"""Logística e montagem: ordem de montagem, carga dos caminhões, içamento com guindaste e cronograma planejado x montado."""
import json, os, sys
from datetime import date, timedelta
import requests

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA, CAMINHOES, EQUIP = "MONT-TESTE", ["TST1A11", "TST2B22"], "GUINDASTE-TESTE"
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


def limpar():
    for r in api("get_romaneios").get("romaneios", []):
        if r["obra"] == OBRA:
            api("delete_romaneio", codigo=r["codigo"])
    api("delete_obra", codigo_obra=OBRA)
    for c in CAMINHOES:
        api("delete_caminhao", placa=c)
    api("excluir_equipamento_icamento", nome=EQUIP)


def peca(cod, produto, comp, peso):
    return {"cod": cod, "tag": cod, "produto": produto, "secao": "30X40", "comp": comp, "vol": round(peso / 2500, 3), "peso": peso,
            "peso_aco_kg": 50.0, "ferros": [], "fonte": "prancha", "dimensoes_confirmadas": True}


def sequencia():
    return {p["tag"]: p.get("sequencia_montagem") for p in api("get_pieces", obra=OBRA)["pieces"]}


limpar()
api("create_caminhao", placa=CAMINHOES[0], capacidade_kg=15000, comprimento_m=12)
api("create_caminhao", placa=CAMINHOES[1], capacidade_kg=30000, comprimento_m=14)
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Montagem", "cliente": "C"}),
    pieces_data=json.dumps([peca("MF1", "BLOCO", 3.0, 2000), peca("MP1", "PILAR", 9.0, 6000), peca("MP2", "PILAR", 9.0, 6000), peca("MP3", "PILAR", 10.0, 8000),
                            peca("MV1", "VIGA", 12.0, 5000), peca("MV2", "VIGA", 12.0, 5000), peca("MA1", "PAINEL", 6.0, 3000), peca("MG", "PILAR", 40.0, 60000)]))
pecas = {p["tag"]: p["codigo_peca"] for p in api("get_pieces", obra=OBRA)["pieces"]}
ok("o caminhão guarda o comprimento da carroceria", {c["placa"]: c["comprimento_m"] for c in api("get_caminhoes")["caminhoes"]}.get(CAMINHOES[1]) == 14.0)

print("[Ordem de montagem]")
r = api("definir_sequencia_montagem", obra=OBRA, pecas=json.dumps([pecas["MV2"], pecas["MV1"]]))
seq = sequencia()
ok("a ordem escolhida vai na frente e o resto segue fundação, pilar, viga, painel", r["success"] and seq["MV2"] == 1 and seq["MV1"] == 2 and seq["MF1"] == 3 and seq["MA1"] == 8, str(seq))
ok("recusa peça de outra obra", not api("definir_sequencia_montagem", obra=OBRA, pecas=json.dumps(["NAO-EXISTE"])).get("success"))
api("definir_sequencia_montagem", obra=OBRA)    # volta à ordem padrão
seq = sequencia()
ok("a ordem padrão põe a fundação primeiro e os pilares antes das vigas", seq["MF1"] == 1 and seq["MP1"] < seq["MV1"] < seq["MA1"], str(seq))
for t in pecas:
    for _ in range(5):
        api("advance_piece_phase", codigo_peca=pecas[t], forcar=True)

print("[Planejar as cargas]")
r = api("planejar_cargas", obra=OBRA)
ok("planeja", r["success"], str(r.get("error")))
c1, c2 = r["cargas"][0], r["cargas"][1]
ok("duas viagens, na ordem de montagem", len(r["cargas"]) == 2 and [p["tag"] for p in c1["pecas"]] == ["MF1", "MP1", "MP2", "MP3", "MV1"] and [p["tag"] for p in c2["pecas"]] == ["MV2", "MA1"],
   str([[p["tag"] for p in c["pecas"]] for c in r["cargas"]]))
