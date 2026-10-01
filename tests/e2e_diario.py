"""
Diário de obra + portal do cliente + aba Cliente. API e Chrome (celular).
Cria uma obra de teste, um encarregado e registros; apaga tudo no fim.
Uso: python tests/e2e_diario.py
"""
import datetime
import io
import json
import os
import sys
import uuid

import requests
from PIL import Image
from playwright.sync_api import sync_playwright

U = "http://localhost:8088"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUF = uuid.uuid4().hex[:5].upper()
OBRA, OUTRA = f"DIA-{SUF}", f"OUT-{SUF}"
EMAIL = f"enc-{SUF.lower()}@example.com"
resultados = []
HOJE = datetime.date.today().isoformat()


def checar(nome, ok, detalhe=""):
    resultados.append(bool(ok))
    print(("  OK    " if ok else "  FALHA "), nome, ("- " + str(detalhe)[:150]) if detalhe else "")


def senha():
    for l in open(os.path.join(RAIZ, "precast_service_credentials.env"), encoding="utf-8"):
        if l.startswith("ADMIN_PASSWORD="):
            return l.split("=", 1)[1].strip()


def jpeg(cor, lado=3000):
    buf = io.BytesIO()
    Image.new("RGB", (lado, lado // 2), cor).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def chamar(s, metodo, **kw):
    r = s.post(U + f"/api/method/frappe.precast_api.{metodo}", json=kw)
    try:
        j = r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:150]}
    return r.status_code, j.get("message", j)


def main():
    pw = senha()
    adm = requests.Session()
    adm.post(U + "/api/method/login", json={"usr": "Administrator", "pwd": pw})
    try:
        rodar(adm, pw)
    finally:
        for o in (OBRA, OUTRA):
            adm.post(U + "/api/method/frappe.precast_api.delete_obra", json={"codigo_obra": o})
        for d in adm.get(U + "/api/resource/Diario Obra", params={"filters": json.dumps([["obra", "in", [OBRA, OUTRA]]])}).json().get("data", []):
            chamar(adm, "excluir_diario", registro=str(d["name"]))
        for d in adm.get(U + "/api/resource/Romaneio", params={"filters": json.dumps([["obra", "=", OBRA]])}).json().get("data", []):
            adm.delete(U + f"/api/resource/Romaneio/{d['name']}")
        chamar(adm, "delete_caminhao", placa=f"DIA{SUF}")
        for up in adm.get(U + "/api/resource/User Permission", params={"filters": json.dumps([["user", "=", EMAIL]])}).json().get("data", []):
            adm.delete(U + f"/api/resource/User Permission/{up['name']}")
        adm.delete(U + f"/api/resource/User/{EMAIL}")
        adm.delete(U + f"/api/resource/Customer/Cliente {SUF}")
    print(f"\n{sum(resultados)}/{len(resultados)} verificações ok")
    sys.exit(0 if all(resultados) else 1)


