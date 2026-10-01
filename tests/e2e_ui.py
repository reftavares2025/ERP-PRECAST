"""
Teste de interface no Chrome real: importa um IFC, grava, abre o portal do cliente pelo botão,
cria operador e solicita assentos pela aba Equipe, e faz o operador entrar pelo celular e bipar.
Apaga o que criou. Uso: python tests/e2e_ui.py
"""
import json
import os
import sys
import uuid

import requests
from playwright.sync_api import sync_playwright

U = "http://localhost:8088"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUF = uuid.uuid4().hex[:5]
EMAIL_OP = f"op-ui-{SUF}@example.com"
resultados = []


def checar(nome, ok, detalhe=""):
    resultados.append(bool(ok))
    print(("  OK    " if ok else "  FALHA "), nome, ("- " + str(detalhe)[:160]) if detalhe else "")


def senha_admin():
    for linha in open(os.path.join(RAIZ, "precast_service_credentials.env"), encoding="utf-8"):
        if linha.startswith("ADMIN_PASSWORD="):
            return linha.split("=", 1)[1].strip()


def rodar(pw, erros):
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        ctx = b.new_context(viewport={"width": 1600, "height": 900})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: erros.append(e.message))
        pg.on("dialog", lambda d: d.accept())
        ctx.request.post(U + "/api/method/login", data=json.dumps({"usr": "Administrator", "pwd": pw}), headers={"Content-Type": "application/json"})
        pg.goto(U + "/painel", wait_until="networkidle")
        pg.wait_for_timeout(1500)

        print("[Projeto]")
        pg.click(".tab-projeto")
        pg.set_input_files("#cadFileInput", os.path.join(RAIZ, "sample_structure.ifc"))
        pg.wait_for_function("document.getElementById('metaTotalPecas').innerText.trim()==='4 peças'", timeout=90000)
        pg.wait_for_timeout(2500)
        checar("IFC lido pela tela", pg.locator("#parsedPiecesBody tr").count() == 4)
        pg.click("text=Gravar Peças no Sistema")
        pg.wait_for_timeout(6000)

        print("[Obras / portal]")
        pg.click(".tab-projeto")
        pg.locator("#subtabsContainer .subtab", has_text="Obras Cadastradas").click()
        pg.wait_for_timeout(1500)
        with ctx.expect_page() as novo:
            pg.locator("text=Portal").first.click()
        portal = novo.value
        portal.wait_for_load_state("networkidle")
        portal.wait_for_timeout(1500)
        corpo = portal.locator("body").inner_text()
        checar("botão Portal abre link com token", "t=" in portal.url, portal.url.replace(U, ""))
        checar("portal mostra o andamento", "peças" in corpo, corpo[:80].replace("\n", " "))
        portal.close()
        anon_ctx = b.new_context()
        anon = anon_ctx.new_page()
        anon.goto(U + "/portal-obra?obra=SAMPLE_STRUCTURE", wait_until="networkidle")
        anon.wait_for_timeout(800)
        checar("portal sem token pede o link completo", "link completo" in anon.locator("body").inner_text())
        anon_ctx.close()

        print("[Equipe]")
        pg.wait_for_selector("#navTabEquipe", state="visible")
        pg.click("#navTabEquipe")
        pg.wait_for_timeout(1200)
        pg.fill("#operadorNome", "Operador UI")
        pg.fill("#operadorEmail", EMAIL_OP)
        pg.click("text=Criar operador")
        pg.wait_for_timeout(2500)
        msg = pg.locator("#operadorMsg").inner_text()
        checar("criar operador pela tela", "Senha temporária" in msg, msg[:90])
        senha_op = msg.split("Senha temporária:")[1].split("—")[0].strip()
        checar("operador aparece na lista", EMAIL_OP in pg.locator("#operadoresLista").inner_text())
        pg.fill("#assentoExtraQtd", "7")
        pg.wait_for_timeout(300)
        total = pg.locator("#assentoExtraTotal").inner_text()
        checar("preço do pacote na tela (7 = R$ 748,00)", "748,00" in total, total)
        pg.click("text=Solicitar assentos")
        pg.wait_for_timeout(2500)
        texto = pg.locator("#assentoExtraMsg").inner_text()
        checar("solicitação de assentos enviada", "Solicitação enviada" in texto, texto[:90])

        print("[Operador no celular]")
        cel = b.new_context(viewport={"width": 390, "height": 800}, is_mobile=True)
        m = cel.new_page()
        m.on("pageerror", lambda e: erros.append("celular: " + e.message))
        m.on("dialog", lambda d: d.accept())
        m.goto(U + "/login", wait_until="networkidle")
        m.fill("#login_email", EMAIL_OP)
        m.fill("#login_password", senha_op)
        m.click(".btn-login")
        m.wait_for_url("**/bipar*", timeout=15000)
        checar("operador entra direto no bipar", "bipar" in m.url, m.url.replace(U, ""))
        m.wait_for_timeout(1500)
        m.click("text=Digitar Código Manualmente")
        m.fill("#manualCodeInput", "P1")
        m.click("text=Buscar Peça")
        m.wait_for_timeout(2500)
        area = m.locator("#pieceArea").inner_text()
        checar("operador encontra a peça", "P1" in area, area[:80].replace("\n", " "))
        m.click("text=Avançar para Próxima Fase")
        m.wait_for_timeout(2500)
        status = m.locator("#statusMsg").inner_text()
        checar("mensagem 'peça atualizada com sucesso'", "atualizada com sucesso" in status, status[:100])
        sess = requests.Session()
        sess.post(U + "/api/method/login", json={"usr": "Administrator", "pwd": pw})
        fase = sess.get(U + "/api/method/frappe.precast_api.get_pieces", params={"obra": "SAMPLE_STRUCTURE"}).json()["message"]["pieces"]
        checar("fase da peça mudou no sistema", any(x["tag"] == "P1" and x["fase_numero"] == 2 for x in fase), [(x["tag"], x["fase_numero"]) for x in fase])
        cel.close()
        checar("sem erros de JavaScript", not erros, erros)
        b.close()


def limpar(pw):
    s = requests.Session()
    s.post(U + "/api/method/login", json={"usr": "Administrator", "pwd": pw})
    s.post(U + "/api/method/frappe.precast_api.delete_obra", json={"codigo_obra": "SAMPLE_STRUCTURE"})
    s.delete(U + f"/api/resource/User/{EMAIL_OP}")
    for t in s.get(U + "/api/resource/ToDo", params={"filters": json.dumps([["description", "like", "%assento%"]])}).json().get("data", []):
        s.delete(U + f"/api/resource/ToDo/{t['name']}")


def main():
    pw = senha_admin()
    erros = []
    try:
        rodar(pw, erros)
    finally:
        limpar(pw)
    print(f"\n{sum(resultados)}/{len(resultados)} verificações ok")
    sys.exit(0 if all(resultados) else 1)


if __name__ == "__main__":
    main()