ok("27 t vão no caminhão de 30 t (90%) e 8 t no de 15 t", (c1["caminhao"], c1["peso_kg"], c1["utilizacao_pct"]) == (CAMINHOES[1], 27000.0, 90.0) and c2["caminhao"] == CAMINHOES[0],
   str((c1["caminhao"], c2["caminhao"], c2["utilizacao_pct"])))
ok("carrega na ordem inversa da montagem (a primeira a montar entra por último)", c1["ordem_carregamento"] == [pecas[t] for t in ("MV1", "MP3", "MP2", "MP1", "MF1")])
ok("a peça de 60 t não entra em nenhum caminhão e o motivo aparece", [n["tag"] for n in r["nao_atendidas"]] == ["MG"] and "Pesa" in r["nao_atendidas"][0]["motivo"], str(r["nao_atendidas"]))
ok("o resumo soma viagens, peças e peso", r["resumo"] == {"viagens": 2, "pecas": 7, "peso_kg": 35000.0}, str(r["resumo"]))
r2 = api("planejar_cargas", obra=OBRA, pecas=json.dumps([pecas["MV1"]]), balanco_m=0)
ok("planejar só algumas peças", r2["success"] and r2["resumo"]["pecas"] == 1)
ok("recusa obra que não existe", not api("planejar_cargas", obra="NAO-EXISTE-X").get("success"))

print("[Criar os romaneios]")
amanha = date.today() + timedelta(days=1)
ap = api("aplicar_plano_cargas", obra=OBRA, data_expedicao=str(amanha), cargas=json.dumps(r["cargas"]))
ok("cria um romaneio por viagem", ap["success"] and len(ap["romaneios"]) == 2 and not ap["falhas"], str(ap))
roms = {x["codigo"]: x for x in api("get_romaneios")["romaneios"]}
r1 = roms[ap["romaneios"][0]["romaneio"]]
ok("o romaneio guarda a ordem de carregamento", json.loads(r1["ordem_carga"]) == c1["ordem_carregamento"] and len(r1["pecas"]) == 5)
depois = api("planejar_cargas", obra=OBRA)
ok("depois de romaneadas, só sobra a peça que não cabe", [n["tag"] for n in depois["nao_atendidas"]] == ["MG"] and depois["cargas"] == [], str(depois.get("error")))

print("[Içamento]")
tabela = [{"raio_m": 20, "capacidade_kg": 8000}, {"raio_m": 8, "capacidade_kg": 40000}, {"raio_m": 12, "capacidade_kg": 25000}, {"raio_m": 16, "capacidade_kg": 14000}]
ok("cadastra o guindaste com tabela de carga", api("salvar_equipamento_icamento", nome=EQUIP, tipo="Guindaste", capacidade_max_kg=60000, tabela_carga=json.dumps(tabela), fator_seguranca=1.25).get("success"))
ok("recusa equipamento sem nome", not api("salvar_equipamento_icamento", nome="", capacidade_max_kg=1000).get("success"))
ok("recusa capacidade zero", not api("salvar_equipamento_icamento", nome="X-ZERO", capacidade_max_kg=0).get("success"))
ok("recusa tabela com linha inválida", not api("salvar_equipamento_icamento", nome="X-TAB", capacidade_max_kg=1000, tabela_carga=json.dumps([{"raio_m": 5}])).get("success"))
ok("recusa fator de segurança absurdo", not api("salvar_equipamento_icamento", nome="X-FAT", capacidade_max_kg=1000, fator_seguranca=9).get("success"))
ok("lista o equipamento com a tabela ordenada por raio", [l["raio_m"] for l in next(e for e in api("listar_equipamentos_icamento")["equipamentos"] if e["nome"] == EQUIP)["tabela_carga"]] == [8.0, 12.0, 16.0, 20.0])
p = api("plano_icamento", obra=OBRA, equipamento=EQUIP, raio_m=12)
est = {l["tag"]: l for l in p["pecas"]}
ok("no raio de 12 m a capacidade é 25 t", p["capacidade_no_raio_kg"] == 25000.0)
ok("a peça de 8 t (10 t com o fator) usa 40% e fica ok", est["MP3"]["utilizacao_pct"] == 40.0 and est["MP3"]["estado"] == "ok", str(est["MP3"]))
ok("a peça de 60 t não pode ser içada nesse raio", est["MG"]["estado"] == "nao")
ok("o alcance máximo da peça de 8 t (10 t com o fator) é 16 m, onde o guindaste ainda levanta 14 t", est["MP3"]["raio_maximo_m"] == 16.0, str(est["MP3"]["raio_maximo_m"]))
p = api("plano_icamento", obra=OBRA, equipamento=EQUIP, raio_m=20)
est = {l["tag"]: l for l in p["pecas"]}
ok("a 20 m (8 t no guindaste) a peça de 6 t fica em atenção e a de 8 t não passa", est["MP1"]["estado"] == "atencao" and est["MP3"]["estado"] == "nao" and est["MV1"]["estado"] == "ok",
   str({k: (v["utilizacao_pct"], v["estado"]) for k, v in est.items()}))
