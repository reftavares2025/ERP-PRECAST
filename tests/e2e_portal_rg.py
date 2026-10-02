"""O RG da peça no portal do cliente: só abre com o link válido e o dossiê ligado, e sem dados internos."""
import json, os, sys
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA, LOTE, CORRIDA = "PORTAL-RG", "LT-PRG-01", "CR-PRG-10"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


adm = requests.Session()
adm.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    return adm.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo).json().get("message", {})


def publico(metodo, **params):
    r = requests.get(f"{URL}/api/method/frappe.precast_api.{metodo}", params=params)
    try:
        return r.json().get("message", {})
    except ValueError:
        return {"success": False}


def limpar():
    api("delete_obra", codigo_obra=OBRA)
    for x in adm.get(f"{URL}/api/resource/Corpo Prova", params={"filters": json.dumps([["lote", "=", LOTE]])}).json().get("data", []):
        adm.delete(f"{URL}/api/resource/Corpo Prova/{x['name']}")
    adm.delete(f"{URL}/api/resource/Lote Concreto/{LOTE}")
    adm.delete(f"{URL}/api/resource/Certificado Aco/{CORRIDA}")


limpar()
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Portal RG", "cliente": "C", "fck": "35 MPa"}),
    pieces_data=json.dumps([{"cod": "PR1", "tag": "PR1", "produto": "Pilar", "secao": "30X40", "comp": 9.0, "vol": 1.0, "peso": 2500, "peso_aco_kg": 50.0, "fonte": "prancha", "dimensoes_confirmadas": True,
                             "ferros": [{"posicao": "1", "bitola_mm": 10.0, "quantidade": 4, "comp_unit_m": 3.0, "comp_total_m": 12.0, "peso_kg": 7.4}]}]))
cod = api("get_pieces", obra=OBRA)["pieces"][0]["codigo_peca"]
api("registrar_lote_concreto", codigo=LOTE, fck_especificado=35, usina="Usina Secreta", nota_fiscal="NF-INTERNA-9")
api("registrar_corpo_prova", lote=LOTE, idade_dias=28, fck_obtido=40)
api("vincular_lote_pecas", lote=LOTE, pecas=json.dumps([cod]))
api("registrar_certificado_aco", corrida=CORRIDA, bitola_mm=10, fabricante="Aço Brasil", nota_fiscal="NF-ACO-INTERNA")
api("vincular_corridas_pecas", pecas=json.dumps([cod]), corridas=json.dumps([CORRIDA]))
api("submit_checklist", codigo_peca=cod, etapa="2. Armação", aprovado=1, inspetor="Fulano Inspetor Interno")
api("abrir_nao_conformidade", codigo_peca=cod, descricao="Segredo interno da NC: trinca no topo")
for _ in range(2):
    api("advance_piece_phase", codigo_peca=cod, forcar=True)

url = api("get_link_portal", codigo_obra=OBRA)["url"]
token = url.split("t=")[1]

print("[Desligado por padrão]")
d = publico("get_rg_publico", codigo_obra=OBRA, t=token, tag="PR1")
ok("sem o dono ligar, o dossiê não abre mesmo com o link certo", not d.get("success") and "dossiê" in d.get("error", ""), str(d.get("error")))

print("[Ligado]")
api("salvar_config_portal", codigo_obra=OBRA, ativo=True, secoes=json.dumps({"dossie": True}))
d = publico("get_rg_publico", codigo_obra=OBRA, t=token, tag="PR1")
ok("abre o dossiê da peça pelo nome dela", d.get("success") and d["peca"]["tag"] == "PR1", str(d.get("error")))
ok("traz o lote, a ruptura e o certificado do aço", d["lote"]["codigo"] == LOTE and d["lote"]["status"] == "Aprovado" and d["lote"]["corpos_de_prova"][0]["fck_obtido"] == 40 and d["certificados"][0]["corrida"] == CORRIDA)
ok("traz as fases (com data) e as inspeções (com resultado)", len(d["fases"]) >= 2 and d["inspecoes"][0]["aprovado"] == 1)
bruto = json.dumps(d, ensure_ascii=False)
ok("não vaza nome de inspetor, usuário, nota fiscal, usina nem o texto interno da não conformidade", all(x not in bruto for x in ("Fulano", "Administrator", "NF-INTERNA", "NF-ACO", "Usina Secreta", "trinca no topo")), "")
ok("a não conformidade aparece só como situação", any(c["item"] == "Não conformidades" and c["detalhe"] == "Em tratamento pela empresa" for c in d["conferencias"]))
ok("peça que não existe na obra é recusada", not publico("get_rg_publico", codigo_obra=OBRA, t=token, tag="XX9").get("success"))
ok("token errado é recusado", not publico("get_rg_publico", codigo_obra=OBRA, t="abc", tag="PR1").get("success"))
ok("sem token é recusado", not publico("get_rg_publico", codigo_obra=OBRA, tag="PR1").get("success"))
ok("outra obra não abre com o token desta", not publico("get_rg_publico", codigo_obra="OUTRA-OBRA", t=token, tag="PR1").get("success"))
api("salvar_config_portal", codigo_obra=OBRA, ativo=False, secoes=json.dumps({"dossie": True}))
ok("com o portal desativado, o dossiê fecha junto", not publico("get_rg_publico", codigo_obra=OBRA, t=token, tag="PR1").get("success"))
api("salvar_config_portal", codigo_obra=OBRA, ativo=True, secoes=json.dumps({"dossie": True}))
api("renovar_link_portal", codigo_obra=OBRA)
ok("renovar o link invalida o token antigo também para o dossiê", not publico("get_rg_publico", codigo_obra=OBRA, t=token, tag="PR1").get("success"))
url = api("get_link_portal", codigo_obra=OBRA)["url"]

print("[Na página do cliente]")
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 420, "height": 900}).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message))
    pg.goto(URL + url, wait_until="networkidle"); pg.wait_for_timeout(2500)
    peca = pg.locator(".peca", has_text="PR1")
    ok("a peça aparece clicável quando o dossiê está ligado", peca.count() == 1 and peca.get_attribute("data-tag") == "PR1")
    peca.click(); pg.wait_for_timeout(2500)
    corpo = pg.inner_text("#dossieCorpo")
    ok("o dossiê abre com a conferência, o lote e o certificado", "Dossiê da peça PR1" in corpo and LOTE in corpo and CORRIDA in corpo and "Conferência" in corpo.title() or "CONFERÊNCIA" in corpo.upper(), corpo[:200].replace("\n", " "))
    ok("a tela do cliente não mostra dados internos", "Fulano" not in corpo and "trinca" not in corpo and "NF-" not in corpo)
    pg.click("text=Fechar"); pg.wait_for_timeout(500)
    ok("fecha o dossiê", not pg.locator("#dossieFundo.aberto").count())
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

api("salvar_config_portal", codigo_obra=OBRA, ativo=True, secoes=json.dumps({"dossie": False}))
limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