def rodar(adm, pw):
    print("[dados da obra]")
    for o in (OBRA, OUTRA):
        chamar(adm, "integrate_parsed_project", obra_data=json.dumps({"cod": o, "nome": f"Obra {o}", "cliente": f"Cliente {SUF}"}),
               pieces_data=json.dumps([{"cod": f"{o}-P{i}", "tag": f"P{i}", "produto": "Pilar", "secao": "30X40", "comp": 6, "vol": 0.72, "peso": 1800} for i in range(1, 5)]))
    chamar(adm, "create_caminhao", placa=f"DIA{SUF}", capacidade_kg=40000)
    pecas = [p["codigo_peca"] for p in adm.get(U + "/api/method/frappe.precast_api.get_pieces", params={"obra": OBRA}).json()["message"]["pieces"]]
    chamar(adm, "registrar_ruptura_cp", codigo_peca=pecas[0], fck_obtido="80")
    for fase in range(2, 7):
        chamar(adm, "advance_piece_phase", codigo_peca=pecas[0], next_fase=fase)
    for fase in (2, 3):
        chamar(adm, "advance_piece_phase", codigo_peca=pecas[1], next_fase=fase)
    _, rom = chamar(adm, "create_romaneio", obra=OBRA, caminhao=f"DIA{SUF}", data_expedicao="2026-10-10", pecas=json.dumps([pecas[0]]))
    chamar(adm, "despachar_romaneio", codigo=rom.get("codigo"))
    chamar(adm, "confirmar_entrega_romaneio", codigo=rom.get("codigo"), recebedor_nome="Seu João")

    print("[encarregado e permissões]")
    _, enc = chamar(adm, "criar_encarregado", email=EMAIL, full_name="Encarregado Teste", obras=json.dumps([OBRA]))
    checar("criar encarregado (grátis)", enc.get("success"), enc.get("error"))
    _, lst = chamar(adm, "listar_encarregados")
    checar("aparece na lista com a obra", any(e["email"] == EMAIL and OBRA in e["obras"] for e in lst.get("encarregados", [])), lst)
    so = requests.Session()
    lg = so.post(U + "/api/method/login", json={"usr": EMAIL, "pwd": enc["senha_temporaria"]})
    checar("login do encarregado cai no diário", (lg.json().get("home_page") or "").strip("/") == "diario-obra", lg.json().get("home_page"))
    _, ob = chamar(so, "obras_para_diario")
    checar("vê só a obra liberada", [o["codigo_obra"] for o in ob.get("obras", [])] == [OBRA], ob)
    code, r = chamar(so, "listar_diario", obra=OUTRA)
    checar("não lê o diário de outra obra", code >= 400 or r.get("exc_type") == "PermissionError", code)
    code, r = chamar(so, "get_link_portal", codigo_obra=OBRA)
    checar("não gera link do portal", code >= 400 or r.get("exc_type") == "PermissionError", code)
    code, r = chamar(so, "create_obra", codigo_obra="X-NAO")
    checar("não cria obra", code >= 400, code)

    print("[registro do dia com fotos]")
    foto1, foto2 = jpeg((200, 80, 40)), jpeg((30, 90, 200))
    r = so.post(U + "/api/method/frappe.precast_api.registrar_diario", data={"obra": OBRA, "data": HOJE, "clima": "Sol", "resumo": "Montamos 4 pilares do eixo A. Equipe de 6 pessoas."},
                files=[("fotos", ("a.jpg", foto1, "image/jpeg")), ("fotos", ("b.jpg", foto2, "image/jpeg"))])
    m = r.json().get("message", {})
    checar("registrar diário com 2 fotos", m.get("success") and m.get("fotos") == 2, m)
    r = so.post(U + "/api/method/frappe.precast_api.registrar_diario", data={"obra": OUTRA, "data": HOJE, "resumo": "x"})
    checar("não registra em obra não liberada", r.status_code >= 400 or r.json().get("message", {}).get("success") is not True, r.status_code)
    r = so.post(U + "/api/method/frappe.precast_api.registrar_diario", data={"obra": OBRA, "data": HOJE, "resumo": ""})
    checar("recusa registro vazio com mensagem", "Escreva" in (r.json().get("message", {}).get("error") or ""), r.text[:120])
    r = so.post(U + "/api/method/frappe.precast_api.registrar_diario", data={"obra": OBRA, "data": HOJE, "resumo": "x"}, files=[("fotos", ("x.jpg", b"isto nao e imagem", "image/jpeg"))])
    checar("recusa arquivo que não é foto", "JPG, PNG" in (r.json().get("message", {}).get("error") or ""), r.text[:120])
    r = so.post(U + "/api/method/frappe.precast_api.registrar_diario", data={"obra": OBRA, "data": "2099-01-01", "resumo": "x"})
    checar("recusa data no futuro", "futuro" in (r.json().get("message", {}).get("error") or ""), r.text[:120])
    _, dia = chamar(so, "listar_diario", obra=OBRA)
    reg = (dia.get("registros") or [{}])[0]
    checar("registro listado com as fotos", len(reg.get("fotos", [])) == 2 and "Montamos" in reg.get("resumo", ""), reg)
    img = requests.get(U + reg["fotos"][0]) if reg.get("fotos") else None
    checar("foto abre e é imagem", img is not None and img.status_code == 200 and img.headers.get("content-type", "").startswith("image/"), img.status_code if img is not None else "")
    code, r = chamar(so, "excluir_diario", registro=str(reg.get("id")))
    checar("encarregado não exclui registro", code >= 400, code)

    print("[portal do cliente]")
    _, lk = chamar(adm, "get_link_portal", codigo_obra=OBRA)
    tok = lk["url"].split("t=")[1]
    pub = requests.get(U + "/api/method/frappe.precast_api.get_status_publico_obra", params={"codigo_obra": OBRA, "t": tok}).json()["message"]
    c = pub.get("contagem", {})
    checar("contagem: 1 entregue, 1 em produção adiantada, 2 em produção", c.get("Entregue") == 1 and c.get("Em produção") == 3, c)
    checar("percentual produzido = 25%", pub.get("percentual_produzido") == 25.0, pub.get("percentual_produzido"))
    checar("entrega com recebedor", any(e.get("recebedor") == "Seu João" and e["status"] == "Entregue" for e in pub.get("entregas", [])), pub.get("entregas"))
    checar("diário no portal com fotos", len(pub.get("diario", [])) == 1 and len(pub["diario"][0]["fotos"]) == 2)
    checar("portal sem preço", "preco" not in json.dumps(pub).lower() and "custo" not in json.dumps(pub).lower())
    ruim = requests.get(U + "/api/method/frappe.precast_api.get_status_publico_obra", params={"codigo_obra": OBRA, "t": "errado"}).json()["message"]
    checar("token errado é recusado", ruim.get("success") is False)

    print("[telas no Chrome]")
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        erros = []
        cel = b.new_context(viewport={"width": 390, "height": 800}, is_mobile=True)
        m = cel.new_page()
        m.on("pageerror", lambda e: erros.append("celular: " + e.message))
        m.goto(U + "/login", wait_until="networkidle")
        m.fill("#login_email", EMAIL)
        m.fill("#login_password", enc["senha_temporaria"])
        m.click(".btn-login")
        m.wait_for_url("**/diario-obra*", timeout=15000)
        m.wait_for_timeout(1500)
        checar("diário abre no celular com a obra", OBRA in m.locator("#obra").inner_text())
        checar("registro de antes aparece na lista", "Montamos" in m.locator("#lista").inner_text())
        m.fill("#resumo", "Concretagem da laje do bloco B, 18 m³.")
        m.click("#clima .chip >> nth=1")
        m.set_input_files("#gal", [{"name": "c.jpg", "mimeType": "image/jpeg", "buffer": jpeg((10, 160, 90), 4000)}])
        m.wait_for_timeout(1200)
        checar("foto aparece na prévia (reduzida)", m.locator("#previas .f").count() == 1)
        m.click("#btnEnviar")
        m.wait_for_timeout(4000)
        checar("mensagem de sucesso", "registrado" in m.locator("#msg").inner_text(), m.locator("#msg").inner_text())
        checar("novo registro na lista com foto", "Concretagem" in m.locator("#lista").inner_text() and m.locator("#lista img").count() >= 3)
        cel.close()

        ctx = b.new_context(viewport={"width": 1500, "height": 900})
        ctx.request.post(U + "/api/method/login", data=json.dumps({"usr": "Administrator", "pwd": pw}), headers={"Content-Type": "application/json"})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: erros.append(e.message))
        pg.goto(U + "/painel", wait_until="networkidle")
        pg.wait_for_timeout(1500)
        pg.click(".tab-cliente")
        pg.wait_for_timeout(2500)
        pg.select_option("#clienteObra", OBRA)
        pg.wait_for_timeout(3000)
        frame = pg.frame_locator("#clientePreview")
        corpo = frame.locator("body").inner_text()
        checar("aba Cliente mostra o portal embutido", "diário de obra" in corpo.lower() and "situação das peças" in corpo.lower(), corpo[:80].replace("\n", " "))
        checar("portal mostra produzido, entrega e diário", "Seu João" in corpo and "Concretagem da laje" in corpo)
        checar("aba Cliente lista o diário para gestão", "Montamos" in pg.locator("#clienteDiario").inner_text())
        checar("encarregado listado na aba", EMAIL in pg.locator("#encLista").inner_text())
        port = ctx.new_page()
        port.set_viewport_size({"width": 390, "height": 800})
        port.goto(U + lk["url"], wait_until="networkidle")
        port.wait_for_timeout(1500)
        checar("portal no celular sem rolagem lateral", port.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2"))
        checar("sem erros de JavaScript", not erros, erros)
        b.close()


if __name__ == "__main__":
    main()
