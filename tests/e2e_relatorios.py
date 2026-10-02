"""Relatório de peças: escolher o cliente, ver as peças, marcar todas, algumas ou uma, ver, imprimir e baixar a planilha."""
import csv, json, os, sys
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRAS, CLIENTES = ["REL-A1", "REL-A2", "REL-B1"], ["Cliente Relatório Alfa", "Cliente Relatório Beta"]
LOTE = "LT-REL-01"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


adm = requests.Session()
adm.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    r = adm.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo)
    try:
        return r.json().get("message", {}) if r.status_code < 400 else {"success": False, "http": r.status_code}
    except ValueError:
        return {"success": False}


def limpar():
    for o in OBRAS:
        api("delete_obra", codigo_obra=o)
    for x in adm.get(f"{URL}/api/resource/Corpo Prova", params={"filters": json.dumps([["lote", "=", LOTE]])}).json().get("data", []):
        adm.delete(f"{URL}/api/resource/Corpo Prova/{x['name']}")
    adm.delete(f"{URL}/api/resource/Lote Concreto/{LOTE}")


def peca(cod, comp=9.0, peso=2500):
    return {"cod": cod, "tag": cod, "produto": "Pilar", "secao": "30X40", "comp": comp, "vol": 1.0, "peso": peso, "peso_aco_kg": 50.0, "fonte": "prancha", "dimensoes_confirmadas": True,
            "ferros": [{"posicao": "1", "bitola_mm": 10.0, "quantidade": 4, "comp_unit_m": 3.0, "comp_total_m": 12.0, "peso_kg": 7.4}]}


def obra(cod, cliente):
    return json.dumps({"cod": cod, "nome": f"Obra {cod}", "cliente": cliente})


limpar()
api("integrate_parsed_project", obra_data=obra("REL-A1", CLIENTES[0]), pieces_data=json.dumps([peca("RA1"), peca("RA2"), peca("RA3")]))
api("integrate_parsed_project", obra_data=obra("REL-A2", CLIENTES[0]), pieces_data=json.dumps([peca("RB1")]))
api("integrate_parsed_project", obra_data=obra("REL-B1", CLIENTES[1]), pieces_data=json.dumps([peca("RC1"), peca("RC2")]))
cod = {}
for o in OBRAS:
    for p in api("get_pieces", obra=o)["pieces"]:
        cod[p["tag"]] = p["codigo_peca"]
api("registrar_lote_concreto", codigo=LOTE, fck_especificado=35, usina="Usina Rel")
api("registrar_corpo_prova", lote=LOTE, idade_dias=28, fck_obtido=40)
api("vincular_lote_pecas", lote=LOTE, pecas=json.dumps([cod["RA1"]]))
api("submit_checklist", codigo_peca=cod["RA1"], etapa="2. Armação", aprovado=1, inspetor="Inspetor Rel")
for _ in range(2):
    api("advance_piece_phase", codigo_peca=cod["RA1"], forcar=True)

print("[Clientes e peças]")
cl = {c["cliente"]: c for c in api("relatorio_clientes")["clientes"]}
ok("os dois clientes aparecem com o total de peças e as obras", cl[CLIENTES[0]]["pecas"] == 4 and cl[CLIENTES[1]]["pecas"] == 2 and [o["codigo"] for o in cl[CLIENTES[0]]["obras"]] == ["REL-A1", "REL-A2"], str(cl.get(CLIENTES[0])))
l = api("relatorio_lista_pecas", cliente=CLIENTES[0])["pecas"]
ok("o cliente mostra as peças de todas as obras dele (e só dele), em ordem natural", [p["tag"] for p in l] == ["RA1", "RA2", "RA3", "RB1"], str([p["tag"] for p in l]))
ok("escolher uma obra mostra só as peças dela", [p["tag"] for p in api("relatorio_lista_pecas", cliente=CLIENTES[0], obra="REL-A2")["pecas"]] == ["RB1"])
ok("a obra de outro cliente não aparece no cliente errado", api("relatorio_lista_pecas", cliente=CLIENTES[1], obra="REL-A1")["pecas"] == [])

