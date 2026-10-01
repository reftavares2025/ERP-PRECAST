"""
Teste de ponta a ponta do sistema rodando (http://localhost:8088 + motor CAD em :2026).

Importa um projeto real (PDF, DXF e DWG), grava as peças, anda pelas fases com a trava
de corpo de prova, RNC, romaneio, faturas, NF-e, QR, operador de fábrica, assentos,
portal do cliente e formulário de contato. Apaga tudo que criou no final.

Uso:  python tests/e2e_sistema.py [--sem-dwg]
Credencial: ADMIN_PASSWORD em precast_service_credentials.env (fora do git).
"""
import json
import os
import sys
import time
import uuid

import requests

U = "http://localhost:8088"
CAD = "http://localhost:2026"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
from precast_caminhos import pasta_de_uploads

AMOSTRAS = pasta_de_uploads()
BASE = "BM37-BM38-BM39-BM40-BM41"
SUFIXO = uuid.uuid4().hex[:5].upper()
OBRA = f"E2E-{SUFIXO}"

resultados = []


def checar(nome, condicao, detalhe=""):
    resultados.append((nome, bool(condicao), detalhe))
    print(("  OK   " if condicao else "  FALHA"), nome, ("- " + str(detalhe)[:180]) if detalhe else "")
    return bool(condicao)


def credencial():
    with open(os.path.join(RAIZ, "precast_service_credentials.env"), encoding="utf-8") as f:
        for linha in f:
            if linha.startswith("ADMIN_PASSWORD="):
                return linha.split("=", 1)[1].strip()
    raise SystemExit("ADMIN_PASSWORD ausente")


def sessao(usuario, senha):
    s = requests.Session()
    r = s.post(U + "/api/method/login", json={"usr": usuario, "pwd": senha})
    return s, r


def chamar(s, metodo, **kw):
    r = s.post(U + f"/api/method/frappe.precast_api.{metodo}", json=kw)
    try:
        j = r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:200]}
    if "message" in j and isinstance(j["message"], (dict, list)):
        return r.status_code, j["message"]
    return r.status_code, j


def ler_projeto(caminho):
    with open(caminho, "rb") as f:
        r = requests.post(CAD + "/api/parse-cad", files={"file": (os.path.basename(caminho), f)})
    job = r.json().get("job_id")
    fim = time.time() + 420
    while time.time() < fim:
        st = requests.get(CAD + f"/api/parse-status/{job}").json()
        if st.get("done"):
            return st
        time.sleep(3)
    return {"done": True, "error": "timeout"}


