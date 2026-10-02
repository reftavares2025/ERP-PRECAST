"""Plano de corte e dobra do aço: barras por bitola, perda, emendas, peso, ciclo de vida do plano e revisão de projeto."""
import json, os, sys
import requests

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA = "CORTE-TESTE"
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


def ferro(pos, bitola, qtd, comp):
    return {"posicao": str(pos), "bitola_mm": bitola, "quantidade": qtd, "comp_unit_m": comp, "comp_total_m": round(qtd * comp, 3), "peso_kg": 1.0}


def peca(cod, ferros, aco=50.0):
    return {"cod": cod, "tag": cod, "produto": "Pilar", "secao": "30X40", "comp": 8.0, "vol": 0.96, "peso": 2400, "peso_aco_kg": aco,
            "ferros": ferros, "fonte": "prancha", "dimensoes_confirmadas": True}


def gravar(rev, pecas):
    return api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Corte", "cliente": "C", "revisao": rev}), pieces_data=json.dumps(pecas))


def limpar():
    api("config_corte", barra_m=12, traspasse_diametros=40, retalho_minimo_m=0.5)
    api("delete_obra", codigo_obra=OBRA)


limpar()

print("[Parâmetros]")
c = api("config_corte")
ok("padrões: barra de 12 m, traspasse de 40ø, retalho de 0,5 m", (c["barra_m"], c["traspasse_diametros"], c["retalho_minimo_m"]) == (12.0, 40.0, 0.5), str(c))
ok("recusa barra fora do possível", not api("config_corte", barra_m=99).get("success"))
ok("recusa valor que não é número", not api("config_corte", barra_m="abc").get("success"))

print("[Plano com resultado conhecido]")
# Ø10: 4 barras de 3,0 m por peça x 3 peças = 12 cortes de 3,0 m  -> 3 barras de 12 m (4 cortes cada), sem perda.
# Ø12,5: 2 barras de 8,0 m por peça x 3 peças = 6 cortes de 8,0 m -> 6 barras (só cabe 1 por barra), sobra de 4,0 m em cada.
# Ø6,3 (estribos): 20 de 0,5 m por peça x 3 = 60 cortes de 0,5 m -> 24 por barra: 3 barras (24 + 24 + 12).
F = [ferro(1, 10.0, 4, 3.0), ferro(2, 12.5, 2, 8.0), ferro(3, 6.3, 20, 0.5)]
gravar("R0a", [peca("CP1", F), peca("CP2", F), peca("CP3", F)])
el = api("pecas_para_corte", obra=OBRA)["pecas"]
ok("as 3 peças estão em Corte e Dobra, com 3 posições de ferro", len(el) == 3 and all(p["ferros"] == 3 and p["plano"] is None for p in el))
r = api("gerar_plano_corte", obra=OBRA)
ok("gera o plano", r.get("success") and r["numero"] == 1, str(r.get("error")))
por = {b["bitola_mm"]: b for b in r["por_bitola"]}
ok("Ø10: 12 cortes de 3 m cabem em 3 barras, sem perda", por[10.0]["barras"] == 3 and por[10.0]["aproveitamento_pct"] == 100.0, str(por[10.0]["barras"]))
ok("Ø12,5: 6 cortes de 8 m ocupam 6 barras", por[12.5]["barras"] == 6 and por[12.5]["aproveitamento_pct"] == 66.7, str(por[12.5]["barras"]))
ok("Ø12,5: a sobra de 4 m de cada barra é aproveitável como retalho", por[12.5]["sobra_aproveitavel_m"] == 24.0)
ok("Ø6,3: 60 estribos de 0,5 m em 3 barras (24 + 24 + 12)", por[6.3]["barras"] == 3 and sorted(p["vezes"] for p in por[6.3]["padroes"]) == [1, 2], str(por[6.3]["padroes"]))
ok("o peso segue ø² x 0,00617 kg/m", abs(por[10.0]["aco_necessario_kg"] - 36 * 100 * 0.00617) < 0.2 and abs(por[10.0]["aco_comprado_kg"] - 3 * 12 * 100 * 0.00617) < 0.2, str(por[10.0]))
res = r["resumo"]
ok("o resumo soma as bitolas", res["barras"] == 12 and res["cortes"] == 12 + 6 + 60 and res["pecas"] == 3, str(res))
ok("perda total entre 0 e 100% e coerente com o aço", 0 < res["perda_pct"] < 100 and res["aco_comprado_kg"] > res["aco_necessario_kg"], str(res))
ok("a lista de corte traz peça, posição, bitola e quantidade", len(r["lista_de_corte"]) == 9 and {x["tag"] for x in r["lista_de_corte"]} == {"CP1", "CP2", "CP3"})
ok("cada corte sabe de qual barra e qual peça saiu", len(r["barras"]) == 78 and all(x["tag"] and x["barra"] for x in r["barras"]))
ok("as peças ficam marcadas com o plano", all(p["plano"] for p in api("pecas_para_corte", obra=OBRA)["pecas"]))
r2 = api("gerar_plano_corte", obra=OBRA)
ok("não gera de novo para peças que já estão num plano", not r2.get("success") and ("Não há peças" in r2.get("error", "") or "já estão" in r2.get("error", "")), r2.get("error", "")[:90])
ok("não aceita peça que já está em plano", not api("gerar_plano_corte", obra=OBRA, pecas=json.dumps([el[0]["codigo_peca"]])).get("success"))

