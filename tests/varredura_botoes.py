"""
Varredura de botões: para cada aba e subaba, abre a tela do zero, clica em cada botão visível e
registra erro de JavaScript, chamada de API com falha ou clique sem nenhum efeito.
Confirmações (excluir etc.) são recusadas. Cria e apaga uma obra de teste para os botões terem dados.
Uso: python tests/varredura_botoes.py
"""
import json
import os
import sys

import requests
from playwright.sync_api import sync_playwright

U = "http://localhost:8088"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ABAS = [("tab-projeto", "Projeto"), ("tab-fabricacao", "Fabricação"), ("tab-logistica", "Logística"), ("tab-montagem", "Montagem"),
        ("tab-qualidade", "Qualidade"), ("tab-cotacoes", "Cotações"), ("tab-comercial", "Comercial"), ("tab-financeiro", "Financeiro"),
        ("tab-equipe", "Equipe"), ("tab-geral", "Geral")]

LISTAR = """() => {
  const vis = e => e.offsetParent !== null && !e.closest('.hidden') && e.getBoundingClientRect().width > 0;
  const nav = e => e.closest('.nav-tab, .subtab, .quick-btn, #subtabsContainer') !== null;
  return [...document.querySelectorAll('[onclick], button, a[href]')].filter(e => vis(e) && !nav(e) && e.tagName !== 'OPTION')
    .map(e => ({txt: (e.innerText || e.title || e.getAttribute('data-tooltip') || e.id || e.tagName).trim().slice(0, 60),
                oc: (e.getAttribute('onclick') || e.getAttribute('href') || '')}));
}"""

ACHAR = """(alvo) => {
  const vis = e => e.offsetParent !== null && !e.closest('.hidden') && e.getBoundingClientRect().width > 0;
  const nav = e => e.closest('.nav-tab, .subtab, .quick-btn, #subtabsContainer') !== null;
  return [...document.querySelectorAll('[onclick], button, a[href]')].filter(e => vis(e) && !nav(e) && e.tagName !== 'OPTION')
    .find(e => (e.getAttribute('onclick') || e.getAttribute('href') || '') === alvo.oc &&
               (e.innerText || e.title || e.getAttribute('data-tooltip') || e.id || e.tagName).trim().slice(0, 60) === alvo.txt) || null;
}"""

JANELA_ABRE = ("window.open", "href=", "/app", "abrirPortalObra")


def senha():
    for l in open(os.path.join(RAIZ, "precast_service_credentials.env"), encoding="utf-8"):
        if l.startswith("ADMIN_PASSWORD="):
            return l.split("=", 1)[1].strip()


def abrir(ctx, cls, sub):
    pg = ctx.new_page()
    pg.goto(U + "/painel", wait_until="networkidle")
    pg.wait_for_timeout(1200)
    pg.click("." + cls)
    pg.wait_for_timeout(900)
    if sub:
        pg.locator("#subtabsContainer .subtab", has_text=sub).first.click()
        pg.wait_for_timeout(900)
    pg.evaluate("document.querySelectorAll('.modal-backdrop.active').forEach(m=>m.classList.remove('active'))")
    return pg


def estado(pg):
    return pg.evaluate("document.body.innerText.length + '|' + document.querySelectorAll('.modal-backdrop.active').length + '|' + [...document.querySelectorAll('input,select')].map(i=>i.value).join(',').length")


def main():
    pw = senha()
    problemas, total = [], 0
    s = requests.Session()
    s.post(U + "/api/method/login", json={"usr": "Administrator", "pwd": pw})
    obra = {"cod": "VARREDURA", "nome": "Obra de varredura", "cliente": "Cliente Varredura"}
    pecas = [{"cod": f"VR{i}", "tag": f"VR{i}", "produto": "Pilar", "secao": "30X40", "comp": 6, "vol": 0.72, "peso": 1800} for i in (1, 2)]
    s.post(U + "/api/method/frappe.precast_api.integrate_parsed_project", json={"obra_data": json.dumps(obra), "pieces_data": json.dumps(pecas)})

    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome")
            ctx = b.new_context(viewport={"width": 1600, "height": 900})
            ctx.request.post(U + "/api/method/login", data=json.dumps({"usr": "Administrator", "pwd": pw}), headers={"Content-Type": "application/json"})

            for cls, nome in ABAS:
                pg = abrir(ctx, cls, None)
                subs = pg.eval_on_selector_all("#subtabsContainer .subtab", "els => els.filter(e => e.offsetParent !== null).map(e => e.innerText.trim())") if pg.locator("#subtabsContainer").is_visible() else []
                pg.close()
                for sub in (subs or [""]):
                    pg = abrir(ctx, cls, sub)
                    itens = pg.evaluate(LISTAR)
                    pg.close()
                    vistos = set()
                    for it in itens:
                        chave = (it["txt"], it["oc"])
                        if chave in vistos:
                            continue
                        vistos.add(chave)
                        total += 1
                        pg = abrir(ctx, cls, sub)
                        eventos = []
                        pg.on("pageerror", lambda e: eventos.append(("JS", e.message[:140])))
                        pg.on("response", lambda r: eventos.append(("HTTP%d" % r.status, r.url.replace(U, "")[:80])) if r.status >= 400 else (eventos.append(("API", r.url)) if "/api/method/" in r.url else None))
                        pg.on("dialog", lambda d: (eventos.append(("DIALOG", d.message[:80])), d.dismiss() if d.type == "confirm" else d.accept()))
                        ctx.on("page", lambda np: eventos.append(("POPUP", np.url)))
                        pg.wait_for_timeout(500)
                        eventos.clear()
                        antes = estado(pg)
                        alvo = pg.evaluate_handle(ACHAR, it)
                        el = alvo.as_element()
                        if el is None:
                            pg.close()
                            continue
                        try:
                            el.click(timeout=4000)
                        except Exception as e:
                            problemas.append((nome, sub, it["txt"], it["oc"][:70], "NÃO CLICÁVEL: " + str(e).splitlines()[0][:80]))
                            pg.close()
                            continue
                        pg.wait_for_timeout(1800)
                        depois = estado(pg) if not pg.is_closed() else antes
                        ruins = [e for e in eventos if e[0] in ("JS",) or e[0].startswith("HTTP")]
                        efeito = antes != depois or any(e[0] in ("API", "DIALOG", "POPUP") for e in eventos) or any(x in it["oc"] for x in JANELA_ABRE)
                        if ruins:
                            problemas.append((nome, sub, it["txt"], it["oc"][:70], str(ruins[:2])))
                        elif not efeito:
                            problemas.append((nome, sub, it["txt"], it["oc"][:70], "SEM EFEITO"))
                        for extra in ctx.pages:
                            if extra != pg:
                                extra.close()
                        pg.close()
            b.close()
    finally:
        s.post(U + "/api/method/frappe.precast_api.delete_obra", json={"codigo_obra": "VARREDURA"})
        for t in s.get(U + "/api/resource/ToDo", params={"filters": json.dumps([["description", "like", "%assento%"]])}).json().get("data", []):
            s.delete(U + f"/api/resource/ToDo/{t['name']}")

    print(f"{total} botões testados, {len(problemas)} com problema")
    for pr in problemas:
        print(" -", " / ".join(x for x in pr[:2] if x), "|", pr[2].replace("\n", " "), "|", pr[3], "|", pr[4])
    sys.exit(1 if problemas else 0)


if __name__ == "__main__":
    main()
