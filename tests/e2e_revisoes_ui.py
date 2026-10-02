"""Gravar uma revisão pela tela: resumo do que muda e do impacto na produção, histórico da obra e aviso no bipar."""
import json, os, sys
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA = "REVISAO-UI"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


adm = requests.Session()
adm.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    return adm.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo).json().get("message", {})


def peca(cod, secao, comp):
    return {"cod": cod, "tag": cod, "produto": "Pilar", "secao": secao, "comp": comp, "vol": round(0.3 * 0.4 * comp, 3), "peso": 1000 * comp,
            "peso_aco_kg": 80.0, "ferros": [], "fonte": "prancha", "dimensoes_confirmadas": True}


api("delete_obra", codigo_obra=OBRA)
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Revisão UI", "cliente": "C", "revisao": "R0a"}),
    pieces_data=json.dumps([peca("RV1", "30X40", 8.0), peca("RV2", "30X40", 8.0)]))
cods = {p["tag"]: p["codigo_peca"] for p in api("get_pieces", obra=OBRA)["pieces"]}
for _ in range(4):
    api("advance_piece_phase", codigo_peca=cods["RV2"], forcar=True)       # RV2 já concretada (fase 5)

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); ctx = b.new_context(viewport={"width": 1440, "height": 900}); pg = ctx.new_page()
    erros, alertas = [], []
    pg.on("pageerror", lambda e: erros.append(e.message)); pg.on("dialog", lambda d: (alertas.append(d.message), d.accept()))
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2500)

    print("[Gravar a revisão R0e]")
    pg.evaluate("""currentParsedData = { obra: { cod: 'REVISAO-UI', nome: 'Obra Revisão UI', cliente: 'C', revisao: 'R0e', arquivo: 'EST - X - R0e.dwg' },
        pieces: [ %s ], resolved_dxf_path: null }; integrateCurrentProjectToERPNext(); 0""" % ",".join(json.dumps(p) for p in
             [peca("RV1", "30X40", 8.0), peca("RV2", "30X45", 8.0), peca("RV3", "30X40", 6.0)]))
    pg.wait_for_selector("#modalModoGravacao.active", timeout=20000)
    pg.wait_for_timeout(800)
    texto = pg.inner_text("#modoGravacaoTexto")
    ok("o modal mostra a revisão e as contagens", "Revisão R0e" in texto and "1 nova" in texto and "1 alterada" in texto and "1 igual" in texto, texto[:200])
    ok("mostra a peça alterada com o antes e o depois", "RV2" in texto and "30X40 cm → 30X45 cm" in texto, texto)
    ok("marca a peça concretada como crítica e manda abrir não conformidade", "crítico" in texto and "não conformidade" in texto)
    pg.screenshot(path=os.path.join(os.environ.get("TEMP", "."), "revisao_modal.png"))
    pg.click("#modoAcrescentar"); pg.wait_for_timeout(5000)
    ok("depois de gravar, avisa das peças que já andaram", any("Revisão R0e gravada" in a and "1 crítica" in a for a in alertas), str(alertas)[-260:])

    print("[Histórico da obra]")
    pg.evaluate("abrirRevisoesObra('REVISAO-UI')"); pg.wait_for_timeout(2000)
    corpo = pg.inner_text("#revisoesCorpo")
    ok("duas revisões listadas, R0e primeiro", corpo.index("R0e") < corpo.index("R0a"), corpo[:160])
    pg.locator("#revisoesCorpo details").first.click(); pg.wait_for_timeout(300)
    ok("abrir a revisão mostra o que mudou na peça", "30X45" in pg.inner_text("#revisoesCorpo") and "RV2" in pg.inner_text("#revisoesCorpo"))
    pg.evaluate("document.getElementById('modalRevisoes').classList.remove('active')")

    print("[Bipar mostra o aviso]")
    pg.goto(URL + "/bipar", wait_until="domcontentloaded"); pg.wait_for_timeout(2500)
    pg.evaluate("buscarPeca('PECA:%s'); 0" % cods["RV2"]); pg.wait_for_timeout(2500)
    area = pg.inner_text("#pieceArea")
    ok("quem bipa a peça vê o aviso da engenharia", "AVISO DA ENGENHARIA" in area and "Revisão R0e" in area, area[:200])
    pg.evaluate("buscarPeca('PECA:%s'); 0" % cods["RV1"]); pg.wait_for_timeout(2000)
    ok("a peça sem impacto não mostra aviso", "AVISO DA ENGENHARIA" not in pg.inner_text("#pieceArea"))
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

api("delete_obra", codigo_obra=OBRA)
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
