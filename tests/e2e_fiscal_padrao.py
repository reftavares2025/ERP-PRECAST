"""Fiscal (preparação), padrão de desenho do AutoCAD e RH visível."""
import json, os, sys, time
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("PRECAST_URL", "http://localhost:8088")
CAD = "http://localhost:2026"
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
DWG = r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg\109 - 26 - RODRIGO FEIJÃO - ITAPETININGA - SP - R1.dwg"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


s = requests.Session()
s.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    return s.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo).json().get("message", {})


print("[API fiscal]")
original = api("get_fiscal")
ok("get_fiscal responde com checklist", original.get("success") and len(original["prontidao"]["itens"]) == 11)
r = api("salvar_fiscal", dados=json.dumps({"cnpj": "11.222.333/0001-81", "razao_social": "Teste Ltda", "uf": "SP", "regime": "Simples Nacional"}))
itens = {i["chave"]: i["ok"] for i in r["prontidao"]["itens"]}
ok("CNPJ válido conta no checklist", itens["cnpj"] and itens["razao"] and itens["regime"])
r = api("salvar_fiscal", dados=json.dumps({"cnpj": "11.222.333/0001-80"}))
ok("CNPJ com dígito errado não conta", not {i["chave"]: i["ok"] for i in r["prontidao"]["itens"]}["cnpj"])
r = api("salvar_fiscal", dados=json.dumps({"uf": "XX"}))
ok("UF inválida é recusada", not r.get("success"), str(r.get("error"))[:60])
r = api("salvar_fiscal", dados=json.dumps({"produtos": {"Pilar": {"ncm": "6810.91.00", "cfop_dentro_uf": "5101"}}}))
ok("produto sem NCM/CFOP completos mantém o item pendente", not {i["chave"]: i["ok"] for i in r["prontidao"]["itens"]}["produtos"])
ok("sugestões não contam como preenchidas", api("get_fiscal")["dados"]["produtos"].get("Viga") is None)

print("[Permissão]")
s.delete(URL + "/api/resource/User/op.fiscal@example.com")
api("criar_operador", email="op.fiscal@example.com", full_name="Op Fiscal")
op = requests.Session()
senha_op = "Senha#Op2026x"
s.post(URL + "/api/method/frappe.core.doctype.user.user.update_password", json={"new_password": senha_op, "key": ""})  # ignorado: define abaixo
s.put(URL + "/api/resource/User/op.fiscal@example.com", json={"new_password": senha_op})
op.post(URL + "/api/method/login", json={"usr": "op.fiscal@example.com", "pwd": senha_op})
resp = op.post(f"{URL}/api/method/frappe.precast_api.get_fiscal", json={}).json()
ok("operador de fábrica não vê o fiscal", "message" not in resp or not resp["message"].get("success"))
s.delete(URL + "/api/resource/User/op.fiscal@example.com")

print("[Padrão CAD no motor]")
ok("padrão do motor lista os elementos do modelo", len(requests.get(CAD + "/api/padrao-cad").json()["elementos"]) == 12)
scr = requests.get(CAD + "/api/padrao-cad.scr").text
ok("script cria as camadas do padrão", "pilar" in scr and "Viga_Cobertura" in scr and scr.startswith("-LAYER"))
with open(DWG, "rb") as f:
    job = requests.post(CAD + "/api/parse-cad", files={"file": (os.path.basename(DWG), f)}).json()["job_id"]
t = time.time()
while time.time() - t < 400:
    st = requests.get(f"{CAD}/api/parse-status/{job}").json()
    if st.get("done"):
        break
    time.sleep(3)
p = (st.get("result") or {}).get("padrao_cad") or {}
ok("leitura devolve o relatório do padrão", bool(p), str(st.get("error")))
ok("relatório lista camadas do padrão com conteúdo", any(i["ok"] for i in p.get("itens", [])) and any(i["camada"] == "pilar" and i["ok"] for i in p["itens"]))

print("[Telas]")
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1400, "height": 800}).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message))
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2000)
    pg.evaluate("switchModule('fiscal')"); pg.wait_for_selector("#fiscalEmpresa [data-fiscal='cnpj']", timeout=15000)
    ok("aba Fiscal mostra o cadastro", pg.locator("#fiscalChecklist .fiscal-item").count() == 11)
    pg.fill("[data-fiscal='email_contador']", "contador@exemplo.com.br"); pg.click("text=Salvar cadastro fiscal"); pg.wait_for_selector("#fiscalMsg:has-text('salvo')", timeout=10000)
    ok("salvar atualiza o checklist", "contador" in pg.inner_text("#fiscalChecklist") and pg.locator("#fiscalChecklist .fiscal-item:has-text('✅')").count() >= 3)
    ok("botão Emitir NF-e desativado", pg.locator("button:has-text('Emitir NF-e')").is_disabled())
    pg.evaluate("switchModule('projeto')"); pg.wait_for_timeout(800)
    pg.click("text=Ver o padrão"); pg.wait_for_selector("#padraoCadLista table", timeout=10000)
    ok("tela mostra o padrão de camadas", "Viga_Cobertura" in pg.inner_text("#padraoCadLista"))
    ok("link do script aponta para o motor", pg.get_attribute("#padraoCadScr", "href").endswith("/api/padrao-cad.scr"))
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

print("[RH]")
icones = s.get(URL + "/api/resource/Desktop Icon", params={"fields": '["name"]', "filters": '[["parent_icon","=","Frappe HR"]]', "limit_page_length": 50}).json()["data"]
restritos = [i["name"] for i in icones if s.get(URL + "/api/resource/Desktop Icon/" + i["name"]).json()["data"].get("roles")]
ok("nenhum ícone do RH restrito ao fornecedor", not restritos, str(restritos))

# devolve o cadastro fiscal ao estado inicial
api("salvar_fiscal", dados=json.dumps({k: ("" if isinstance(v, str) else v) for k, v in original["dados"].items() if k != "produtos"} | {"produtos": original["dados"].get("produtos", {})}))
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
