"""Leitura das pranchas de detalhamento pelo painel: importar o DWG da obra 109-26, conferir peças, dados e
imagens, excluir a obra e conferir que nada fica para trás.

Precisa do DWG de detalhamento (rede R:) ou de um caminho em RBR_DWG_DETALHAMENTO."""
import json, os, sys, time
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("RBR_URL", "http://localhost:8088")
CAD = "http://localhost:2026"
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
_NOME_DWG = "109 - 26 - RODRIGO FEIJÃO - ITAPETININGA - SP - R1- DETALHAMENTOS 17-09-26.dwg"
_NA_REDE = (r"R:\ENGENHARIA\DT_2026\RBR_DETAL_2026\109 - 26 - RODRIGO FEIJÃO - CEREALISTA OLIVEIRA - ITAPETININGA - SP\DETALHAMENTO"
            "\\" + _NOME_DWG)
_NO_UPLOADS = os.path.join(os.environ.get("PRECAST_UPLOADS_DIR") or r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg", _NOME_DWG)
# A planta fica na rede da engenharia; sem a rede, vale a cópia que já está na pasta de uploads do motor CAD.
DWG = os.environ.get("RBR_DWG_DETALHAMENTO") or (_NA_REDE if os.path.exists(_NA_REDE) else _NO_UPLOADS)
OBRA = "109 - 26"
ESPERADAS = {"PM.01", "PM.02", "PM.03", *[f"PM.{n:02d}" for n in range(4, 15)], "VM-1.1", "VM-2.1", "VM-1.3", "VM-2.3", "VM-1.4", "VM-2.4",
             "VM-1.5", "VM-2.5", "VM-1.7", "VM-1.8"}
DUAS_UNIDADES = {"VM-1.2", "VM-1.6", "VM-2.8", "VM-2.2", "VM-2.7", "VM-2.6"}  # um código, título "- 2X"
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


s = requests.Session()
s.post(URL + "/api/method/login", json={"usr": "Administrator", "pwd": SENHA})


def api(metodo, **corpo):
    return s.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo).json().get("message", {})


def pecas():
    """Peças da obra pelo código do desenho. Se outra obra do sistema já usa o código (PM.01 é comum), o sistema
    grava com o prefixo da obra; aqui o prefixo é ignorado."""
    return {(p["codigo_peca"][len(OBRA) + 1:] if p["codigo_peca"].startswith(OBRA + "-") else p["codigo_peca"]): p for p in api("get_pieces", obra=OBRA).get("pieces", [])}


