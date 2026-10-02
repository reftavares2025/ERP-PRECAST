"""Telas de Segurança, Manutenção da frota e dos direitos do titular (LGPD) em Equipe."""
import json, os, sys, tempfile
from datetime import date, timedelta
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
PESSOA, ATIVO, TITULAR = "Pessoa SST Tela", "SST-TELA-PONTE", "titular.lgpd@teste.local"
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
    api("config_seguranca", exigir_treinamento=False)
    api("excluir_ativo_operacional", nome=ATIVO)
    for x in adm.get(f"{URL}/api/resource/Registro SST", params={"filters": json.dumps([["pessoa", "=", PESSOA]]), "limit_page_length": 100}).json().get("data", []):
        adm.delete(f"{URL}/api/resource/Registro SST/{x['name']}")
    for doctype, campo in (("Rosto Operador", "usuario"), ("Consentimento Dados", "titular")):
        for x in adm.get(f"{URL}/api/resource/{doctype}", params={"filters": json.dumps([[campo, "=", TITULAR]]), "limit_page_length": 20}).json().get("data", []):
            adm.delete(f"{URL}/api/resource/{doctype}/{x['name']}")


limpar()
adm.post(f"{URL}/api/resource/Rosto Operador", json={"usuario": TITULAR, "nome": "Titular LGPD Teste", "setores": json.dumps(["Armação"]), "descritor": "[0.1]", "ativo": 1})

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1500, "height": 950}, accept_downloads=True).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message)); pg.on("dialog", lambda d: d.accept())
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2500)

    print("[Segurança]")
    pg.click(".nav-tab.tab-seguranca"); pg.wait_for_timeout(2500)
    ok("a aba abre a tela de segurança", pg.locator("#viewSeguranca").is_visible() and "Segurança" in pg.inner_text("#screenTitle"))
    pg.fill("#segPessoa", PESSOA); pg.fill("#segDocumento", "NR-35"); pg.fill("#segEmissao", str(date.today() - timedelta(days=10))); pg.fill("#segValidade", str(date.today() + timedelta(days=15)))
    pg.click("#viewSeguranca >> text=+ Registrar"); pg.wait_for_timeout(2000)
    ok("registra o treinamento", "Registro salvo" in pg.inner_text("#segMsg"), pg.inner_text("#segMsg"))
    ok("a lista mostra o treinamento a vencer", PESSOA in pg.inner_text("#segRegistros") and "a vencer" in pg.inner_text("#segRegistros").lower())
    ok("o vencimento próximo aparece nos avisos", PESSOA in pg.inner_text("#segVencimentos"))
    ok("a matriz mostra a pessoa com NR-11 pendente e NR-35 em dia", PESSOA in pg.inner_text("#segMatriz") and "pendente" in pg.inner_text("#segMatriz") and "em dia" in pg.inner_text("#segMatriz"), pg.inner_text("#segMatriz")[:160].replace("\n", " "))
    pg.fill("#segPessoa", PESSOA); pg.select_option("#segTipo", "Acidente"); pg.fill("#segObs", "Corte na mão"); pg.fill("#segDias", "2"); pg.check("#segCat")
    pg.click("#viewSeguranca >> text=+ Registrar"); pg.wait_for_timeout(2000)
    ok("o acidente aparece com CAT e dias afastados", "(CAT)" in pg.inner_text("#segRegistros") and "2 dia(s) afastado" in pg.inner_text("#segRegistros"))
    pg.click("#segExigir"); pg.wait_for_timeout(1200)
    ok("liga a exigência de treinamento", api("config_seguranca")["exigir_treinamento"] is True and "treinamento em dia" in pg.inner_text("#segMsg"))
    pg.click("#segExigir"); pg.wait_for_timeout(1200)
    ok("e desliga", api("config_seguranca")["exigir_treinamento"] is False)
    pg.fill("#segPessoa", ""); pg.select_option("#segTipo", "Treinamento")
    pg.click("#viewSeguranca >> text=+ Registrar"); pg.wait_for_timeout(1200)
    ok("registro sem pessoa mostra o motivo", "pessoa" in pg.inner_text("#segMsg").lower(), pg.inner_text("#segMsg"))
    pg.screenshot(path=os.path.join(tempfile.gettempdir(), "seguranca.png"))

    print("[Manutenção da frota]")
    pg.evaluate("switchModule('logistica')"); pg.wait_for_timeout(1200)
    pg.click("text=🔧 Manutenção"); pg.wait_for_timeout(2000)
    ok("a sub-aba abre", pg.locator("#viewManutencao").is_visible())
    pg.fill("#atNome", ATIVO); pg.select_option("#atTipo", "Ponte rolante"); pg.fill("#atLeitura", "1000"); pg.fill("#atIntervalo", "250")
    pg.click("#viewManutencao >> text=+ Salvar equipamento"); pg.wait_for_timeout(1800)
    ok("o equipamento aparece em dia", ATIVO in pg.inner_text("#atLista") and "EM DIA" in pg.inner_text("#atLista").upper(), pg.inner_text("#atLista")[:160].replace("\n", " "))
    pg.locator("#atLista tr", has_text=ATIVO).locator("input[type=number]").fill("1300"); pg.locator("#atLista tr", has_text=ATIVO).locator("input[type=number]").press("Tab"); pg.wait_for_timeout(1800)
    ok("com 1300 h a manutenção está vencida", "VENCIDA" in pg.locator("#atLista tr", has_text=ATIVO).inner_text().upper())
    pg.select_option("#mtAtivo", ATIVO); pg.fill("#mtLeitura", "1300"); pg.fill("#mtCusto", "1800"); pg.fill("#mtDescricao", "Troca de óleo")
    pg.click("#viewManutencao >> text=+ Registrar manutenção"); pg.wait_for_timeout(2500)
    ok("a preventiva zera o intervalo e entra no histórico com o custo", "EM DIA" in pg.locator("#atLista tr", has_text=ATIVO).inner_text().upper() and "Troca de óleo" in pg.inner_text("#mtHistorico") and "1.800,00" in pg.inner_text("#mtHistorico"))
    pg.locator("#atLista tr", has_text=ATIVO).locator("input[type=number]").fill("500"); pg.locator("#atLista tr", has_text=ATIVO).locator("input[type=number]").press("Tab"); pg.wait_for_timeout(1500)
    ok("leitura menor que a atual é recusada com o motivo", "não pode voltar" in pg.inner_text("#atMsg"), pg.inner_text("#atMsg"))

    print("[LGPD em Equipe]")
    pg.evaluate("switchModule('equipe')"); pg.wait_for_timeout(2500)
    linha = pg.locator("#rostosLista tr", has_text="Titular LGPD Teste")
    ok("o operador aparece como sem consentimento registrado (cadastro antigo)", "sem consentimento" in linha.inner_text(), linha.inner_text()[:120].replace("\n", " "))
    with pg.expect_download() as dl:
        linha.locator("button", has_text="Cópia dos dados").click()
    conteudo = json.load(open(dl.value.path(), encoding="utf-8"))
    ok("baixa a cópia dos dados do titular, sem o descritor do rosto", conteudo["cadastro"]["nome"] == "Titular LGPD Teste" and "descritor" not in json.dumps(conteudo), dl.value.suggested_filename)
    linha.locator("button", has_text="Excluir dados").click(); pg.wait_for_timeout(2500)
    ok("excluir os dados tira o operador da lista", "Titular LGPD Teste" not in pg.inner_text("#rostosLista"))
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
