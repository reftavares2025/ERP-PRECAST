"""O mesmo código de peça (PM.01) em obras diferentes: cada peça fica na obra do arquivo importado, com os próprios
dados, QR Code e prancha. Importar de novo acrescenta ou substitui, sem tocar nas outras obras."""
import json, os, sys
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
A, B = "OBRA-A-TESTE", "OBRA-B-TESTE"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


s = requests.Session()
s.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    r = s.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo)
    try:
        return r.json().get("message", {})
    except ValueError:
        return {"success": False, "error": r.text[:100]}


def peca(cod, secao, comp, **extra):
    return {"cod": cod, "tag": cod, "produto": "Pilar", "secao": secao, "comp": comp, "vol": round(0.3 * 0.4 * comp, 3), "peso": 1000 * comp, "dimensoes_confirmadas": True, **extra}


def gravar(obra, pecas, modo="acrescentar"):
    return api("integrate_parsed_project", obra_data=json.dumps({"cod": obra, "nome": f"Nome {obra}", "cliente": "Cliente", "fck": "35 MPa"}), pieces_data=json.dumps(pecas), modo=modo)


for o in (A, B):
    api("delete_obra", codigo_obra=o)

print("[Mesmo código em duas obras]")
gravar(A, [peca("PM.01", "30X40", 8.6, fonte="prancha", print_url="/files/precast_logo.png", prancha_url="/files/precast_logo.png"), peca("PM.02", "30X40", 9.6), peca("PM.03", "30X40", 9.6)])
r = gravar(B, [peca("PM.01", "40X40", 12.0, fonte="prancha", print_url="/files/favicon.png", prancha_url="/files/favicon.png"), peca("PM.02", "40X40", 12.0)])
ok("a segunda obra grava as peças dela sem apagar nem trocar as da primeira", r.get("success") and r.get("created") == 2 and not r.get("pecas_removidas"), str(r)[:120])
pa, pb = api("get_pieces", obra=A)["pieces"], api("get_pieces", obra=B)["pieces"]
ok("cada obra lista só as suas peças", len(pa) == 3 and len(pb) == 2 and all(p["obra"] == A for p in pa) and all(p["obra"] == B for p in pb))
ok("a etiqueta/tag continua PM.01 nas duas", any(p["tag"] == "PM.01" for p in pa) and any(p["tag"] == "PM.01" for p in pb))
a01 = next(p for p in pa if p["tag"] == "PM.01"); b01 = next(p for p in pb if p["tag"] == "PM.01")
ok("PM.01 de cada obra tem os próprios dados", a01["secao"] == "30X40" and a01["comprimento_m"] == 8.6 and b01["secao"] == "40X40" and b01["comprimento_m"] == 12.0)
ok("e a própria prancha", a01["print_url"] == "/files/precast_logo.png" and b01["print_url"] == "/files/favicon.png")
ok("os códigos internos são diferentes (um por obra)", a01["codigo_peca"] != b01["codigo_peca"], f'{a01["codigo_peca"]} | {b01["codigo_peca"]}')

print("[QR e bipar]")
qa, qb = api("get_or_generate_qrcode", codigo_peca=a01["codigo_peca"]), api("get_or_generate_qrcode", codigo_peca=b01["codigo_peca"])
ok("QR de cada peça aponta para a obra dela", A in qa["obra"] and B in qb["obra"] and qa["payload"] != qb["payload"], f'{qa["obra"]} | {qb["obra"]}')
ok("ler o QR abre a peça da obra certa", api("get_piece_for_scan", codigo=qb["payload"])["peca"]["obra"] == B and api("get_piece_for_scan", codigo=qa["payload"])["peca"]["obra"] == A)
dig = api("get_piece_for_scan", codigo="PM.01")
ok("digitar PM.01 (existe nas duas) pede a obra", dig.get("ambiguo") and {o["obra"] for o in dig["opcoes"]} == {A, B}, str(dig)[:120])
ok("PM.03 (só existe na obra A) abre direto", api("get_piece_for_scan", codigo="PM.03")["peca"]["obra"] == A)

print("[Importar de novo]")
for _ in range(3):
    api("advance_piece_phase", codigo_peca=a01["codigo_peca"], forcar=True)  # PM.01 da obra A já tem produção
r = gravar(A, [peca("PM.02", "30X40", 9.6)], "acrescentar")
ok("acrescentar mantém tudo o que a obra já tinha", not r.get("pecas_removidas") and len(api("get_pieces", obra=A)["pieces"]) == 3)
r = gravar(A, [peca("PM.02", "30X40", 9.6)], "substituir")
nomes = {p["tag"] for p in api("get_pieces", obra=A)["pieces"]}
ok("substituir tira só a peça sem produção que saiu do desenho (PM.03)", r.get("pecas_removidas") == [next(p["codigo_peca"] for p in pa if p["tag"] == "PM.03")] and nomes == {"PM.01", "PM.02"}, f"{r.get('pecas_removidas')} | {sorted(nomes)}")
ok("a peça com produção ficou, marcada", r.get("pecas_fora_do_desenho") == [a01["codigo_peca"]])
ok("a outra obra não foi tocada", len(api("get_pieces", obra=B)["pieces"]) == 2)

print("[Telas]")
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1400, "height": 850}).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message)); pg.on("dialog", lambda d: d.accept())
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2000)
    # uma leitura ao vivo de OUTRO arquivo, com PM.01 de medidas absurdas, está aberta na tela
    pg.evaluate("currentParsedData = { obra: { cod: 'OBRA-LIVE' }, pieces: [{ cod: 'PM.01', tag: 'PM.01', secao: '99X99', comp: 99, vol: 99, peso: 99999, produto: 'Pilar' }], resolved_dxf_path: null }; 0")
    pg.evaluate("switchModule('fabricacao')"); pg.wait_for_timeout(2500)
    pg.select_option("#fabObraFilter", B); pg.wait_for_timeout(600)
    pg.locator("#fabricacaoTableBody tr", has_text="PM.01").locator("button.btn-prancha", has_text="Prancha").click(); pg.wait_for_timeout(1500)
    sub = pg.inner_text("#pranchaModalSub")
    ok("prancha de uma peça gravada mostra os dados da obra dela, não os da leitura ao vivo", "40X40" in sub and "99" not in sub, sub)
    ok("com a imagem da própria obra", pg.get_attribute("#pranchaModalImg", "src").startswith("/files/favicon.png"), pg.get_attribute("#pranchaModalImg", "src"))
    pg.evaluate("closePranchaModal()")
    pg.locator("#fabricacaoTableBody tr", has_text="PM.01").locator("button.btn-zpl").click(); pg.wait_for_selector("#zplQrImg[src*='/files/qrcodes/']", timeout=15000)
    ok("etiqueta da peça gravada mostra a obra dela", B in pg.inner_text("#zplObraNome") and "40X40" in pg.inner_text("#zplSecao"), pg.inner_text("#zplObraNome"))
    pg.evaluate("closeZplModal()")
    # etiqueta de uma peça da leitura ao vivo que NÃO foi gravada (OBRA-LIVE): não pode herdar o QR de outra obra
    pg.evaluate("openZplForPiece('PM.01', 'PM.01', '99X99', 99, 99, 99999, true)"); pg.wait_for_timeout(2500)
    ok("etiqueta de peça ao vivo não gravada não usa o QR de outra obra", "ainda não está gravada" in pg.inner_text("#zplCodeStr") and B not in pg.inner_text("#zplObraNome"), pg.inner_text("#zplCodeStr")[:60])
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

for o in (A, B):
    api("delete_obra", codigo_obra=o)
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
