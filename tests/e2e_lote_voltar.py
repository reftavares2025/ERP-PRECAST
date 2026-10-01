"""Etiquetas em lote (impressora comum, etiqueta + pranchas, ZPL) e voltar a fase da peça."""
import json, os, sys
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA = "LOTE-TESTE"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


s = requests.Session()
s.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, sessao=None, **corpo):
    r = (sessao or s).post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo)
    try:
        return r.json().get("message", {"success": False, "error": r.text[:120]})
    except ValueError:
        return {"success": False, "error": r.text[:120]}


api("delete_obra", codigo_obra=OBRA)
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Lote", "cliente": "Cliente", "fck": "35 MPa"}),
    pieces_data=json.dumps([{"cod": "LT1", "tag": "LT 1", "produto": "Pilar", "secao": "30X40", "comp": 8.6, "vol": 0.942, "peso": 2435.4, "print_url": "/files/precast_logo.png", "prancha_url": "/files/precast_logo.png", "fonte": "prancha", "dimensoes_confirmadas": True},
                            {"cod": "LT2", "tag": "LT 2", "produto": "Pilar", "secao": "30X40", "comp": 8.6, "vol": 0.942, "peso": 2435.4},
                            {"cod": "LT3", "tag": "LT 3", "produto": "Viga", "secao": "25X60", "comp": 5.0, "vol": 0.75, "peso": 1900}]))

print("[Voltar a fase — servidor]")
for _ in range(3):
    api("advance_piece_phase", codigo_peca="LT2", forcar=True)  # vai para a fase 4
ok("peça foi para a fase 4", api("get_piece_for_scan", codigo="LT2")["peca"]["fase_numero"] == 4)
r = api("voltar_fase_peca", codigo_peca="LT2", fase_destino=2, motivo="bipado por engano")
ok("volta para a fase escolhida (2)", r.get("success") and r["fase_numero"] == 2 and "Armação" in r["status_producao"], str(r))
ok("não aceita ir para frente ou ficar na mesma", not api("voltar_fase_peca", codigo_peca="LT2", fase_destino=2).get("success") and not api("voltar_fase_peca", codigo_peca="LT2", fase_destino=5).get("success"))
ok("fica no histórico com a fase anterior e a nova", any(h["fase_anterior"] == 4 and h["fase_nova"] == 2 for h in s.get(URL + "/api/resource/Fase Historico", params={"filters": json.dumps([["codigo_peca", "=", "LT2"]]), "fields": '["fase_anterior","fase_nova"]'}).json()["data"]))
op = requests.Session()
api("delete_obra", codigo_obra="__nada__")
s.delete(URL + "/api/resource/User/op.voltar@example.com")
api("criar_operador", email="op.voltar@example.com", full_name="Op Voltar")
s.put(URL + "/api/resource/User/op.voltar@example.com", json={"new_password": "Senha#Op2026x"})
op.post(URL + "/api/method/login", json={"usr": "op.voltar@example.com", "pwd": "Senha#Op2026x"})
ok("operador de fábrica não volta fase", not api("voltar_fase_peca", sessao=op, codigo_peca="LT2", fase_destino=1).get("success"))
s.delete(URL + "/api/resource/User/op.voltar@example.com")

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); ctx = b.new_context(viewport={"width": 1400, "height": 850}); pg = ctx.new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message)); pg.on("dialog", lambda d: d.accept())
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2000)

    print("[Voltar a fase — tela]")
    pg.evaluate("switchModule('fabricacao')"); pg.wait_for_timeout(2500)
    pg.select_option("#fabObraFilter", OBRA); pg.wait_for_timeout(800)
    linha = pg.locator("#fabricacaoTableBody tr", has_text="LT 2")
    ok("linha da peça mostra a fase atual", "Armação" in linha.inner_text())
    ok("peça na fase 1 não tem como voltar", pg.locator("#fabricacaoTableBody tr", has_text="LT 1").locator("text=Voltar").is_disabled())
    api("advance_piece_phase", codigo_peca="LT2")  # volta a ser fase 3 para ter mais de uma opção
    pg.evaluate("fetchPiecesFromERP().then(renderFabricacaoTable)"); pg.wait_for_timeout(1200)
    pg.click("button[onclick=\"abrirVoltarFase('LT2')\"]"); pg.wait_for_selector("#voltarDestino option", state="attached", timeout=5000)
    opcoes = pg.eval_on_selector_all("#voltarDestino option", "els => els.map(e => e.value)")
    ok("o modal oferece só fases anteriores (2 e 1)", opcoes == ["2", "1"], str(opcoes))
    pg.select_option("#voltarDestino", "1"); pg.fill("#voltarMotivo", "teste"); pg.click("#modalVoltarFase >> button:has-text(\"Voltar a fase\")"); pg.wait_for_timeout(2000)
    ok("depois de confirmar a peça está na fase 1 na tela e no sistema", "Corte e Dobra" in pg.locator("#fabricacaoTableBody tr", has_text="LT 2").inner_text() and api("get_piece_for_scan", codigo="LT2")["peca"]["fase_numero"] == 1)

    print("[Etiquetas em lote]")
    pg.evaluate("window.__prints = []; window.imprimirHtml = async (titulo, html, css) => { window.__prints.push({ titulo, html }); }; 0")
    pg.click("text=Imprimir Etiquetas ZPL"); pg.wait_for_selector("#loteLista .lote-peca", timeout=8000)
    ok("o botão abre o lote com as peças da obra escolhida", pg.locator(".lote-peca").count() == 3 and "3 de 3" in pg.inner_text("#loteContagem"))
    pg.click("#modalEtiquetasLote >> text=Imprimir etiquetas"); pg.wait_for_function("window.__prints.length >= 1", timeout=20000)
    imp = pg.evaluate("window.__prints")
    ok("imprime uma folha com as 3 etiquetas, cada uma com o QR", len(imp) == 1 and imp[0]["html"].count('class="et"') == 3 and all(f"/files/qrcodes/LT{i}.png" in imp[0]["html"] for i in (1, 2, 3)), f'{len(imp)} impressão(ões)')
    pg.evaluate("window.__prints = []"); pg.uncheck(".lote-peca[value='LT3']"); pg.wait_for_timeout(200)
    ok("desmarcar tira a peça do lote", "2 de 3" in pg.inner_text("#loteContagem"))
    pg.click("#modalEtiquetasLote >> text=Etiquetas + pranchas"); pg.wait_for_function("window.__prints.length >= 2", timeout=20000)
    imp = pg.evaluate("window.__prints")
    ok("etiquetas + pranchas: primeiro as etiquetas (2), depois as pranchas", imp[0]["html"].count('class="et"') == 2 and "precast_logo.png" in imp[1]["html"] and imp[1]["html"].count("<img") == 1, str([i["titulo"] for i in imp]))
    with pg.expect_download() as d:
        pg.click("#modalEtiquetasLote >> text=ZPL de todas")
    zpl = open(d.value.path(), encoding="utf-8").read()
    ok("ZPL do lote tem uma etiqueta por peça marcada", zpl.count("^XA") == 2 and zpl.count("^XZ") == 2 and "PECA:LT1" in zpl and "PECA:LT2" in zpl and "PECA:LT3" not in zpl)
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

api("delete_obra", codigo_obra=OBRA)
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