ok("o resumo conta ok, atenção e não", sum(p["resumo"].values()) == 8)
p = api("plano_icamento", obra=OBRA, equipamento=EQUIP, raio_m=25)
ok("raio além da tabela: tudo barrado e o aviso explica", all(l["estado"] == "nao" for l in p["pecas"]) and any("alcance" in a for a in p["avisos"]))
ok("recusa raio zero", not api("plano_icamento", obra=OBRA, equipamento=EQUIP, raio_m=0).get("success"))
ok("recusa equipamento inexistente", not api("plano_icamento", obra=OBRA, equipamento="NAO-EXISTE", raio_m=10).get("success"))

print("[Cronograma planejado x montado]")
ok("sem datas e sem ritmo, o cronograma explica o que falta", "datas de montagem" in api("cronograma_montagem", obra=OBRA).get("error", ""))
ok("recusa ritmo que não é número", not api("cronograma_montagem", obra=OBRA, data_inicio=str(date.today()), pecas_por_dia="abc").get("success"))
segunda = date.today() - timedelta(days=14)
while segunda.weekday() != 0:
    segunda -= timedelta(days=1)
c = api("cronograma_montagem", obra=OBRA, data_inicio=str(segunda), pecas_por_dia=2, aplicar=True)
ok("8 peças a 2 por dia terminam na quinta (4 dias úteis)", c["success"] and c["resumo"]["termino_planejado"] == str(segunda + timedelta(days=3)), str(c.get("resumo")))
ok("a série começa na data de início e planeja as 8 no fim", c["serie"][0]["data"] == str(segunda) and c["serie"][0]["planejado"] == 2 and c["serie"][-1]["planejado"] == 8)
ok("nada montado ainda: 8 atrasadas", c["resumo"]["montadas"] == 0 and len(c["atrasadas"]) == 8 and c["atrasadas"][0]["dias_atraso"] > 0)
for t in ("MF1", "MP1", "MP2"):
    for _ in range(2):
        api("advance_piece_phase", codigo_peca=pecas[t], forcar=True)   # romaneada na fase 6 -> 7 -> 8
c = api("cronograma_montagem", obra=OBRA)
ok("usa as datas gravadas, sem novo cálculo", c["success"] and c["resumo"]["planejadas_ate_hoje"] == 8)
ok("3 montadas: desvio de -5 e 5 atrasadas", c["resumo"]["montadas"] == 3 and c["resumo"]["desvio"] == -5 and len(c["atrasadas"]) == 5, str(c["resumo"]))
ok("a curva realizada termina em 3 hoje", [x for x in c["serie"] if x["realizado"] is not None][-1]["realizado"] == 3)
ok("há previsão de término pelo ritmo real", c["resumo"]["termino_previsto"] and c["resumo"]["termino_previsto"] >= str(date.today()), str(c["resumo"]["termino_previsto"]))

print("[Permissões e limpeza]")
ok("o plano de cargas exige sessão", requests.post(f"{URL}/api/method/frappe.precast_api.planejar_cargas", json={"obra": OBRA}).status_code in (401, 403))
limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