def main():
    sem_dwg = "--sem-dwg" in sys.argv
    s, r = sessao("Administrator", credencial())
    checar("login Administrator", r.status_code == 200)
    criados = {"obra": OBRA, "operador": f"op-{SUFIXO.lower()}@example.com"}
    invoices = []

    try:
        print("\n[1] Importação de projetos")
        pdf_sem_texto = os.path.join(AMOSTRAS, f"{BASE}.pdf")
        st = ler_projeto(pdf_sem_texto)
        checar("PDF sem texto explica o motivo", st.get("error") and "texto" in st["error"], st.get("error"))
        for ext, nome in (("pdf", "PO-52 - 26 - SEVY - SENAI - PP.1"), ("dxf", BASE)) + (() if sem_dwg else (("dwg", BASE),)):
            arq = os.path.join(AMOSTRAS, f"{nome}.{ext}")
            if not os.path.exists(arq):
                checar(f"leitura .{ext}", False, "arquivo de amostra ausente")
                continue
            t0 = time.time()
            st = ler_projeto(arq)
            res = st.get("result") or {}
            pecas = res.get("pieces") or []
            checar(f"leitura .{ext}", st.get("done") and not st.get("error") and len(pecas) > 0,
                   f"{len(pecas)} peças em {time.time() - t0:.0f}s {st.get('error') or ''}")
            if ext == "dxf":
                projeto = res

        pecas = (projeto or {}).get("pieces") or []
        obra_dados = dict((projeto or {}).get("obra") or {})
        obra_dados["cod"] = OBRA
        obra_dados.setdefault("nome", OBRA)
        pecas = pecas[:4]
        _, g = chamar(s, "integrate_parsed_project", obra_data=json.dumps(obra_dados), pieces_data=json.dumps(pecas))
        checar("gravar peças no ERPNext", g.get("success"), g.get("error") or g.get("message"))
        _, lista = chamar(s, "get_pieces", obra=OBRA)
        cods = [p["codigo_peca"] for p in lista.get("pieces", [])]
        checar("peças cadastradas na obra", len(cods) >= 2, f"{len(cods)} peças")
        A, B = cods[0], cods[1]
        _, st = chamar(s, "estimar_custos_pecas", pecas=json.dumps(pecas))
        checar("orçador automático", st.get("success") and st.get("total_preco_venda_sugerido", 0) > 0,
               st.get("total_preco_venda_sugerido"))

        print("\n[2] Fases, corpo de prova e RNC")
        for fase in (2, 3, 4):
            _, a = chamar(s, "advance_piece_phase", codigo_peca=A, next_fase=fase)
            checar(f"avançar para fase {fase}", a.get("success"), a.get("error"))
        _, a = chamar(s, "advance_piece_phase", codigo_peca=B, next_fase=4)
        checar("bloqueia pular fase sem forçar", a.get("bloqueado_sequencia") is True, a.get("error"))
        _, a = chamar(s, "advance_piece_phase", codigo_peca=A, next_fase=5)
        checar("desforma bloqueada sem corpo de prova", a.get("bloqueado_fck") is True, a.get("error"))
        _, c = chamar(s, "registrar_ruptura_cp", codigo_peca=A, fck_obtido="10")
        checar("CP reprovado registrado", c.get("success") and c.get("aprovado") is False)
        _, a = chamar(s, "advance_piece_phase", codigo_peca=A, next_fase=5)
        checar("CP reprovado continua bloqueando", a.get("bloqueado_fck") is True)
        _, c = chamar(s, "registrar_ruptura_cp", codigo_peca=A, fck_obtido="80")
        checar("CP aprovado registrado", c.get("success") and c.get("aprovado") is True)
        for fase in (5, 6):
            _, a = chamar(s, "advance_piece_phase", codigo_peca=A, next_fase=fase)
            checar(f"avançar para fase {fase}", a.get("success"), a.get("error"))

        _, n = chamar(s, "abrir_nao_conformidade", codigo_peca=A, descricao="Teste E2E: fissura")
        checar("abrir RNC", n.get("success"), n.get("error"))
        rnc = n.get("name")

        print("\n[3] Logística")
        chamar(s, "create_transportadora", nome=f"Transp {SUFIXO}")
        chamar(s, "create_motorista", nome=f"Motorista {SUFIXO}", transportadora=f"Transp {SUFIXO}")
        placa = f"E2E{SUFIXO}"
        _, c = chamar(s, "create_caminhao", placa=placa, capacidade_kg=40000, transportadora=f"Transp {SUFIXO}")
        checar("cadastrar caminhão", c.get("success"), c.get("error"))
        _, r1 = chamar(s, "create_romaneio", obra=OBRA, caminhao=placa, data_expedicao="2026-10-15", pecas=json.dumps([A]))
        checar("RNC aberta bloqueia o romaneio", r1.get("success") is False, r1.get("error"))
        _, ap = chamar(s, "aprovar_nao_conformidade", name=rnc, receita_reparo="Argamassa de reparo")
        checar("aprovar RNC", ap.get("success"), ap.get("error"))
        _, cf = chamar(s, "sugerir_carretas", codigo_obra=OBRA)
        checar("sugerir carretas", cf.get("success") and cf.get("carretas_sugeridas", 0) >= 1, cf)
        _, r2 = chamar(s, "create_romaneio", obra=OBRA, caminhao=placa, data_expedicao="2026-10-15", pecas=json.dumps([A]))
        checar("montar romaneio", r2.get("success"), r2.get("error"))
        rom = r2.get("codigo")
        criados["romaneio"] = rom
        _, d = chamar(s, "despachar_romaneio", codigo=rom)
        checar("despachar romaneio", d.get("success"), d.get("error"))
        _, fr = chamar(s, "gerar_fatura_romaneio", codigo_romaneio=rom)
        checar("fatura do romaneio", fr.get("success"), fr.get("error"))
        if fr.get("sales_invoice"):
            invoices.append(fr["sales_invoice"])
        _, en = chamar(s, "confirmar_entrega_romaneio", codigo=rom, recebedor_nome="Fulano Teste")
        checar("canhoto eletrônico", en.get("success"), en.get("error"))
        _, m = chamar(s, "confirm_montagem", codigo_peca=A)
        checar("confirmar montagem (fase 8)", m.get("success"), m.get("error"))
        _, fm = chamar(s, "gerar_fatura_montagem", codigo_obra=OBRA)
        checar("fatura por montagem", fm.get("success"), fm.get("error"))
        if fm.get("sales_invoice"):
            invoices.append(fm["sales_invoice"])
        if invoices:
            _, nf = chamar(s, "emitir_nfe_pynfe", sales_invoice_name=invoices[0])
            checar("NF-e responde com erro claro quando falta certificado", isinstance(nf, dict) and (nf.get("success") is False) and bool(nf.get("error")), nf.get("error") or nf)
        _, sf = chamar(s, "testar_conexao_sefaz_pynfe")
        checar("teste de conexão SEFAZ responde", isinstance(sf, dict), str(sf)[:120])

        print("\n[4] QR, formas e carbono")
        _, q = chamar(s, "get_or_generate_qrcode", codigo_peca=B)
        url = q.get("url") or q.get("qr_url") or q.get("file_url")
        ok_q = False
        if url:
            ok_q = requests.get(U + url).status_code == 200
        checar("QR code gerado e acessível", q.get("success") and ok_q, q)
        _, co = chamar(s, "estimar_carbono_peca", codigo_peca=B)
        checar("pegada de carbono", co.get("success"), co.get("error"))
        _, ot = chamar(s, "otimizar_corte_aco", comprimentos_necessarios=json.dumps([3, 4, 5, 6]))
        checar("otimizar corte de aço", ot.get("success"))

        print("\n[5] Operador de fábrica (bipar)")
        _, op = chamar(s, "criar_operador", email=criados["operador"], full_name="Operador Teste")
        checar("criar operador (sem custo)", op.get("success"), op.get("error"))
        if op.get("success"):
            so, lo = sessao(criados["operador"], op["senha_temporaria"])
            checar("operador faz login", lo.status_code == 200, lo.text[:120])
            checar("operador cai no bipar", (lo.json().get("home_page") or "").strip("/") == "bipar", lo.json().get("home_page"))
            _, sc = chamar(so, "get_piece_for_scan", codigo=q.get("payload"))
            checar("operador bipa a peça", sc.get("success"), sc.get("error"))
            _, av = chamar(so, "advance_piece_phase", codigo_peca=B, next_fase=2)
            checar("operador avança a fase ('peça atualizada')", av.get("success"), av.get("error"))
            code, ne = chamar(so, "create_obra", codigo_obra="NAO-PODE")
            checar("operador não cria obra", code >= 400 or ne.get("exc_type") == "PermissionError", code)
            code, ne = chamar(so, "listar_assentos")
            checar("operador não vê assentos", code >= 400 or ne.get("exc_type") == "PermissionError", code)
        _, ls = chamar(s, "listar_assentos")
        checar("operador não consome assento", all(a["usados"] <= a["limite"] for a in ls.get("assentos", [])) and criados["operador"] in ls.get("operadores", []))

        print("\n[6] Assentos extras")
        _, sol = chamar(s, "solicitar_assento_extra", setor="Produção", quantidade=5)
        checar("solicitar 5 assentos = R$ 490", sol.get("success") and sol.get("total_mensal") == 490.0, sol)
        _, sol = chamar(s, "solicitar_assento_extra", setor="Produção", quantidade=10)
        checar("10 assentos = R$ 890", sol.get("total_mensal") == 890.0, sol)
        _, sol = chamar(s, "solicitar_assento_extra", setor="Produção", quantidade=7)
        checar("7 assentos = 490 + 2x129", sol.get("total_mensal") == 748.0, sol)
        _, lim = chamar(s, "definir_limite_assento", setor="Produção", limite=2)
        checar("Administrator sobe o limite", lim.get("success") and lim.get("limite") == 2)
        _, ls = chamar(s, "listar_assentos")
        checar("limite novo aparece", next(a for a in ls["assentos"] if a["setor"] == "Produção")["limite"] == 2)
        chamar(s, "definir_limite_assento", setor="Produção", limite=1)

        print("\n[7] Portal do cliente")
        _, lk = chamar(s, "get_link_portal", codigo_obra=OBRA)
        checar("link do portal com token", lk.get("success") and "t=" in lk.get("url", ""), lk)
        anon = requests.Session()
        r = anon.get(U + "/api/method/frappe.precast_api.get_status_publico_obra", params={"codigo_obra": OBRA}).json()["message"]
        checar("portal sem token é recusado", r.get("success") is False)
        r = anon.get(U + "/api/method/frappe.precast_api.get_status_publico_obra", params={"codigo_obra": OBRA, "t": "x" * 24}).json()["message"]
        checar("portal com token errado é recusado", r.get("success") is False)
        tok = lk["url"].split("t=")[1]
        r = anon.get(U + "/api/method/frappe.precast_api.get_status_publico_obra", params={"codigo_obra": OBRA, "t": tok}).json()["message"]
        checar("portal com token certo mostra o andamento", r.get("success") and r.get("total_pecas", 0) >= 2, r)
        checar("portal não expõe preço", "preco" not in json.dumps(r).lower() and "valor" not in json.dumps(r).lower())

        print("\n[8] Formulário de contato + WhatsApp")
        r = requests.post(U + "/api/method/frappe.precast_api.enviar_contato", json={
            "nome": f"Teste E2E {SUFIXO}", "email": "e2e@example.com", "empresa": "Empresa E2E", "telefone": "19999999999", "mensagem": "teste automático"})
        checar("formulário de contato (visitante)", r.status_code == 200 and r.json().get("message", {}).get("success"), r.text[:150])
    finally:
        print("\n[limpeza]")
        for inv in invoices:
            s.delete(U + f"/api/resource/Sales Invoice/{inv}")
        if criados.get("romaneio"):
            chamar(s, "delete_romaneio", codigo=criados["romaneio"])
        chamar(s, "delete_obra", codigo_obra=OBRA)
        cliente = (locals().get("obra_dados") or {}).get("cliente")
        if cliente:
            s.delete(U + f"/api/resource/Customer/{cliente}")
        for it in s.get(U + "/api/resource/Item", params={"filters": json.dumps([["item_code", "like", "PRECAST-%"]])}).json().get("data", []):
            s.delete(U + f"/api/resource/Item/{it['name']}")
        placa = f"E2E{SUFIXO}"
        chamar(s, "delete_caminhao", placa=placa)
        chamar(s, "delete_motorista", nome=f"Motorista {SUFIXO}")
        chamar(s, "delete_transportadora", nome=f"Transp {SUFIXO}")
        s.post(U + f"/api/method/frappe.client.set_value", json={"doctype": "User", "name": criados["operador"], "fieldname": "enabled", "value": 0})
        s.delete(U + f"/api/resource/User/{criados['operador']}")
        for nome in s.get(U + "/api/resource/Contato Comercial", params={"filters": json.dumps([["nome", "like", f"%{SUFIXO}%"]])}).json().get("data", []):
            s.delete(U + f"/api/resource/Contato Comercial/{nome['name']}")
        for lead in s.get(U + "/api/resource/Lead", params={"filters": json.dumps([["lead_name", "like", f"%{SUFIXO}%"]])}).json().get("data", []):
            s.delete(U + f"/api/resource/Lead/{lead['name']}")
        for t in s.get(U + "/api/resource/ToDo", params={"filters": json.dumps([["description", "like", "%solicit%Produção%"]]), "limit": 50}).json().get("data", []):
            s.delete(U + f"/api/resource/ToDo/{t['name']}")

    falhas = [r for r in resultados if not r[1]]
    print(f"\n{len(resultados) - len(falhas)}/{len(resultados)} verificações ok")
    for n, _, d in falhas:
        print("FALHOU:", n, "-", d)
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
