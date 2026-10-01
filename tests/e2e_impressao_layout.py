"""Etiqueta e prancha na impressora comum, ZPL para a Zebra, QR ligado à prancha e telas que ocupam a janela inteira."""
import json, os, sys
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA = "IMP-TESTE"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


s = requests.Session()
s.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    return s.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo).json().get("message", {})


api("delete_obra", codigo_obra=OBRA)
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Impressão", "cliente": "Cliente", "fck": "35 MPa"}),
    pieces_data=json.dumps([{"cod": "IM1", "tag": "IM 1", "produto": "Pilar", "secao": "30X40", "comp": 8.6, "vol": 0.942, "peso": 2435.4,
                              "print_url": "/files/precast_logo.png", "prancha_url": "/files/precast_logo.png", "fonte": "prancha", "dimensoes_confirmadas": True}] +
                             [{"cod": f"IM{i}", "tag": f"IM {i}", "produto": "Viga", "secao": "25X60", "comp": 5.0, "vol": 0.75, "peso": 1900} for i in range(2, 4)]))

print("[QR ligado à prancha]")
scan = api("get_piece_for_scan", codigo="PECA:IM1")
ok("ler o QR devolve a prancha da peça", scan.get("success") and scan["peca"]["print_url"] == "/files/precast_logo.png", str({k: scan["peca"].get(k) for k in ("print_url", "prancha_url")}))
qr = api("get_or_generate_qrcode", codigo_peca="IM1")
ok("QR traz o código da peça e a obra dela", qr.get("success") and qr["payload"].endswith("IM1") and OBRA in qr["obra"], f'{qr.get("payload")} | {qr.get("obra")}')
nao = api("get_or_generate_qrcode", codigo_peca="NAO-GRAVADA")
ok("peça não gravada: erro claro", not nao.get("success") and "não encontrada" in nao.get("error", ""))

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); ctx = b.new_context(viewport={"width": 1400, "height": 800}); pg = ctx.new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message)); dialogos = []; pg.on("dialog", lambda d: (dialogos.append(d.message), d.accept()))
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2000)

    print("[Tela do bipar mostra a prancha]")
    pb = ctx.new_page(); pb.goto(URL + "/bipar", wait_until="domcontentloaded"); pb.wait_for_timeout(2500)
    pb.evaluate("buscarPeca('PECA:IM1')"); pb.wait_for_selector("#pieceArea img[alt^='Prancha']", timeout=15000)
    ok("peça lida no bipar mostra a prancha dela", "PRANCHA DESTA PEÇA" in pb.inner_text("#pieceArea").upper())
    pb.close()

    print("[Impressão]")
    pg.evaluate("switchModule('fabricacao')"); pg.wait_for_timeout(2500)
    pg.evaluate("window.__prints = []; window.imprimirHtml = async (titulo, html, css) => { window.__prints.push({ titulo, html }); }; 0")
    pg.evaluate("openZplForPiece('IM1', 'IM 1', '30X40', 8.6, 0.942, 2435.4)"); pg.wait_for_selector("#zplQrImg[src*='/files/qrcodes/']", timeout=15000)
    pg.click("#modalZpl >> text=Imprimir etiqueta"); pg.wait_for_timeout(500)
    imp = pg.evaluate("window.__prints") or []
    ok("imprimir etiqueta manda uma etiqueta com o QR da peça", len(imp) == 1 and "RASTREABILIDADE INDUSTRIAL" in imp[0]["html"] and "/files/qrcodes/IM1.png" in imp[0]["html"] and "IM 1" in imp[0]["html"], str([(i.get("titulo"), (i.get("html") or "")[:60]) for i in imp]) + f" avisos: {dialogos}")
    pg.evaluate("window.__prints = []")
    pg.click("#modalZpl >> text=Etiqueta + prancha"); pg.wait_for_timeout(800)
    imp = pg.evaluate("window.__prints")
    ok("etiqueta + prancha imprime as duas, nessa ordem", len(imp) == 2 and "RASTREABILIDADE" in imp[0]["html"] and "precast_logo.png" in imp[1]["html"] and imp[1]["titulo"].startswith("Prancha"), str([i["titulo"] for i in imp]))
    with pg.expect_download() as d:
        pg.click("#modalZpl >> text=Baixar ZPL")
    zpl = open(d.value.path(), encoding="utf-8").read()
    ok("ZPL baixado é um comando de etiqueta de verdade", zpl.startswith("^XA") and zpl.rstrip().endswith("^XZ") and "PECA:IM1" in zpl and "^BQN" in zpl, zpl[:40].replace("\n", " "))
    ok("não existe mais o aviso falso de 'comando enviado'", "Comando ZPL enviado" not in pg.content())
    pg.evaluate("closeZplModal()")

    print("[Peça não gravada]")
    pg.evaluate("openZplForPiece('FANTASMA', 'FANTASMA', '30X40', 1, 1, 1)"); pg.wait_for_timeout(2500)
    ok("etiqueta de peça não gravada explica o que fazer", "ainda não está gravada" in pg.inner_text("#zplCodeStr"), pg.inner_text("#zplCodeStr")[:80])
    pg.evaluate("closeZplModal()")

    print("[Telas ocupam a janela]")
    pg.evaluate("switchModule('qualidade')"); pg.wait_for_timeout(800)
    pg.evaluate("switchModule('cotacoes')"); pg.wait_for_timeout(800)
    ok("o painel de Qualidade não fica por baixo de outras abas", pg.evaluate("document.getElementById('viewQualidade').classList.contains('hidden')"))
    pg.evaluate("switchModule('fabricacao')"); pg.wait_for_timeout(2500)
    caixa = pg.evaluate("(() => { const t = [...document.querySelectorAll('.table-container')].find(e => e.offsetParent); const m = document.querySelector('.main-viewport').getBoundingClientRect(); const r = t.getBoundingClientRect(); return [Math.round(r.bottom), Math.round(m.bottom)]; })()")
    ok("a tabela da Fabricação vai até o fim da janela", abs(caixa[0] - caixa[1]) <= 4, str(caixa))
    pg.evaluate("switchModule('projeto')"); pg.wait_for_timeout(500)
    pg.evaluate("switchSubScreen('obras')"); pg.wait_for_timeout(1500)
    caixa = pg.evaluate("(() => { const t = [...document.querySelectorAll('.table-container')].find(e => e.offsetParent); const m = document.querySelector('.main-viewport').getBoundingClientRect(); const r = t.getBoundingClientRect(); return [Math.round(r.bottom), Math.round(m.bottom)]; })()")
    ok("a tabela de Obras vai até o fim da janela", abs(caixa[0] - caixa[1]) <= 4, str(caixa))
    pg.click("#zoomMenos"); pg.wait_for_timeout(500)
    pg.evaluate("document.getElementById('modalZpl').classList.add('active')")
    cobertura = pg.evaluate("(() => { const r = document.getElementById('modalZpl').getBoundingClientRect(); return [Math.round(r.right), Math.round(r.bottom), innerWidth, innerHeight]; })()")
    ok("com a letra em 90% a janela de diálogo cobre a tela toda", cobertura[0] >= cobertura[2] - 2 and cobertura[1] >= cobertura[3] - 2, str(cobertura))
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

api("delete_obra", codigo_obra=OBRA)
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
