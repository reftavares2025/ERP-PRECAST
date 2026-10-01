"""Dashboard Executivo, tamanho da letra (-10% a +25%) e travas de zoom/rolagem lateral."""
import json, os, sys
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA = "DASH-TESTE"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


s = requests.Session()
s.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    return s.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo).json().get("message", {})


base = api("get_dashboard")["kpis"]
api("delete_obra", codigo_obra=OBRA)
pecas = [{"cod": f"DT{i}", "tag": f"DT {i}", "produto": "Pilar", "secao": "30x30", "comp": 3.0, "vol": 0.5, "peso": 1000} for i in range(1, 31)]
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Dash", "cliente": "Cliente Dash", "fck": "30 MPa"}), pieces_data=json.dumps(pecas))
codigos = [p["codigo_peca"] for p in api("get_pieces", obra=OBRA)["pieces"]]
for cod, fase_alvo in zip(codigos, (4, 6, 6, 1)):
    for _ in range(fase_alvo - 1):
        api("advance_piece_phase", codigo_peca=cod, forcar=True)

print("[Números]")
d = api("get_dashboard")
k = d["kpis"]
ok("obra nova conta em andamento", k["obras_em_andamento"] == base["obras_em_andamento"] + 1, f'{base["obras_em_andamento"]} -> {k["obras_em_andamento"]}')
ok("peças produzidas (fase 6+) somam 2", k["pecas_produzidas"] == base["pecas_produzidas"] + 2)
ok("volume soma 15 m³", abs(k["volume_concreto_m3"] - base["volume_concreto_m3"] - 15.0) < 0.05)
ok("avanço por etapa tem 8 etapas decrescentes", len(d["etapas"]) == 8 and all(d["etapas"][i]["percentual"] >= d["etapas"][i + 1]["percentual"] for i in range(7)))
linha = next((o for o in d["obras"] if o["codigo"] == OBRA), None)
ok("tabela traz a obra com 7% produzido", linha is not None and linha["progresso"] == 7, str(linha))
ok("donut soma as peças", sum(x["pecas"] for x in d["por_status"]) == k["total_pecas"])

print("[Tela]")
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1500, "height": 900}).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message))
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_selector("#dashKpis .dash-kpi", timeout=15000)
    ok("início é o Dashboard Executivo", "Dashboard Executivo" in pg.inner_text("#viewHome"))
    ok("cinco cartões de números", pg.locator("#dashKpis .dash-kpi").count() == 5)
    ok("oito etapas", pg.locator("#dashEtapas .dash-etapa").count() == 8)
    pg.wait_for_selector("#dashObras table", timeout=10000)
    ok("tabela de obras mostra a obra do teste", OBRA in pg.inner_text("#dashObras"))
    ok("gráfico de peças por status desenhado", pg.locator("#dashStatus svg circle").count() == 8)
    ok("a janela inteira é do painel", pg.evaluate("document.querySelector('.main-viewport').getBoundingClientRect().bottom") >= 890)
    ok("uma fonte só: Inter", pg.evaluate("getComputedStyle(document.body).fontFamily").startswith("Inter") and pg.evaluate("document.fonts.check('16px Inter')"))

    print("[Tamanho da letra]")
    ok("começa em 100%", pg.inner_text("#zoomRotulo") == "100%")
    pg.click("#zoomMais"); pg.click("#zoomMais")
    ok("sobe até 125%", pg.inner_text("#zoomRotulo") == "125%" and pg.evaluate("document.body.style.zoom") == "1.25")
    ok("não passa de +25%", pg.locator("#zoomMais").is_disabled())
    ok("altura acompanha o zoom (sem barra na janela)", pg.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"))
    pg.click("#zoomMenos"); pg.click("#zoomMenos"); pg.click("#zoomMenos")
    ok("desce até 90%", pg.inner_text("#zoomRotulo") == "90%" and pg.locator("#zoomMenos").is_disabled())
    pg.reload(wait_until="networkidle"); pg.wait_for_selector("#zoomRotulo", timeout=10000)
    ok("lembra a escolha ao recarregar", pg.inner_text("#zoomRotulo") == "90%")
    pg.click("#zoomMais")

    print("[Travas]")
    resultado = pg.evaluate("""() => new Promise(res => {
      const saida = {};
      const ctrlWheel = new WheelEvent('wheel', { ctrlKey: true, deltaY: -100, cancelable: true });
      window.dispatchEvent(ctrlWheel); saida.ctrlWheelBloqueado = ctrlWheel.defaultPrevented;
      const k = new KeyboardEvent('keydown', { key: '+', ctrlKey: true, cancelable: true, bubbles: true });
      window.dispatchEvent(k); saida.ctrlMaisBloqueado = k.defaultPrevented;
      const k0 = new KeyboardEvent('keydown', { key: '0', ctrlKey: true, cancelable: true, bubbles: true });
      window.dispatchEvent(k0); saida.ctrlZeroBloqueado = k0.defaultPrevented;
      const lateral = new WheelEvent('wheel', { deltaX: 120, deltaY: 0, cancelable: true, bubbles: true });
      document.querySelector('#viewHome').dispatchEvent(lateral); saida.lateralBloqueado = lateral.defaultPrevented;
      const vertical = new WheelEvent('wheel', { deltaY: 120, cancelable: true, bubbles: true });
      document.querySelector('#viewHome').dispatchEvent(vertical); saida.verticalLivre = !vertical.defaultPrevented;
      res(saida);
    })""")
    ok("Ctrl + roda do mouse bloqueado", resultado["ctrlWheelBloqueado"])
    ok("Ctrl + e Ctrl 0 bloqueados", resultado["ctrlMaisBloqueado"] and resultado["ctrlZeroBloqueado"])
    ok("rolagem lateral bloqueada", resultado["lateralBloqueado"])
    ok("rolagem para cima e para baixo livre", resultado["verticalLivre"])
    ok("viewport sem escala do usuário", pg.evaluate("[...document.querySelectorAll('meta[name=viewport]')].every(m => m.content.includes('user-scalable=no'))"))

    print("[Rolagem vertical]")
    pg.evaluate("switchModule('fabricacao')"); pg.wait_for_timeout(2500)
    rolavel = pg.evaluate("[...document.querySelectorAll('.main-viewport *')].some(e => e.scrollHeight > e.clientHeight + 2 && ['auto', 'scroll'].includes(getComputedStyle(e).overflowY))")
    ok("tela longa tem área com rolagem vertical", rolavel)
    pg.mouse.move(700, 450); pg.mouse.wheel(0, 600); pg.wait_for_timeout(500)
    ok("roda do mouse desce a tela", pg.evaluate("[...document.querySelectorAll('.main-viewport *')].some(e => e.scrollTop > 0)"))
    pg.mouse.wheel(0, -2000); pg.wait_for_timeout(500)
    ok("roda do mouse sobe a tela", pg.evaluate("[...document.querySelectorAll('.main-viewport *')].every(e => e.scrollTop === 0)"))
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

api("delete_obra", codigo_obra=OBRA)
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