print("[Dados do relatório]")
r = api("relatorio_pecas", codigos=json.dumps([cod["RA1"]]))
p = r["pecas"][0]
ok("uma peça só: traz cliente, obra, fase e os assuntos padrão", r["success"] and r["total"] == 1 and p["cliente"] == CLIENTES[0] and p["obra"] == "REL-A1" and set(r["secoes"]) == {"dados", "producao", "rastreabilidade", "qualidade", "ferros", "entrega"})
ok("dados técnicos", p["dados"]["secao"] == "30X40" and p["dados"]["comprimento_m"] == 9.0 and p["dados"]["aco_kg"] == 50.0)
ok("produção: a fase atual e o histórico com quem avançou", p["fase"].startswith("3.") and len(p["producao"]["historico"]) == 2 and p["producao"]["historico"][0]["quem"])
ok("rastreabilidade: o lote com a ruptura de 28 dias", p["rastreabilidade"]["lote"]["codigo"] == LOTE and p["rastreabilidade"]["lote"]["corpos_de_prova"][0]["fck_obtido"] == 40)
ok("qualidade: a inspeção aprovada", p["qualidade"]["inspecoes"][0]["aprovado"] is True and p["qualidade"]["inspecoes"][0]["inspetor"] == "Inspetor Rel")
ok("lista de ferros", p["ferros"][0]["bitola_mm"] == 10.0)
ok("entrega: peça ainda sem romaneio", p["entrega"] is None)
r = api("relatorio_pecas", codigos=json.dumps([cod["RA1"], cod["RC1"]]), secoes=json.dumps(["dados"]))
ok("só os assuntos pedidos vêm no relatório", set(r["secoes"]) == {"dados"} and "producao" not in r["pecas"][0] and "ferros" not in r["pecas"][0])
ok("duas obras de clientes diferentes: o relatório lista os dois clientes e soma o peso", r["clientes"] == CLIENTES and r["resumo"]["peso_kg"] == 5000.0, str(r["resumo"]))
ok("assunto inventado é ignorado", api("relatorio_pecas", codigos=json.dumps([cod["RA1"]]), secoes=json.dumps(["dados", "senha_do_banco"]))["secoes"] == ["dados"])
ok("peça repetida entra uma vez só", api("relatorio_pecas", codigos=json.dumps([cod["RA1"], cod["RA1"]]))["total"] == 1)
ok("sem peça, o sistema pede para escolher", not api("relatorio_pecas", codigos=json.dumps([])).get("success"))
ok("peça que não existe é recusada com o código", "NAO-EXISTE" in api("relatorio_pecas", codigos=json.dumps(["NAO-EXISTE"])).get("error", ""))
ok("acima de 500 peças o sistema recusa e explica", "500" in api("relatorio_pecas", codigos=json.dumps([f"X{i}" for i in range(501)])).get("error", ""))
ok("o relatório exige sessão", requests.post(f"{URL}/api/method/frappe.precast_api.relatorio_pecas", json={"codigos": [cod["RA1"]]}).status_code in (401, 403))

