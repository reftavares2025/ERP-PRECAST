"""Regressão: quem abriu o desk na mesma sessão tem um token CSRF gravado; as páginas do sistema
precisam enviá-lo, senão toda gravação volta "Solicitação inválida". Também confere que o painel
não mostra a barra e o rodapé do site nem dados de exemplo."""
import os, sys
from playwright.sync_api import sync_playwright

URL = os.environ.get("PRECAST_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
falhas = []
OBRA = "CSRF-TESTE"

def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond: falhas.append(nome)

import json, requests
api = requests.Session(); api.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})
api.post(URL + "/api/method/frappe.precast_api.integrate_parsed_project", json={
    "obra_data": json.dumps({"cod": OBRA, "nome": "Obra de teste", "cliente": "Cliente Teste", "fck": "30 MPa"}),
    "pieces_data": json.dumps([{"cod": "CS1", "tag": "CS 1", "produto": "Pilar", "secao": "30x30", "comp": 3.0, "vol": 0.27, "peso": 675}])})

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1400, "height": 800}).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message))
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/desk", wait_until="domcontentloaded"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2000)
    ok("barra e rodapé do site escondidos", pg.evaluate("[...document.querySelectorAll('.navbar,.web-footer')].every(e=>e.offsetHeight===0)"))
    pg.evaluate("switchModule('fabricacao')"); pg.wait_for_timeout(2500)
    pg.locator("button.btn-zpl:visible").first.click(); pg.wait_for_selector("#zplQrImg[src*='/files/qrcodes/']", timeout=15000)
    ok("QR Code gerado depois de abrir o desk", "Erro" not in pg.inner_text("#zplCodeStr"), pg.inner_text("#zplCodeStr")[:40])
    ok("etiqueta mostra a obra da peça", OBRA in pg.inner_text("#zplObraNome"), pg.inner_text("#zplObraNome"))
    pg.evaluate("closeZplModal()"); pg.click("#suporteBtn"); pg.fill("#suporteEntrada", "Como cadastro um caminhão?"); pg.keyboard.press("Enter")
    pg.wait_for_function("!document.querySelector('#suporteMsgs').innerText.includes('Digitando') && document.querySelectorAll('#suporteMsgs .sup-m').length>=3", timeout=40000)
    ok("chat de suporte responde", "inválida" not in pg.locator("#suporteMsgs .sup-m").last.inner_text())
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}"); sys.exit(1 if falhas else 0)
