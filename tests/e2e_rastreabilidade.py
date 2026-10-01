"""Rastreabilidade: lote de concreto, corpos de prova, certificados do aço, RG da peça e trava de expedição."""
import json, os, sys
import requests

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA, LOTE, LOTE2, PLACA = "RASTRO-TESTE", "LT-TESTE-01", "LT-TESTE-02", "TST9A99"
CORRIDAS = ["CR-TESTE-10", "CR-TESTE-125"]
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


s = requests.Session()
s.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    r = s.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo)
    try:
        return r.json().get("message", {})
    except ValueError:
        return {"success": False, "error": r.text[:150]}


def limpar():
    api("config_rastreabilidade", exigir_rg_expedicao=False)
    api("delete_obra", codigo_obra=OBRA)
    api("delete_caminhao", placa=PLACA)
    for doctype, nomes in (("Corpo Prova", None), ("Lote Concreto", [LOTE, LOTE2]), ("Certificado Aco", CORRIDAS)):
        if doctype == "Corpo Prova":
            for lote in (LOTE, LOTE2):
                r = s.get(f"{URL}/api/resource/Corpo Prova", params={"filters": json.dumps([["lote", "=", lote]]), "limit_page_length": 50}).json().get("data", [])
                for x in r:
                    s.delete(f"{URL}/api/resource/Corpo Prova/{x['name']}")
        else:
            for n in nomes:
                s.delete(f"{URL}/api/resource/{doctype}/{n}")


limpar()
pecas = [{"cod": f"RG{i}", "tag": f"RG {i}", "produto": "Pilar", "secao": "30x30", "comp": 3.0, "vol": 0.27, "peso": 675,
          "ferros": [{"posicao": "1", "bitola_mm": 10.0, "quantidade": 4, "comp_unit_m": 3.0, "comp_total_m": 12.0, "peso_kg": 7.4},
                     {"posicao": "2", "bitola_mm": 12.5, "quantidade": 2, "comp_unit_m": 3.0, "comp_total_m": 6.0, "peso_kg": 5.8}]}
         for i in (1, 2, 3)]
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Rastro", "cliente": "Cliente", "fck": "35 MPa"}), pieces_data=json.dumps(pecas))
cods = [p["codigo_peca"] for p in api("get_pieces", obra=OBRA)["pieces"]]
ok("três peças da obra de teste", len(cods) == 3, str(cods))

print("[Lote de concreto]")
r = api("registrar_lote_concreto", codigo=LOTE, fck_especificado=35, usina="Usina Norte", traco="1:2:3", slump_cm=10, temperatura_c=24, volume_m3=8, nota_fiscal="NF-123")
ok("cadastra o lote", r.get("success"), str(r))
ok("recusa lote repetido", not api("registrar_lote_concreto", codigo=LOTE, fck_especificado=35).get("success"))
ok("recusa lote sem fck", not api("registrar_lote_concreto", codigo="LT-X", fck_especificado=0).get("success"))
ok("recusa concretagem no futuro", not api("registrar_lote_concreto", codigo="LT-X", fck_especificado=30, data_concretagem="2999-01-01").get("success"))
lote = next(l for l in api("get_rastreabilidade")["lotes"] if l["codigo"] == LOTE)
ok("começa aguardando ruptura", lote["status"] == "Aguardando ruptura" and lote["pecas"] == 0)

print("[Ligar peças ao lote e ao aço]")
r = api("vincular_lote_pecas", lote=LOTE, pecas=json.dumps(cods[:2]))
ok("liga duas peças ao lote", r.get("success") and r["vinculadas"] == 2, str(r))
ok("recusa peça que não existe", not api("vincular_lote_pecas", lote=LOTE, pecas=json.dumps(["NAO-EXISTE"])).get("success"))
api("registrar_certificado_aco", corrida=CORRIDAS[0], bitola_mm=10, fabricante="Aço Brasil", norma="CA-50", nota_fiscal="NF-9")
ok("recusa corrida repetida", not api("registrar_certificado_aco", corrida=CORRIDAS[0], bitola_mm=10).get("success"))
ok("recusa corrida sem bitola", not api("registrar_certificado_aco", corrida="CR-X", bitola_mm=0).get("success"))
ok("recusa corrida sem certificado", not api("vincular_corridas_pecas", pecas=json.dumps(cods[:1]), corridas=json.dumps(["SEM-CERT"])).get("success"))
api("vincular_corridas_pecas", pecas=json.dumps(cods[:2]), corridas=json.dumps([CORRIDAS[0]]))

print("[RG com documentação incompleta]")
rg = api("get_rg_peca", codigo_peca=cods[0])
estados = {c["item"]: c["estado"] for c in rg["conferencias"]}
ok("RG traz peça, obra e fase", rg["peca"]["obra_nome"] == "Obra Rastro" and rg["peca"]["fase_numero"] == 1, str(rg["peca"]))
ok("lote e aço ligados aparecem", rg["lote"]["codigo"] == LOTE and [c["corrida"] for c in rg["certificados"]] == [CORRIDAS[0]])
ok("bitola 12,5 sem certificado é falha", estados["Bitolas cobertas pelos certificados"] == "falha", str(estados))
ok("resistência pendente sem corpo de prova", estados["Resistência do concreto (28 dias)"] == "pendente")
ok("não está completo", rg["completo"] is False)
sem_lote = api("get_rg_peca", codigo_peca=cods[2])
e3 = {c["item"]: c["estado"] for c in sem_lote["conferencias"]}
ok("peça sem lote ainda na fase 1 fica pendente (não falha)", e3["Lote de concreto"] == "pendente" and e3["Certificado do aço"] == "pendente", str(e3))