print("[Ciclo de vida]")
plano = r["plano"]
ok("abre o plano gravado", api("get_plano_corte", plano=plano)["resumo"]["barras"] == 12)
ok("lista os planos da obra", [p["status"] for p in api("listar_planos_corte", obra=OBRA)["planos"]] == ["Gerado"])
ok("passa para Em corte", api("mudar_status_plano_corte", plano=plano, status="Em corte").get("success"))
ok("recusa situação inventada", not api("mudar_status_plano_corte", plano=plano, status="Voando").get("success"))
ok("cancelar libera as peças", api("mudar_status_plano_corte", plano=plano, status="Cancelado").get("success") and all(p["plano"] is None for p in api("pecas_para_corte", obra=OBRA)["pecas"]))
ok("plano cancelado não muda mais", not api("mudar_status_plano_corte", plano=plano, status="Concluído").get("success"))

print("[Barra menor que o ferro: emendas]")
r = api("gerar_plano_corte", obra=OBRA, pecas=json.dumps([el[0]["codigo_peca"]]), barra_m=6)
por = {b["bitola_mm"]: b for b in r["por_bitola"]}
ok("com barra de 6 m, o ferro de 8 m vira dois trechos com traspasse", por[12.5]["emendas"] == 2 and any("emenda" in a for a in r["avisos"]), str(r["avisos"]))
ok("a barra usada ficou registrada no plano", r["parametros"]["barra_m"] == 6.0)
api("mudar_status_plano_corte", plano=r["plano"], status="Cancelado")
api("config_corte", barra_m=12)

print("[Peça sem lista de ferros]")
gravar("R0a", [peca("CP4", [])])
cod4 = next(p["codigo_peca"] for p in api("pecas_para_corte", obra=OBRA)["pecas"] if p["tag"] == "CP4")
r = api("gerar_plano_corte", obra=OBRA, pecas=json.dumps([cod4]))
ok("peça sem lista de ferros não gera plano e explica o motivo", not r.get("success") and "lista de ferros" in r.get("error", ""), r.get("error", "")[:90])
r = api("gerar_plano_corte", obra=OBRA)
ok("junto com outras, ela fica de fora com aviso", r.get("success") and any("sem lista de ferros" in a for a in r["avisos"]) and r["resumo"]["pecas"] == 3, str(r.get("avisos")))
plano = r["plano"]

print("[Revisão do projeto muda o ferro]")
F2 = [ferro(1, 10.0, 6, 3.0), ferro(2, 12.5, 2, 8.0), ferro(3, 6.3, 20, 0.5)]
rv = gravar("R0b", [peca("CP1", F2, aco=62.0), peca("CP2", F), peca("CP3", F)])
ok("a revisão registra a mudança", rv["success"] and rv["revisao"]["alteradas"] == 1, str(rv.get("revisao")))
ab = api("get_plano_corte", plano=plano)
ok("o plano que usa a lista antiga fica marcado como desatualizado", ab["desatualizado"] is True)
aviso = next(p for p in api("get_pieces", obra=OBRA)["pieces"] if p["tag"] == "CP1").get("aviso_engenharia") or ""
ok("a peça avisa que o plano de corte é de antes da revisão", "plano de corte" in aviso and "gere o plano de novo" in aviso, aviso[:160])

print("[Otimizador simples continua valendo]")
o = api("otimizar_corte_aco", comprimentos_necessarios=json.dumps([3, 4, 5, 6]))
ok("otimizar_corte_aco usa o mesmo empacotador", o["success"] and o["barras_necessarias"] == 2 and o["aproveitamento_pct"] == 75.0, str(o))

print("[Permissões e limpeza]")
ok("o plano exige sessão", requests.post(f"{URL}/api/method/frappe.precast_api.get_plano_corte", json={"plano": plano}).status_code in (401, 403))
api("delete_obra", codigo_obra=OBRA)
ok("excluir a obra apaga os planos", api("get_plano_corte", plano=plano).get("success") is False)
limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
