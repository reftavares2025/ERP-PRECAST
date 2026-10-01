"""Tela de rastreabilidade na aba Qualidade e o RG da peça (Fabricação)."""
import json, os, sys
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA, LOTE, CORRIDA = "RASTRO-UI", "LT-UI-01", "CR-UI-10"
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
    api("config_rastreabilidade", exigir_rg_expedicao=False)
    api("delete_obra", codigo_obra=OBRA)
    for x in adm.get(f"{URL}/api/resource/Corpo Prova", params={"filters": json.dumps([["lote", "=", LOTE]])}).json().get("data", []):
        adm.delete(f"{URL}/api/resource/Corpo Prova/{x['name']}")
    adm.delete(f"{URL}/api/resource/Lote Concreto/{LOTE}")
    adm.delete(f"{URL}/api/resource/Certificado Aco/{CORRIDA}")


limpar()
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra UI", "cliente": "Cliente", "fck": "35 MPa"}),
    pieces_data=json.dumps([{"cod": f"UI{i}", "tag": f"UI {i}", "produto": "Pilar", "secao": "30x30", "comp": 3.0, "vol": 0.27, "peso": 675,
                             "ferros": [{"posicao": "1", "bitola_mm": 10.0, "quantidade": 4, "comp_unit_m": 3.0, "comp_total_m": 12.0, "peso_kg": 7.4}]} for i in (1, 2)]))

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message)); pg.on("dialog", lambda d: d.accept())
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2500)

    print("[Aba Qualidade]")
    pg.evaluate("switchModule('qualidade')"); pg.wait_for_timeout(2500)
    ok("a seção de rastreabilidade aparece", pg.locator("#rastroLoteCodigo").is_visible())
    pg.fill("#rastroLoteCodigo", LOTE); pg.fill("#rastroLoteFck", "35"); pg.fill("#rastroLoteUsina", "Usina Teste")
    pg.click("text=+ Cadastrar lote"); pg.wait_for_timeout(1500)
    ok("cadastra o lote pela tela", "cadastrado" in pg.inner_text("#rastroMsg"), pg.inner_text("#rastroMsg"))
    ok("o lote entra na tabela com 'Aguardando ruptura'", "Aguardando ruptura" in pg.inner_text("#rastroLotesTbody") and LOTE in pg.inner_text("#rastroLotesTbody"))
    pg.click("text=+ Cadastrar lote"); pg.wait_for_timeout(800)
    ok("campo obrigatório vazio mostra o motivo", "código do lote" in pg.inner_text("#rastroMsg").lower(), pg.inner_text("#rastroMsg"))

    pg.fill("#rastroAcoCorrida", CORRIDA); pg.fill("#rastroAcoBitola", "10"); pg.fill("#rastroAcoFabricante", "Aço Teste")
    pg.click("text=+ Cadastrar corrida"); pg.wait_for_timeout(1500)
    ok("cadastra a corrida de aço", CORRIDA in pg.inner_text("#rastroAcoTbody"))

    pg.select_option("#rastroCpLote", LOTE); pg.fill("#rastroCpIdade", "28"); pg.fill("#rastroCpFck", "40")
    pg.click("text=+ Registrar ruptura"); pg.wait_for_timeout(1500)
    ok("ruptura aprova o lote", "aprovado" in pg.inner_text("#rastroMsg").lower() and "Aprovado" in pg.inner_text("#rastroLotesTbody"), pg.inner_text("#rastroMsg"))
    ok("a ruptura aparece na linha do lote", "28d: 40 MPa" in pg.inner_text("#rastroLotesTbody"))

    pg.select_option("#rastroVincObra", OBRA); pg.wait_for_timeout(400)
    ok("lista as peças da obra escolhida", pg.locator("#rastroVincPecas input").count() == 2)
    pg.select_option("#rastroVincLote", LOTE)
    pg.click("text=Marcar todas"); pg.click("text=Ligar lote às marcadas"); pg.wait_for_timeout(1500)
    ok("liga o lote às duas peças", "ligado a 2" in pg.inner_text("#rastroMsg"), pg.inner_text("#rastroMsg"))
    pg.select_option("#rastroVincCorridas", CORRIDA)
    pg.click("text=Ligar aço às marcadas"); pg.wait_for_timeout(1500)
    ok("liga o aço às duas peças", "Aço ligado a 2" in pg.inner_text("#rastroMsg"), pg.inner_text("#rastroMsg"))
    ok("a tabela mostra 2 peças no lote", "Usina Teste" in pg.inner_text("#rastroLotesTbody") and pg.locator("#rastroLotesTbody tr").first.inner_text().split("\t")[4].strip() == "2")

    pg.check("#rastroExigirRg"); pg.wait_for_timeout(1000)
    ok("liga a exigência de RG para o romaneio", api("config_rastreabilidade")["exigir_rg_expedicao"] is True)
    pg.uncheck("#rastroExigirRg"); pg.wait_for_timeout(1000)
    ok("e desliga", api("config_rastreabilidade")["exigir_rg_expedicao"] is False)

    print("[RG da peça]")
    pg.evaluate("switchModule('fabricacao')"); pg.wait_for_timeout(2500)
    pg.select_option("#fabObraFilter", OBRA); pg.wait_for_timeout(600)
    pg.locator("#fabricacaoTableBody tr", has_text="UI 1").locator("button", has_text="RG").click(); pg.wait_for_timeout(2000)
    corpo = pg.inner_text("#rgCorpo")
    ok("o modal abre com a peça e a obra", "UI 1" in corpo and "Obra UI" in corpo, corpo[:80])
    ok("mostra RG incompleto (peça ainda na fase 1)", "RG INCOMPLETO" in corpo)
    ok("lote, usina e ruptura aparecem", LOTE in corpo and "Usina Teste" in corpo and "40 MPa" in corpo)
    ok("a corrida aparece com o fabricante", CORRIDA in corpo and "Aço Teste" in corpo)
    ok("as conferências aparecem com os estados", "Fabricação concluída" in corpo and "pendente" in corpo)
    pg.screenshot(path=os.path.join(os.environ.get("TEMP", "."), "rg_peca.png"))
    pg.evaluate("fecharRgPeca()")
    ok("fecha o modal", not pg.locator("#modalRgPeca").is_visible())
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
