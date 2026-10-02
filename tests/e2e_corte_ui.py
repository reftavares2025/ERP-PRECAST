"""Tela do plano de corte do aço (Fabricação > Plano de Corte): gerar, ver, baixar a planilha e mudar a situação."""
import csv, json, os, sys, tempfile
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA = "CORTE-UI"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


adm = requests.Session()
adm.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    return adm.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo).json().get("message", {})


def ferro(pos, bitola, qtd, comp):
    return {"posicao": str(pos), "bitola_mm": bitola, "quantidade": qtd, "comp_unit_m": comp, "comp_total_m": qtd * comp, "peso_kg": 1.0}


F = [ferro(1, 10.0, 4, 3.0), ferro(2, 12.5, 2, 8.0)]
api("config_corte", barra_m=12, traspasse_diametros=40, retalho_minimo_m=0.5)
api("delete_obra", codigo_obra=OBRA)
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Corte UI", "cliente": "C"}),
    pieces_data=json.dumps([{"cod": f"CU{i}", "tag": f"CU{i}", "produto": "Pilar", "secao": "30X40", "comp": 8.0, "vol": 0.96, "peso": 2400, "peso_aco_kg": 50.0,
                             "ferros": F, "fonte": "prancha", "dimensoes_confirmadas": True} for i in (1, 2, 3)]))

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message)); pg.on("dialog", lambda d: d.accept())
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2500)

    print("[Abrir a tela]")
    pg.evaluate("switchModule('fabricacao')"); pg.wait_for_timeout(1500)
    pg.click("text=✂️ Plano de Corte"); pg.wait_for_timeout(2000)
    ok("a sub-aba abre o plano de corte", pg.locator("#viewPlanoCorte").is_visible() and "Plano de Corte" in pg.inner_text("#screenTitle"))
    ok("os parâmetros vêm preenchidos", pg.input_value("#corteBarra") == "12" and pg.input_value("#corteTraspasse") == "40")
    pg.select_option("#corteObra", OBRA); pg.wait_for_timeout(1500)
    ok("lista as 3 peças da obra em Corte e Dobra", pg.locator("#cortePecas input").count() == 3)

    print("[Gerar]")
    pg.click("text=✂️ Gerar plano de corte"); pg.wait_for_timeout(1200)
    ok("sem marcar peça, pede para marcar", "Marque as peças" in pg.inner_text("#corteMsg"))
    pg.click("text=Marcar todas livres"); pg.click("text=✂️ Gerar plano de corte"); pg.wait_for_timeout(3000)
    corpo = pg.inner_text("#corteResultado")
    baixo = corpo.lower()   # os títulos aparecem em maiúsculas na tela
    ok("mostra o plano com barras e perda", "plano #1" in baixo and "barras de 12 m" in baixo and "perda" in baixo, corpo[:120].replace("\n", " "))
    ok("Ø10 em 3 barras e Ø12,5 em 6", "ø 10 mm · 3 barra" in baixo and "ø 12.5 mm · 6 barra" in baixo, baixo[:300].replace("\n", " "))
    ok("mostra os cortes de cada barra", "4 × 3,00 m" in corpo and "1 × 8,00 m" in corpo)
    ok("lista de corte por peça", "CU1" in corpo and "CU3" in corpo)
    ok("as peças do plano saem da lista de livres", pg.locator("#cortePecas input").count() == 0 and "plano" in pg.inner_text("#cortePecas"))
    ok("o plano entra no histórico", "Gerado" in pg.inner_text("#corteHistorico"))
    pg.screenshot(path=os.path.join(tempfile.gettempdir(), "plano_corte.png"))

    print("[Planilha]")
    with pg.expect_download() as dl:
        pg.click("text=⬇️ Planilha (CSV)")
    caminho = dl.value.path()
    linhas = list(csv.reader(open(caminho, encoding="utf-8-sig"), delimiter=";"))
    ok("o CSV tem cabeçalho e uma linha por corte (18 de Ø10 e 6 de Ø12,5 = 18)", linhas[0] == ["bitola_mm", "barra", "peca", "posicao", "comprimento_mm"] and len(linhas) == 1 + 12 + 6, str(len(linhas)))
    ok("comprimentos em milímetros", {l[4] for l in linhas[1:]} == {"3000", "8000"})
    ok("o nome do arquivo leva obra e número", dl.value.suggested_filename == f"plano-corte-{OBRA}-1.csv", dl.value.suggested_filename)

    print("[Situação]")
    pg.click("text=▶ Iniciar corte"); pg.wait_for_timeout(1500)
    ok("passa para Em corte", "Em corte" in pg.inner_text("#corteResultado") and "Em corte" in pg.inner_text("#corteHistorico"))
    pg.click("#corteResultado >> text=Cancelar"); pg.wait_for_timeout(1800)
    ok("cancelar libera as peças", pg.locator("#cortePecas input").count() == 3 and "Cancelado" in pg.inner_text("#corteHistorico"))

    print("[Parâmetros]")
    pg.fill("#corteBarra", "99"); pg.click("text=Salvar parâmetros"); pg.wait_for_timeout(1000)
    ok("barra impossível é recusada com o motivo", "entre" in pg.inner_text("#corteMsg"), pg.inner_text("#corteMsg"))
    pg.fill("#corteBarra", "6"); pg.click("text=Salvar parâmetros"); pg.wait_for_timeout(1000)
    ok("barra de 6 m é aceita", api("config_corte")["barra_m"] == 6.0)
    pg.click("text=Marcar todas livres"); pg.click("text=✂️ Gerar plano de corte"); pg.wait_for_timeout(3000)
    ok("o plano novo usa a barra de 6 m e avisa das emendas", "barras de 6 m" in pg.inner_text("#corteResultado").lower() and "emenda" in pg.inner_text("#corteResultado").lower())
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

api("config_corte", barra_m=12)
api("delete_obra", codigo_obra=OBRA)
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
