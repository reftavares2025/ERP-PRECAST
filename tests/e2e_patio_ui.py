"""Tela do planejador de pátio: mapa de ocupação, ciclo da forma, sugestão e aplicação da programação."""
import json, os, sys
from datetime import date, timedelta
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA, FORMAS = "PATIO-UI", ["PU-PISTA", "PU-FORMA"]
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
    for p in api("get_pieces", obra=OBRA).get("pieces", []):
        api("unprogram_piece", codigo_peca=p["codigo_peca"])
    api("delete_obra", codigo_obra=OBRA)
    for f in FORMAS:
        api("delete_forma_pista", codigo=f)


def peca(cod, comp, peso):
    return {"cod": cod, "tag": cod, "produto": "Viga", "secao": "30X40", "comp": comp, "vol": round(peso / 2500, 3), "peso": peso, "peso_aco_kg": 50.0,
            "ferros": [], "fonte": "prancha", "dimensoes_confirmadas": True}


limpar()
api("create_forma_pista", codigo="PU-PISTA", tipo="Pista de Protensão", comprimento_m=20, largura_m=1.2, capacidade_kg=20000)
api("create_forma_pista", codigo="PU-FORMA", tipo="Fôrma", comprimento_m=10, largura_m=1, capacidade_kg=8000)
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Pátio UI", "cliente": "C"}),
    pieces_data=json.dumps([peca("UA", 8.0, 3000), peca("UB", 8.0, 3000), peca("UC", 30.0, 9000)]))
cod = {p["tag"]: p["codigo_peca"] for p in api("get_pieces", obra=OBRA)["pieces"]}
amanha = date.today() + timedelta(days=1)
api("program_piece", codigo_peca=cod["UA"], forma_pista="PU-PISTA", data_programada=str(amanha))

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1500, "height": 900}).new_page()
    erros, dialogos = [], []
    pg.on("pageerror", lambda e: erros.append(e.message)); pg.on("dialog", lambda d: (dialogos.append(d.message), d.accept()))
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2500)

    print("[Mapa de ocupação]")
    pg.evaluate("switchModule('fabricacao')"); pg.wait_for_timeout(1500)
    pg.click("text=📊 Planejador de Pátio"); pg.wait_for_timeout(2500)
    ok("a sub-aba abre o planejador", pg.locator("#viewPlanejadorPatio").is_visible())
    mapa = pg.inner_text("#patioMapa")
    ok("as formas aparecem no mapa", "PU-PISTA" in mapa and "PU-FORMA" in mapa)
    ok("a pista aparece ocupada pela peça programada (40% = 8 de 20 m)", "40%" in mapa and "UA" in mapa, mapa[:200].replace("\n", " "))
    ok("o card de peças sem forma conta as 2 que faltam", "Sem forma (2)" in pg.inner_text("#patioAlertas") or "SEM FORMA (2)" in pg.inner_text("#patioAlertas").upper())

    print("[Ciclo da forma]")
    pg.locator("#patioMapa tr", has_text="PU-FORMA").locator("input").fill("3"); pg.locator("#patioMapa tr", has_text="PU-FORMA").locator("input").press("Tab"); pg.wait_for_timeout(1200)
    ok("salva o ciclo da forma", next(f for f in api("get_formas_pistas")["formas_pistas"] if f["codigo"] == "PU-FORMA")["ciclo_dias"] == 3)

    print("[Sugerir e aplicar]")
    pg.select_option("#patioObra", OBRA)
    pg.click("text=🔮 Sugerir programação"); pg.wait_for_timeout(2500)
    sug = pg.inner_text("#patioSugestoes")
    ok("sugere a peça UB e explica que a UC (30 m) não cabe", "UB" in sug and "UC" in sug and "não cabe" in sug, sug[:260].replace("\n", " "))
    pg.click("text=✓ Aplicar programação"); pg.wait_for_timeout(3000)
    ok("aplica e avisa quantas foram programadas", "1 peça(s) programada(s)" in pg.inner_text("#patioMsg"), pg.inner_text("#patioMsg"))
    ok("a peça UB ficou programada no sistema", next(p for p in api("get_pieces", obra=OBRA)["pieces"] if p["tag"] == "UB").get("forma_pista") in FORMAS)
    pg.screenshot(path=os.path.join(os.environ.get("TEMP", "."), "patio.png"))
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
