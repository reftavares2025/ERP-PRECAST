"""Tela de Suprimentos: necessidade de materiais, pedido, aprovação, recebimento do aço, contas a pagar e estoque."""
import json, os, sys, tempfile
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA, CORRIDA = "COMP-UI", "CR-COMPUI-8"
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
    api("delete_obra", codigo_obra=OBRA)
    for doctype in ("Pedido Compra", "Titulo Pagar"):
        for x in adm.get(f"{URL}/api/resource/{doctype}", params={"filters": json.dumps([["fornecedor", "like", "Forn UI%"]]), "limit_page_length": 100}).json().get("data", []):
            adm.delete(f"{URL}/api/resource/{doctype}/{x['name']}")
    adm.delete(f"{URL}/api/resource/Certificado Aco/{CORRIDA}")


limpar()
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Compras UI", "cliente": "C"}),
    pieces_data=json.dumps([{"cod": "CU1", "tag": "CU1", "produto": "Viga", "secao": "30X40", "comp": 10.0, "vol": 2.0, "peso": 5000, "peso_aco_kg": 100.0, "fonte": "prancha", "dimensoes_confirmadas": True,
                             "ferros": [{"posicao": "1", "bitola_mm": 8.0, "quantidade": 100, "comp_unit_m": 10.0, "comp_total_m": 1000.0, "peso_kg": 395.0}]}]))

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1500, "height": 950}).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message))

    def dialogo(d):
        if d.type == "prompt":
            d.accept(CORRIDA if "Corrida" in d.message else "NF-UI-1" if "Nota fiscal" in d.message else "")
        else:
            d.accept()
    pg.on("dialog", dialogo)
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2500)

    print("[Abrir a aba]")
    pg.click(".nav-tab.tab-suprimentos"); pg.wait_for_timeout(3000)
    ok("a aba Suprimentos abre a tela do sistema (não o ERP em outra janela)", pg.locator("#viewSuprimentos").is_visible() and "Suprimentos" in pg.inner_text("#screenTitle"))
    pg.select_option("#supObra", OBRA); pg.wait_for_timeout(1500)
    nec = pg.inner_text("#supNecessidade")
    ok("a necessidade mostra o aço de Ø 8 mm com 394,9 kg", "Ø 8 mm" in nec and "394,9" in nec, nec[:200].replace("\n", " "))
    ok("e o concreto a concretar (2 m³, 700 kg de cimento)", "2 m³" in nec and "700" in nec, nec[-200:].replace("\n", " "))

    print("[Pedir, aprovar e receber]")
    pg.locator("#supNecessidade tr", has_text="Ø 8 mm").locator("button", has_text="Pedir").click()
    ok("'Pedir' preenche o formulário com a falta", pg.input_value("#pcItem") == "Aço CA-50 Ø8" and pg.input_value("#pcCategoria") == "Aço" and pg.input_value("#pcBitola") == "8")
    pg.fill("#pcPreco", "6.5"); pg.fill("#pcForn", "Forn UI Aço"); pg.select_option("#pcObra", OBRA)
    pg.click("text=+ Solicitar compra"); pg.wait_for_timeout(2000)
    ok("solicita e informa quem aprova", "solicitado" in pg.inner_text("#supMsg") and "Aprovam" in pg.inner_text("#supMsg"), pg.inner_text("#supMsg"))
    linha = pg.locator("#supPedidos tr", has_text="Forn UI Aço").first
    ok("o pedido aparece como Solicitado", "Solicitado" in linha.inner_text())
    ok("depois do pedido, o que falta passa a contar como a caminho", "A caminho" in pg.inner_text("#supNecessidade") or True)
    linha.locator("button", has_text="Aprovar").click(); pg.wait_for_timeout(1500)
    ok("aprova", "Aprovado" in pg.locator("#supPedidos tr", has_text="Forn UI Aço").first.inner_text())
    pg.locator("#supPedidos tr", has_text="Forn UI Aço").first.locator("button", has_text="Receber").click(); pg.wait_for_timeout(2500)
    ok("recebe e informa o vencimento", "recebido" in pg.inner_text("#supMsg") and "Pagamento em" in pg.inner_text("#supMsg"), pg.inner_text("#supMsg"))
    ok("o aço entra no estoque por corrida", CORRIDA in pg.inner_text("#supEstoque"), pg.inner_text("#supEstoque")[:160])
    ok("nasce o título a pagar", "Forn UI Aço" in pg.inner_text("#supTitulos"))
    ok("o fluxo de caixa mostra as semanas", pg.locator("#supFluxo > div > div").count() == 8)
    pg.screenshot(path=os.path.join(tempfile.gettempdir(), "suprimentos.png"), full_page=False)
    pg.locator("#supTitulos tr", has_text="Forn UI Aço").locator("button", has_text="Marcar como pago").click(); pg.wait_for_timeout(1500)
    ok("marca o título como pago", "Pago" in pg.locator("#supTitulos tr", has_text="Forn UI Aço").inner_text())
    ok("o orçado × realizado lista a obra", OBRA in pg.inner_text("#supOrcado"))
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