print("[Corpos de prova]")
r = api("registrar_corpo_prova", lote=LOTE, idade_dias=7, fck_obtido=22)
ok("ruptura aos 7 dias é parcial (não reprova)", r.get("success") and r["resultado"] == "Parcial" and r["status_do_lote"] == "Em ensaio", str(r))
ok("recusa idade inválida", not api("registrar_corpo_prova", lote=LOTE, idade_dias=0, fck_obtido=30).get("success"))
ok("recusa resistência vazia", not api("registrar_corpo_prova", lote=LOTE, idade_dias=28, fck_obtido=0).get("success"))
r = api("registrar_corpo_prova", lote=LOTE, idade_dias=28, fck_obtido=38.4)
ok("28 dias com 38,4 MPa aprova o lote de 35", r["resultado"] == "Aprovado" and r["status_do_lote"] == "Aprovado", str(r))
api("registrar_certificado_aco", corrida=CORRIDAS[1], bitola_mm=12.5, fabricante="Aço Brasil")
api("vincular_corridas_pecas", pecas=json.dumps(cods[:2]), corridas=json.dumps([CORRIDAS[1]]))
rg = api("get_rg_peca", codigo_peca=cods[0])
estados = {c["item"]: c["estado"] for c in rg["conferencias"]}
ok("com as duas bitolas certificadas, o aço fecha", estados["Bitolas cobertas pelos certificados"] == "ok" and estados["Certificado do aço"] == "ok", str(estados))
ok("resistência aprovada no RG", estados["Resistência do concreto (28 dias)"] == "ok")
api("submit_checklist", codigo_peca=cods[0], etapa="2. Armação", aprovado=1)
for _ in range(5):
    api("advance_piece_phase", codigo_peca=cods[0], forcar=True)
    api("advance_piece_phase", codigo_peca=cods[1], forcar=True)
rg = api("get_rg_peca", codigo_peca=cods[0])
ok("peça concluída com tudo ligado: RG completo", rg["completo"] and rg["peca"]["fase_numero"] >= 6, str({c["item"]: c["estado"] for c in rg["conferencias"] if c["estado"] != "ok"}))
ok("histórico de fases com quem e quando", len(rg["fases"]) >= 5 and all(f["usuario"] for f in rg["fases"]))

print("[Trava de expedição]")
api("create_caminhao", placa=PLACA, capacidade_kg=50000)
ok("a exigência fica desligada por padrão", api("config_rastreabilidade")["exigir_rg_expedicao"] is False)
ok("liga a exigência", api("config_rastreabilidade", exigir_rg_expedicao=True)["exigir_rg_expedicao"] is True)
for _ in range(6):
    api("advance_piece_phase", codigo_peca=cods[2], forcar=True)
r = api("create_romaneio", obra=OBRA, caminhao=PLACA, data_expedicao="2026-12-01", pecas=json.dumps([cods[2]]))
ok("peça sem lote nem aço não sai com a exigência ligada", not r.get("success") and "RG da peça incompleto" in r.get("error", ""), r.get("error", "")[:140])
r = api("create_romaneio", obra=OBRA, caminhao=PLACA, data_expedicao="2026-12-01", pecas=json.dumps([cods[0]]))
ok("peça com RG completo sai", r.get("success"), str(r)[:140])
rg = api("get_rg_peca", codigo_peca=cods[0])
ok("o RG mostra o romaneio", rg["romaneio"] and rg["romaneio"]["caminhao"] == PLACA)
api("config_rastreabilidade", exigir_rg_expedicao=False)
r = api("create_romaneio", obra=OBRA, caminhao=PLACA, data_expedicao="2026-12-02", pecas=json.dumps([cods[2]]))
ok("com a exigência desligada a peça sai", r.get("success"), str(r)[:140])

print("[Lote reprovado]")
api("registrar_lote_concreto", codigo=LOTE2, fck_especificado=40)
api("vincular_lote_pecas", lote=LOTE2, pecas=json.dumps([cods[1]]))
r = api("registrar_corpo_prova", lote=LOTE2, idade_dias=28, fck_obtido=31)
ok("28 dias abaixo do fck reprova o lote", r["resultado"] == "Reprovado" and r["status_do_lote"] == "Reprovado" and r["rnc_abertas"] == 1, str(r))
rncs = api("get_nao_conformidades", codigo_peca=cods[1], status="Aberta")["nao_conformidades"]
ok("a peça do lote ganha uma não conformidade aberta", len(rncs) == 1 and LOTE2 in rncs[0]["descricao"])
api("registrar_corpo_prova", lote=LOTE2, idade_dias=28, fck_obtido=30)
ok("repetir a reprovação não duplica a não conformidade", len(api("get_nao_conformidades", codigo_peca=cods[1], status="Aberta")["nao_conformidades"]) == 1)
ok("lote reprovado não recebe novas peças", not api("vincular_lote_pecas", lote=LOTE2, pecas=json.dumps([cods[2]])).get("success"))
rg = api("get_rg_peca", codigo_peca=cods[1])
estados = {c["item"]: c["estado"] for c in rg["conferencias"]}
ok("o RG mostra a falha de resistência e a não conformidade", estados["Resistência do concreto (28 dias)"] == "falha" and estados["Não conformidades"] == "falha")

print("[Permissões]")
ok("ler o RG exige sessão", requests.post(f"{URL}/api/method/frappe.precast_api.get_rg_peca", json={"codigo_peca": cods[0]}).status_code in (401, 403))

limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