print("[Na tela]")
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); ctx = b.new_context(viewport={"width": 1500, "height": 950}, accept_downloads=True); pg = ctx.new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message)); pg.on("dialog", lambda d: d.accept())
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(2500)
    pg.click(".nav-tab.tab-relatorios"); pg.wait_for_timeout(2500)
    ok("a aba Relatórios abre", pg.locator("#viewRelatorios").is_visible())
    pg.select_option("#relCliente", CLIENTES[0]); pg.wait_for_timeout(1500)
    ok("ao escolher o cliente as peças dele aparecem", pg.locator("#relPecas tr").count() == 4 and "RA1" in pg.inner_text("#relPecas") and "RC1" not in pg.inner_text("#relPecas"))
    ok("a contagem começa em 0 marcadas de 4", "0 marcada(s) de 4" in pg.inner_text("#relContagem"), pg.inner_text("#relContagem"))
    pg.click("#viewRelatorios >> text=Ver o relatório"); pg.wait_for_timeout(800)
    ok("sem peça marcada, o sistema pede para marcar", "Marque ao menos uma peça" in pg.inner_text("#relMsg"))
    pg.click("#viewRelatorios >> text=☑ Selecionar todas"); pg.wait_for_timeout(300)
    ok("selecionar todas marca as 4", "4 marcada(s) de 4" in pg.inner_text("#relContagem"))
    pg.click("#viewRelatorios >> text=☐ Limpar seleção"); pg.wait_for_timeout(300)
    ok("limpar seleção zera", "0 marcada(s)" in pg.inner_text("#relContagem"))
    pg.select_option("#relObra", "REL-A1"); pg.wait_for_timeout(1200)
    ok("escolher a obra reduz a lista a 3 peças", pg.locator("#relPecas tr").count() == 3)
    pg.select_option("#relObra", ""); pg.wait_for_timeout(1200)
    pg.fill("#relFiltro", "ra"); pg.wait_for_timeout(400)
    ok("o filtro esconde o que não combina (RB1 sai, RA1 a RA3 ficam)", pg.locator("#relPecas tr:not([hidden])").count() == 3 and "na lista filtrada" in pg.inner_text("#relContagem"), pg.inner_text("#relContagem"))
    pg.click("#viewRelatorios >> text=☑ Selecionar todas"); pg.wait_for_timeout(300)
    ok("selecionar todas respeita o filtro (marca só as 3 visíveis)", "3 marcada(s) de 4" in pg.inner_text("#relContagem"), pg.inner_text("#relContagem"))
    pg.fill("#relFiltro", ""); pg.wait_for_timeout(300)
    pg.click("#viewRelatorios >> text=☐ Limpar seleção")
    pg.locator("#relPecas tr", has_text="RA2").locator("input").check()
    pg.locator("#relPecas tr", has_text="RB1").locator("input").check()
    ok("marcar peças soltas: 2 de 4", "2 marcada(s) de 4" in pg.inner_text("#relContagem"))
    pg.click("#viewRelatorios >> text=Ver o relatório"); pg.wait_for_timeout(2500)
    corpo = pg.inner_text("#relCorpo")
    ok("o relatório mostra o cabeçalho com cliente, obras e totais", CLIENTES[0] in corpo and "REL-A1" in corpo and "REL-A2" in corpo and "2 peça(s)" in corpo, corpo[:220].replace("\n", " "))
    ok("e só as duas peças marcadas", "RA2" in corpo and "RB1" in corpo and "RA3" not in corpo and "RA1" not in corpo)
    pg.screenshot(path=os.path.join(os.environ.get("TEMP", "."), "relatorio.png"))
    pg.evaluate("document.getElementById('modalRelatorio').classList.remove('active')")

    pg.locator("#relPecas tr", has_text="RA2").locator("input").uncheck()
    pg.locator("#relPecas tr", has_text="RB1").locator("input").uncheck()
    pg.locator("#relPecas tr", has_text="RA1").locator("input").check()
    pg.check(".relSecao[value=rastreabilidade]"); pg.check(".relSecao[value=qualidade]"); pg.check(".relSecao[value=ferros]"); pg.check("input[name=relFormato][value=ficha]")
    pg.click("#viewRelatorios >> text=Ver o relatório"); pg.wait_for_timeout(2500)
    corpo = pg.inner_text("#relCorpo")
    ok("uma peça só, em ficha completa, com rastreabilidade e qualidade", "RA1" in corpo and LOTE in corpo)
    ok("a ficha traz a ruptura, o inspetor e a lista de ferros", "28d: 40 MPa" in corpo and "Inspetor Rel" in corpo and "Lista de ferros".upper() in corpo.upper(), corpo[-300:].replace("\n", " "))
    pg.evaluate("document.getElementById('modalRelatorio').classList.remove('active')")

    pg.evaluate("window.__html = null; window.imprimirHtml = (t, h, c) => { window.__html = h; return Promise.resolve(); }")
    pg.click("#viewRelatorios >> text=🖨️ Imprimir"); pg.wait_for_timeout(2500)
    html = pg.evaluate("window.__html") or ""
    ok("imprimir entrega ao navegador o relatório da peça marcada, sem as outras", "RA1" in html and "RA2" not in html and "Relatório de peças" in html, html[:120])

    pg.check("input[name=relFormato][value=tabela]")
    pg.locator("#relPecas tr", has_text="RB1").locator("input").check()
    with pg.expect_download() as dl:
        pg.click("#viewRelatorios >> text=⬇️ Baixar planilha (CSV)")
    linhas = list(csv.reader(open(dl.value.path(), encoding="utf-8-sig"), delimiter=";"))
    ok("a planilha tem o cabeçalho e uma linha por peça marcada (2)", len(linhas) == 3 and linhas[0][0] == "Peça" and {l[0] for l in linhas[1:]} == {"RA1", "RB1"}, str(linhas)[:200])
    ok("o nome do arquivo leva o cliente e a data", dl.value.suggested_filename.startswith("relatorio-Cliente-Relat") and dl.value.suggested_filename.endswith(".csv"), dl.value.suggested_filename)
    pg.select_option("#relCliente", CLIENTES[1]); pg.wait_for_timeout(1200)
    ok("trocar de cliente troca a lista e zera a seleção", "RC1" in pg.inner_text("#relPecas") and "RA1" not in pg.inner_text("#relPecas") and "0 marcada(s) de 2" in pg.inner_text("#relContagem"))
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