api("delete_obra", codigo_obra=OBRA)
requests.post(CAD + "/api/limpar-obra", json={"codigo_obra": OBRA})

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome"); pg = b.new_context(viewport={"width": 1500, "height": 900}).new_page()
    erros = []; pg.on("pageerror", lambda e: erros.append(e.message))
    avisos = []; pg.on("dialog", lambda d: (avisos.append(d.message), d.accept()))
    pg.goto(URL + "/login", wait_until="networkidle"); pg.fill("#login_email", "Administrator"); pg.fill("#login_password", SENHA); pg.click(".btn-login"); pg.wait_for_timeout(5000)
    pg.goto(URL + "/painel", wait_until="networkidle"); pg.wait_for_timeout(1500)
    pg.evaluate("switchModule('projeto')"); pg.wait_for_timeout(800)

    print("[Leitura]")
    t = time.time()
    pg.set_input_files("#cadFileInput", DWG)
    pg.wait_for_function("document.getElementById('modoLeituraCad') && document.getElementById('modoLeituraCad').innerText.length > 5", timeout=900000)
    ok("leitura termina em menos de 15 minutos", time.time() - t < 900, f"{round(time.time() - t)} s")
    ok("modo pranchas de detalhamento", "pranchas de detalhamento" in pg.inner_text("#modoLeituraCad") and "24 pranchas" in pg.inner_text("#modoLeituraCad"), pg.inner_text("#modoLeituraCad")[:90])
    pg.wait_for_function("document.getElementById('modoLeituraCad').innerText.includes('prontas')", timeout=900000)
    ok("imagens geradas em segundo plano em menos de 15 minutos", time.time() - t < 900, f"{round(time.time() - t)} s")
    pg.click("text=Gravar Peças no Sistema")
    for _ in range(45):  # a gravação (36 peças, QR Codes) pode levar um minuto com o sistema ocupado
        time.sleep(2)
        if len(pecas()) >= 36:
            break

    print("[Peças gravadas]")
    lidas = pecas()
    codigos = set(lidas)
    unidades = {c.rsplit("_", 1)[0] for c in codigos if "_" in c}
    ok("36 peças", len(lidas) == 36, str(len(lidas)))
    ok("todas as peças esperadas das pranchas", ESPERADAS <= codigos, str(sorted(ESPERADAS - codigos)))
    ok("peças de código único com 2 unidades numeradas", unidades == DUAS_UNIDADES, str(sorted(unidades)))
    ok("nenhuma peça de legenda ou planta (P01.., E1.., BM.., PM1..)", not any(c.startswith(("P0", "E", "B", "PM1", "PM2")) and not c.startswith(("PM.", "VM")) for c in codigos), str(sorted(c for c in codigos if not c.startswith(("PM.", "VM")))))
    pm1 = lidas["PM.01"]
    ok("PM.01: seção 30X40, 8,60 m, volume 0,942 m³", pm1["secao"] == "30X40" and pm1["comprimento_m"] == 8.6 and pm1["volume_m3"] == 0.942, str({k: pm1[k] for k in ("secao", "comprimento_m", "volume_m3")}))
    ok("PM.01: aço 80,372 kg da lista de materiais", abs((pm1.get("peso_aco_kg") or 0) - 80.372) < 0.01, str(pm1.get("peso_aco_kg")))
    ok("todas com dimensões confirmadas", all(p["dimensoes_confirmadas"] for p in lidas.values()))
    d = api("get_detalhe_prancha", codigo_peca=lidas["PM.01"]["codigo_peca"])
    ok("PM.01: lista de ferros com 5 posições", len(d.get("ferros", [])) == 5 and d["ferros"][0]["quantidade"] == 5, str(d.get("ferros", [])[:1]))

    print("[Pranchas]")
    sem_imagem = [c for c, p in lidas.items() if not p.get("prancha_url") or requests.get(URL + p["prancha_url"]).status_code != 200]
    ok("toda peça tem PDF da prancha", not sem_imagem, str(sem_imagem[:5]))
    img = requests.get(URL + lidas["PM.01"]["print_url"])
    ok("imagem da prancha é a folha inteira (> 100 KB)", img.status_code == 200 and len(img.content) > 100_000, f"{len(img.content)} bytes")
    pdf = requests.get(URL + lidas["VM-1.1"]["prancha_url"])
    ok("PDF da prancha é um PDF", pdf.content[:4] == b"%PDF")
    import fitz
    pagina = fitz.open(stream=pdf.content, filetype="pdf")[0]
    ok("PDF em página A3 paisagem (420 x 297 mm)", abs(pagina.rect.width - 1190.55) < 2 and abs(pagina.rect.height - 841.89) < 2, str(pagina.rect))
    imagem = pagina.get_images()[0]
    ok("folha em 300 dpi (todos os números legíveis)", imagem[2] >= 4000, f"{imagem[2]} px de largura")

    print("[QR ligado à prancha]")
    for cod in ("PM.01", "PM.14", "VM-1.2_2", "VM-2.6_1"):
        scan = api("get_piece_for_scan", codigo=f"PECA:{lidas[cod]['codigo_peca']}")
        ok(f"QR de {cod} abre a prancha dele", scan.get("success") and scan["peca"]["print_url"] == lidas[cod]["print_url"] and cod.split("_")[0] in scan["peca"]["print_url"].replace("_", "-").replace("--", "-") or scan["peca"]["print_url"].endswith(f"{cod}.png"), scan.get("peca", {}).get("print_url"))

    print("[Tela da prancha]")
    pg.evaluate("switchModule('fabricacao')"); pg.wait_for_timeout(2500)
    pg.evaluate(f"openPranchaModal('{lidas['PM.01']['codigo_peca']}')"); pg.wait_for_selector("#pranchaFerros table", timeout=15000)
    ok("modal mostra a lista de ferros", "posição" in pg.inner_text("#pranchaFerros").lower() and "80,372" in pg.inner_text("#pranchaFerros"), pg.inner_text("#pranchaFerros")[:90].replace("\n", " "))
    pg.evaluate("closePranchaModal()")

    print("[Revisão do projeto]")
    revisoes = api("listar_revisoes", obra=OBRA).get("revisoes", [])
    ok("a revisão do arquivo (R1) ficou registrada na obra", len(revisoes) == 1 and revisoes[0]["revisao"] == "R1" and revisoes[0]["resumo"]["novas"] == 36, str([(r["revisao"], r["resumo"]) for r in revisoes]))
    print("[Exclusão total]")
    pg.evaluate("switchModule('projeto')"); pg.wait_for_timeout(500)
    urls = [lidas["PM.01"]["prancha_url"], lidas["PM.01"]["print_url"]]
    pg.evaluate(f"confirmDeleteObra('{OBRA}')"); pg.wait_for_timeout(6000)
    ok("obra sumiu do sistema", not api("get_pieces", obra=OBRA).get("pieces"))
    ok("PDF e imagem da prancha apagados do servidor", all(requests.get(URL + u).status_code == 404 for u in urls))
    prefixo = "109_-_26__"
    restos = [f for f in os.listdir(r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg") if prefixo in f and f.startswith(("print_", "prancha_"))]
    ok("pranchas do motor CAD apagadas", not restos, str(restos[:3]))
    ok("sem erros de JavaScript", not erros, str(erros))
    b.close()

print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
