"""Aba Cliente: o dono escolhe o que o cliente de cada obra enxerga, desliga o acesso e troca o link."""
import json, os, re, sys
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA = "PORTAL-TESTE"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


s = requests.Session()
s.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    return s.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo).json().get("message", {})


def publico(url):
    return requests.get(URL + "/api/method/frappe.precast_api.get_status_publico_obra", params={"codigo_obra": OBRA, "t": re.search(r"t=(\w+)", url).group(1)}).json().get("message", {})


api("delete_obra", codigo_obra=OBRA)
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra do Portal", "cliente": "Cliente", "fck": "30 MPa"}),
    pieces_data=json.dumps([{"cod": "PT1", "tag": "PT 1", "produto": "Pilar", "secao": "30x30", "comp": 3.0, "vol": 0.27, "peso": 675},
                            {"cod": "PT2", "tag": "PT 2", "produto": "Viga", "secao": "20x40", "comp": 5.0, "vol": 0.4, "peso": 1000}]))

print("[Servidor]")
url = api("get_link_portal", codigo_obra=OBRA)["url"]
d = publico(url)
ok("sem configuração, o cliente vê tudo", d.get("success") and d["pecas"] is not None and d["peso_t"] is not None and d["entregas"] is not None)
cfg = api("get_config_portal", codigo_obra=OBRA)
ok("config lista as 11 seções; sem configuração o cliente vê tudo, menos o dossiê da peça (só abre quando o dono liga)", len(cfg["secoes"]) == 11 and cfg["config"]["secoes"]["dossie"] is False and all(v for k, v in cfg["config"]["secoes"].items() if k != "dossie"))
r = api("salvar_config_portal", codigo_obra=OBRA, ativo=True, mensagem="Bem-vindo", secoes=json.dumps({"pecas": False, "pesos": False, "entregas": False, "diario": False, "fotos": False}))
d = publico(url)
ok("peças desligadas não saem do servidor", d["pecas"] is None)
ok("pesos desligados não saem do servidor", d["peso_t"] is None and d["volume_m3"] is None)
ok("entregas e diário desligados não saem", d["entregas"] is None and d["diario"] is None)
ok("o que ficou ligado continua", d["contagem"] is not None and d["percentual_produzido"] is not None and d["mensagem"] == "Bem-vindo")
api("salvar_config_portal", codigo_obra=OBRA, ativo=False, secoes=json.dumps({}))
d = publico(url)
ok("acesso desligado bloqueia o cliente", not d.get("success") and "não está disponível" in d.get("error", ""), d.get("error", ""))
api("salvar_config_portal", codigo_obra=OBRA, ativo=True, secoes=json.dumps({}))
api("salvar_config_portal", codigo_obra=OBRA, ativo=True, secoes=json.dumps({c["chave"]: True for c in cfg["secoes"]}))
novo = api("renovar_link_portal", codigo_obra=OBRA)["url"]
ok("link novo é diferente", novo != url)
ok("link antigo deixa de funcionar", not publico(url).get("success"))
ok("link novo funciona", publico(novo).get("success"))
op = requests.Session()
s.delete(URL + "/api/resource/User/op.portal@example.com")
api("criar_operador", email="op.portal@example.com", full_name="Op Portal")
s.put(URL + "/api/resource/User/op.portal@example.com", json={"new_password": "Senha#Op2026x"})
op.post(URL + "/api/method/login", json={"usr": "op.portal@example.com", "pwd": "Senha#Op2026x"})
resp = op.post(f"{URL}/api/method/frappe.precast_api.salvar_config_portal", json={"codigo_obra": OBRA, "ativo": False}).json()
ok("operador de fábrica não altera o portal", not resp.get("message", {}).get("success"))
s.delete(URL + "/api/resource/User/op.portal@example.com")

print("[Tela]")
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message))
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2000)
    pg.evaluate("switchModule('cliente')"); pg.wait_for_selector("[data-portal-secao]", timeout=15000)
    pg.select_option("#clienteObra", OBRA); pg.wait_for_timeout(2500)
    titulo_cliente = pg.inner_text("#screenTitle")
    pg.evaluate("switchModule('qualidade')"); pg.wait_for_timeout(1000)
    ok("aba Cliente e aba Qualidade são telas diferentes", titulo_cliente != pg.inner_text("#screenTitle"), f"{titulo_cliente!r} x {pg.inner_text('#screenTitle')!r}")
    pg.evaluate("switchModule('cliente')"); pg.wait_for_selector("[data-portal-secao]", timeout=15000)
    pg.select_option("#clienteObra", OBRA); pg.wait_for_timeout(2500)
    ok("seções aparecem como caixas de seleção", pg.locator("[data-portal-secao]").count() == 10)
    frame = pg.frame_locator("#clientePreview")
    frame.locator("h2:text-is('Peças')").wait_for(timeout=20000)
    ok("prévia mostra a lista de peças enquanto ligada", frame.locator("h2:text-is('Peças')").count() >= 1)
    pg.uncheck("[data-portal-secao='pecas']"); pg.uncheck("[data-portal-secao='entregas']")
    pg.click("text=Salvar o que o cliente vê"); pg.wait_for_selector("#portalMsg:has-text('Salvo')", timeout=10000); pg.wait_for_timeout(3500)
    ok("prévia some com as peças e entregas desligadas", frame.locator("h2:text-is('Peças')").count() == 0 and frame.locator("h2:text-is('Entregas')").count() == 0)
    ok("prévia mantém o resto", frame.locator("h2:text-is('Situação das peças')").count() == 1)
    pg.uncheck("#portalAtivo"); pg.click("text=Salvar o que o cliente vê"); pg.wait_for_timeout(4000)
    ok("acesso desligado mostra aviso na prévia", frame.locator("text=não está disponível").count() == 1)
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

api("delete_obra", codigo_obra=OBRA)
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
