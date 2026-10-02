"""Revisões de projeto: o que mudou entre R0a e R0e, o efeito na produção que já andou e o histórico da obra."""
import json, os, sys
import requests

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA = "REVISAO-TESTE"
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
        return {"success": False, "error": r.text[:150]}


def ferros(*linhas):
    return [{"posicao": str(i + 1), "bitola_mm": b, "quantidade": q, "comp_unit_m": c, "comp_total_m": q * c, "peso_kg": 1.0} for i, (b, q, c) in enumerate(linhas)]


def peca(cod, secao, comp, aco, lista, vol=None):
    return {"cod": cod, "tag": cod, "produto": "Pilar", "secao": secao, "comp": comp, "vol": vol or round(0.3 * 0.4 * comp, 3), "peso": 1000 * comp,
            "peso_aco_kg": aco, "ferros": lista, "fonte": "prancha", "dimensoes_confirmadas": True}


def obra(rev):
    return {"cod": OBRA, "nome": "Obra Revisão", "cliente": "Cliente", "fck": "35 MPa", "revisao": rev, "arquivo": f"EST - OBRA - {rev}.dwg"}


def gravar(rev, pecas, modo="acrescentar"):
    return api("integrate_parsed_project", obra_data=json.dumps(obra(rev)), pieces_data=json.dumps(pecas), modo=modo)


def comparar(rev, pecas):
    return api("comparar_revisao", obra_data=json.dumps(obra(rev)), pieces_data=json.dumps(pecas))


api("delete_obra", codigo_obra=OBRA)

F1 = ferros((10.0, 4, 3.0), (12.5, 2, 3.0))
R0A = [peca("PM.1", "30X40", 8.6, 80.0, F1), peca("PM.2", "30X40", 8.6, 80.0, F1), peca("PM.3", "30X40", 9.6, 90.0, F1),
       peca("PM.4", "30X40", 9.6, 90.0, F1), peca("PM.5", "30X40", 9.6, 90.0, F1)]

print("[Primeira leitura (R0a)]")
r = gravar("R0a", R0A)
ok("grava as 5 peças e registra a revisão 1", r["success"] and r["created"] == 5 and r["revisao"]["numero"] == 1 and r["revisao"]["novas"] == 5, str(r.get("revisao")))
cods = {p["tag"]: p["codigo_peca"] for p in api("get_pieces", obra=OBRA)["pieces"]}

print("[Produção anda]")
for _ in range(2):
    api("advance_piece_phase", codigo_peca=cods["PM.2"], forcar=True)    # PM.2: fase 3 (forma pronta)
for _ in range(3):
    api("advance_piece_phase", codigo_peca=cods["PM.3"], forcar=True)    # PM.3: fase 4 (concretada)
for _ in range(5):
    api("advance_piece_phase", codigo_peca=cods["PM.4"], forcar=True)    # PM.4: fase 6 (liberada)
api("advance_piece_phase", codigo_peca=cods["PM.5"], forcar=True)         # PM.5: fase 2 (armação pronta)

print("[Prévia da revisão R0e, sem gravar]")
F2 = ferros((10.0, 6, 3.0), (12.5, 2, 3.0))                              # a posição 1 passa de 4 para 6 barras
R0E = [peca("PM.1", "30X45", 8.6, 80.0, F1, vol=1.161),                  # PM.1: seção muda, ainda não começou
       peca("PM.2", "30X40", 9.0, 80.0, F1),                             # PM.2: comprimento muda, forma pronta
       peca("PM.3", "30X45", 9.6, 90.0, F1, vol=1.296),                  # PM.3: seção muda, já concretada
       peca("PM.4", "30X40", 9.6, 90.0, F1),                             # PM.4: igual
       peca("PM.5", "30X40", 9.6, 98.5, F2),                             # PM.5: aço muda, armação pronta
       peca("PM.6", "30X40", 7.0, 60.0, F1)]                             # PM.6: nova
d = comparar("R0e", R0E)
resumo = d["resumo"]
ok("conta novas, alteradas, iguais e ausentes", (resumo["novas"], resumo["alteradas"], resumo["iguais"], resumo["ausentes"]) == (1, 4, 1, 0), str(resumo))
por = {a["tag"]: a for a in d["alteradas"]}
ok("PM.1 ainda não começou: impacto nenhum", por["PM.1"]["impacto"]["nivel"] == "nenhum")
ok("PM.2 com forma pronta: atenção e manda ajustar a forma", por["PM.2"]["impacto"]["nivel"] == "atencao" and "forma" in " ".join(por["PM.2"]["impacto"]["acoes"]).lower(), str(por["PM.2"]["impacto"]))
ok("PM.3 concretada com medida antiga: crítico", por["PM.3"]["impacto"]["nivel"] == "critico" and "não conformidade" in " ".join(por["PM.3"]["impacto"]["acoes"]))
ok("PM.5 com armação pronta e aço novo: atenção, refazer armação", por["PM.5"]["impacto"]["nivel"] == "atencao" and {m["campo"] for m in por["PM.5"]["mudancas"]} == {"aco", "ferros"} and "refazer" in " ".join(por["PM.5"]["impacto"]["acoes"]).lower(), str(por["PM.5"]["mudancas"]))
ok("peça sem mudança não aparece como alterada", "PM.4" not in por)
ok("a prévia não gravou nada", len(api("get_pieces", obra=OBRA)["pieces"]) == 5 and len(api("listar_revisoes", obra=OBRA)["revisoes"]) == 1)
ok("o resumo conta 1 crítico e 2 de atenção", resumo["critico"] == 1 and resumo["atencao"] == 2, str(resumo))

