"""Telas de logística: planejar cargas, equipamentos de içamento, plano de içamento e cronograma da montagem."""
import json, os, sys, tempfile
from datetime import date, timedelta
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA, PLACA, EQUIP = "MONT-UI", "TSTUI99", "GUINDASTE-UI"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


adm = requests.Session()
adm.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    return adm.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo).json().get("message", {})


def limpar():
    for r in api("get_romaneios").get("romaneios", []):
        if r["obra"] == OBRA:
            api("delete_romaneio", codigo=r["codigo"])
    api("delete_obra", codigo_obra=OBRA)
    api("delete_caminhao", placa=PLACA)
    api("excluir_equipamento_icamento", nome=EQUIP)


def peca(cod, produto, comp, peso):
    return {"cod": cod, "tag": cod, "produto": produto, "secao": "30X40", "comp": comp, "vol": round(peso / 2500, 3), "peso": peso, "peso_aco_kg": 50.0,
            "ferros": [], "fonte": "prancha", "dimensoes_confirmadas": True}


limpar()
api("create_caminhao", placa=PLACA, capacidade_kg=20000, comprimento_m=13)
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Montagem UI", "cliente": "C"}),
    pieces_data=json.dumps([peca("UF1", "BLOCO", 3.0, 3000), peca("UP1", "PILAR", 9.0, 9000), peca("UP2", "PILAR", 9.0, 9000), peca("UV1", "VIGA", 12.0, 6000)]))
cods = [p["codigo_peca"] for p in api("get_pieces", obra=OBRA)["pieces"]]
for c in cods:
    for _ in range(5):
        api("advance_piece_phase", codigo_peca=c, forcar=True)

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1500, "height": 900}).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message)); pg.on("dialog", lambda d: d.accept())
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2500)
    pg.evaluate("switchModule('logistica')"); pg.wait_for_timeout(1500)

    print("[Planejar cargas]")
    pg.click("text=🧮 Planejar Cargas"); pg.wait_for_timeout(2000)
    ok("a sub-aba abre", pg.locator("#viewPlanoCargas").is_visible())
    pg.select_option("#cargasObra", OBRA)
    pg.click("text=Ordem de montagem padrão"); pg.wait_for_timeout(1200)
    ok("grava a ordem de montagem padrão", "Ordem de montagem gravada para 4" in pg.inner_text("#cargasMsg"), pg.inner_text("#cargasMsg"))
    pg.click("#viewPlanoCargas >> text=🧮 Planejar cargas"); pg.wait_for_timeout(2500)
    corpo = pg.inner_text("#cargasResultado")
    ok("duas viagens (27 t não cabem num caminhão de 20 t)", "VIAGENS" in corpo.upper() and corpo.count("Viagem ") == 2, corpo[:160].replace("\n", " "))
    ok("mostra a ordem de carregamento invertida em cada viagem", "UP1 → UF1" in corpo and "UV1 → UP2" in corpo, corpo[:400].replace("\n", " "))
    pg.screenshot(path=os.path.join(tempfile.gettempdir(), "cargas.png"))
    pg.click("text=✓ Criar os romaneios"); pg.wait_for_timeout(3000)
    ok("cria os romaneios", "romaneio(s) criado(s)" in pg.inner_text("#cargasMsg"), pg.inner_text("#cargasMsg"))
    ok("os romaneios existem no sistema", sum(1 for r in api("get_romaneios")["romaneios"] if r["obra"] == OBRA) == 2)

    print("[Equipamento e plano de içamento]")
    pg.click("text=🏗️ Içamento e Cronograma"); pg.wait_for_timeout(2000)
    pg.fill("#eqNome", EQUIP); pg.fill("#eqTipo", "Guindaste"); pg.fill("#eqCap", "60000")
    pg.fill("#eqTabela", "8 ; 40000\n12 ; 25000\n16 ; 14000\n20 ; 8000")
    pg.click("text=+ Salvar equipamento"); pg.wait_for_timeout(1800)
    ok("o equipamento aparece na lista com a tabela", EQUIP in pg.inner_text("#eqLista") and "12 m: 25000 kg" in pg.inner_text("#eqLista"), pg.inner_text("#eqLista")[:150])
    pg.select_option("#icObra", OBRA); pg.select_option("#icEquip", EQUIP); pg.fill("#icRaio", "16")
    pg.click("text=Conferir"); pg.wait_for_timeout(1800)
    res = pg.inner_text("#icResultado")
    ok("a 16 m (14 t) a peça de 9 t (11,25 t com o fator) fica em atenção", "atenção" in res and "UP1" in res, res[:200].replace("\n", " "))

    print("[Cronograma]")
    pg.select_option("#crObra", OBRA); pg.fill("#crRitmo", "2")
    pg.fill("#crInicio", str(date.today() - timedelta(days=10)))
    pg.click("text=Planejar e gravar datas"); pg.wait_for_timeout(2500)
    cr = pg.inner_text("#crResultado")
    ok("mostra o desvio, o término e as atrasadas", "atrasada" in cr.lower() and "Término planejado".lower() in cr.lower() and "UF1" in cr, cr[:200].replace("\n", " "))
    ok("desenha a curva S", pg.locator("#crResultado svg polyline").count() >= 1)
    pg.screenshot(path=os.path.join(tempfile.gettempdir(), "cronograma.png"))
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