print("[Gravar a revisão R0e]")
r = gravar("R0e", R0E)
ok("grava, cria a PM.6 e atualiza as outras", r["success"] and r["created"] == 1 and r["updated"] == 5 and r["revisao"]["numero"] == 2, str(r.get("revisao")))
pc = {p["tag"]: p for p in api("get_pieces", obra=OBRA)["pieces"]}
ok("a peça ganhou o desenho novo", pc["PM.1"]["secao"] == "30X45" and abs(pc["PM.2"]["comprimento_m"] - 9.0) < 0.001)
ok("a peça concretada ganhou o aviso da engenharia", "Revisão R0e" in (pc["PM.3"].get("aviso_engenharia") or "") and "não conformidade" in pc["PM.3"]["aviso_engenharia"], str(pc["PM.3"].get("aviso_engenharia"))[:140])
ok("a peça que não começou não ganhou aviso", "Revisão" not in (pc["PM.1"].get("aviso_engenharia") or ""))
ok("a peça igual não ganhou aviso", "Revisão" not in (pc["PM.4"].get("aviso_engenharia") or ""))
scan = api("get_piece_for_scan", codigo=f"PECA:{cods['PM.3']}")
ok("o operador vê o aviso ao bipar a peça", "Revisão R0e" in (scan["peca"].get("aviso_engenharia") or ""))
ok("comparar de novo o mesmo desenho: nada muda", comparar("R0e", R0E)["resumo"]["alteradas"] == 0)

print("[Histórico]")
h = api("listar_revisoes", obra=OBRA)["revisoes"]
ok("duas revisões, a mais recente primeiro", [x["revisao"] for x in h] == ["R0e", "R0a"] and [x["numero"] for x in h] == [2, 1])
ok("o histórico guarda o resumo e o que mudou em cada peça", h[0]["resumo"]["alteradas"] == 4 and len(h[0]["diff"]["alteradas"]) == 4 and h[0]["arquivo"] == "EST - OBRA - R0e.dwg")

print("[Peça fora do desenho novo]")
d = comparar("R0h", [peca("PM.1", "30X45", 8.6, 80.0, F1)])
aus = {a["tag"]: a for a in d["ausentes"]}
ok("as demais peças da obra aparecem como ausentes do arquivo (não como removidas)", len(aus) == 5 and d["resumo"]["ausentes"] == 5)
ok("as que já andaram ficam marcadas", aus["PM.3"]["ja_andou"] and aus["PM.4"]["ja_andou"] and not aus["PM.1"]["ja_andou"] if "PM.1" in aus else aus["PM.3"]["ja_andou"])
r = gravar("R0h", [peca("PM.1", "30X45", 8.6, 80.0, F1)], modo="substituir")
ok("substituir remove só as que não começaram", r["success"] and len(r["pecas_removidas"]) >= 1 and set(r["pecas_fora_do_desenho"]) >= {cods["PM.3"], cods["PM.4"]}, str((r["pecas_removidas"], r["pecas_fora_do_desenho"])))

print("[Outra obra com o mesmo código de peça]")
OUTRA = "REVISAO-TESTE-B"
api("delete_obra", codigo_obra=OUTRA)
rb = api("integrate_parsed_project", obra_data=json.dumps({**obra("R0a"), "cod": OUTRA}), pieces_data=json.dumps([peca("PM.1", "20X20", 5.0, 40.0, F1)]))
ok("a outra obra grava a sua PM.1 sem mexer nas peças da primeira", rb["success"] and rb["created"] == 1)
d = api("comparar_revisao", obra_data=json.dumps({**obra("R0b"), "cod": OUTRA}), pieces_data=json.dumps([peca("PM.1", "20X25", 5.0, 40.0, F1)]))
ok("comparar a outra obra só enxerga as peças dela", d["resumo"]["alteradas"] == 1 and d["resumo"]["ausentes"] == 0, str(d["resumo"]))
api("delete_obra", codigo_obra=OUTRA)

print("[Limpeza e permissões]")
ok("ler o histórico exige sessão", requests.post(f"{URL}/api/method/frappe.precast_api.listar_revisoes", json={"obra": OBRA}).status_code in (401, 403))
api("delete_obra", codigo_obra=OBRA)
ok("excluir a obra apaga o histórico de revisões", api("listar_revisoes", obra=OBRA)["revisoes"] == [])
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
