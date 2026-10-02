"""Pátio e formas: capacidade, ciclo de cura, programação sugerida, giros e liberação da desforma pelo lote de concreto."""
import json, os, sys
from datetime import date, timedelta
import requests

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA = "PATIO-TESTE"
FORMAS = ["PT-PISTA", "PT-FORMA", "PT-MESA", "PT-MANUT"]
LOTE = "LT-PATIO-01"
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
    api("config_patio", desforma_pct_fck=70, trabalha_sabado=True)
    for p in api("get_pieces", obra=OBRA).get("pieces", []):
        api("unprogram_piece", codigo_peca=p["codigo_peca"])
    api("delete_obra", codigo_obra=OBRA)
    for f in FORMAS:
        api("delete_forma_pista", codigo=f)
    for x in s.get(f"{URL}/api/resource/Corpo Prova", params={"filters": json.dumps([["lote", "=", LOTE]])}).json().get("data", []):
        s.delete(f"{URL}/api/resource/Corpo Prova/{x['name']}")
    s.delete(f"{URL}/api/resource/Lote Concreto/{LOTE}")


def proxima(dia_semana_pos):
    """Próxima data (a partir de amanhã) que cai numa segunda-feira, para os testes não dependerem do dia em que rodam."""
    d = date.today() + timedelta(days=1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d + timedelta(days=dia_semana_pos)


def peca(cod, comp, peso):
    return {"cod": cod, "tag": cod, "produto": "Viga", "secao": "30X40", "comp": comp, "vol": round(peso / 2500, 3), "peso": peso,
            "peso_aco_kg": 50.0, "ferros": [], "fonte": "prancha", "dimensoes_confirmadas": True, "fck": "30 MPa"}


limpar()
api("create_forma_pista", codigo="PT-PISTA", tipo="Pista de Protensão", comprimento_m=20, largura_m=1.2, capacidade_kg=20000)
api("create_forma_pista", codigo="PT-FORMA", tipo="Fôrma", comprimento_m=10, largura_m=1.0, capacidade_kg=8000)
api("create_forma_pista", codigo="PT-MESA", tipo="Mesa Vibratória", comprimento_m=6, largura_m=3, capacidade_kg=5000)
api("create_forma_pista", codigo="PT-MANUT", tipo="Fôrma", comprimento_m=30, largura_m=3, capacidade_kg=50000)
s.put(f"{URL}/api/resource/Forma Pista/PT-MANUT", json={"status": "Manutenção"})
api("configurar_forma_pista", codigo="PT-FORMA", ciclo_dias=2)
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Pátio", "cliente": "C", "fck": "30 MPa"}),
    pieces_data=json.dumps([peca("PA", 8.0, 3000), peca("PB", 8.0, 3000), peca("PC", 12.0, 6000), peca("PD", 9.0, 3500), peca("PE", 3.0, 1000), peca("PF", 25.0, 9000)]))
cod = {p["tag"]: p["codigo_peca"] for p in api("get_pieces", obra=OBRA)["pieces"]}
seg = proxima(0)

print("[Regras de capacidade]")
ok("o ciclo da forma fica registrado", next(f for f in api("get_formas_pistas")["formas_pistas"] if f["codigo"] == "PT-FORMA")["ciclo_dias"] == 2)
ok("recusa ciclo impossível", not api("configurar_forma_pista", codigo="PT-FORMA", ciclo_dias=99).get("success"))
r = api("program_piece", codigo_peca=cod["PF"], forma_pista="PT-PISTA", data_programada=str(seg))
ok("peça de 25 m não cabe na pista de 20 m", not r.get("success") and "não cabe" in r["error"], r.get("error", "")[:90])
r = api("program_piece", codigo_peca=cod["PA"], forma_pista="PT-MANUT", data_programada=str(seg))
ok("forma em manutenção não recebe peça", not r.get("success") and "manutenção" in r["error"], r.get("error", "")[:90])
r = api("program_piece", codigo_peca=cod["PC"], forma_pista="PT-FORMA", data_programada=str(seg))
ok("peça de 12 m não cabe na fôrma de 10 m", not r.get("success") and "não cabe" in r["error"], r.get("error", "")[:90])
ok("peça de 6000 kg passa da capacidade da mesa (5000 kg)", not api("program_piece", codigo_peca=cod["PC"], forma_pista="PT-MESA", data_programada=str(seg)).get("success"))

print("[Pista: soma dos comprimentos]")
ok("PA (8 m) entra na pista", api("program_piece", codigo_peca=cod["PA"], forma_pista="PT-PISTA", data_programada=str(seg)).get("success"))
ok("PB (8 m) entra na mesma pista no mesmo dia (16 de 20 m)", api("program_piece", codigo_peca=cod["PB"], forma_pista="PT-PISTA", data_programada=str(seg)).get("success"))
r = api("program_piece", codigo_peca=cod["PC"], forma_pista="PT-PISTA", data_programada=str(seg))
ok("PC (12 m) estoura a pista (28 de 20 m) e o motivo cita a ocupação", not r.get("success") and "ocupada" in r["error"] and r.get("conflito"), r.get("error", "")[:110])
ok("com 'forçar', a ocupação passa (decisão do responsável)", api("program_piece", codigo_peca=cod["PC"], forma_pista="PT-PISTA", data_programada=str(seg), forcar=True).get("success"))
api("unprogram_piece", codigo_peca=cod["PC"])

print("[Fôrma: uma peça por ciclo de 2 dias]")
ok("PD entra na fôrma na segunda", api("program_piece", codigo_peca=cod["PD"], forma_pista="PT-FORMA", data_programada=str(seg)).get("success"))
r = api("program_piece", codigo_peca=cod["PE"], forma_pista="PT-FORMA", data_programada=str(seg + timedelta(days=1)))
ok("na terça a fôrma ainda está em cura", not r.get("success") and "ocupada" in r["error"], r.get("error", "")[:100])
ok("na quarta a fôrma está livre de novo", api("program_piece", codigo_peca=cod["PE"], forma_pista="PT-FORMA", data_programada=str(seg + timedelta(days=2))).get("success"))
ok("reprogramar a própria peça no mesmo dia não conflita consigo mesma", api("program_piece", codigo_peca=cod["PD"], forma_pista="PT-FORMA", data_programada=str(seg)).get("success"))

print("[Visão do pátio]")
v = api("visao_patio", data_inicio=str(seg), dias=7)
f = {x["codigo"]: x for x in v["formas"]}
ok("a pista aparece com 80% (16 de 20 m) na segunda", f["PT-PISTA"]["dias"][0]["carga_pct"] == 80 and set(f["PT-PISTA"]["dias"][0]["pecas"]) == {"PA", "PB"}, str(f["PT-PISTA"]["dias"][0]))
ok("a fôrma aparece ocupada na segunda e terça, e de novo na quarta", [d["carga_pct"] for d in f["PT-FORMA"]["dias"][:4]] == [100, 100, 100, 100], str([d["carga_pct"] for d in f["PT-FORMA"]["dias"][:4]]))
ok("a forma em manutenção é apontada", "PT-MANUT" in v["manutencao"])
ok("conta as peças sem forma", v["sem_forma"] >= 2)
api("program_piece", codigo_peca=cod["PA"], forma_pista="PT-PISTA", data_programada=str(date.today() - timedelta(days=3)))
v = api("visao_patio")
ok("peça programada no passado e ainda sem concretar aparece como atrasada", any(a["tag"] == "PA" for a in v["atrasadas"]))
api("program_piece", codigo_peca=cod["PA"], forma_pista="PT-PISTA", data_programada=str(seg))

print("[Programação sugerida]")
r = api("sugerir_programacao", obra=OBRA, data_inicio=str(seg))
ok("sugere para as peças sem forma (PC e PF)", r["success"] and {x["tag"] for x in r["sugestoes"]} | {x["tag"] for x in r["sem_lugar"]} == {"PC", "PF"}, str(r))
sug = {x["tag"]: x for x in r["sugestoes"]}
ok("PC (12 m, 6000 kg) vai para a pista, a única onde cabe", sug.get("PC", {}).get("forma") == "PT-PISTA", str(sug.get("PC")))
ok("PC não cai no mesmo dia que lotaria a pista (já tem PA e PB)", sug["PC"]["data"] != str(seg), str(sug.get("PC")))
ok("PF (25 m) não cabe em nenhuma forma e o motivo aparece", [x["tag"] for x in r["sem_lugar"]] == ["PF"] and "não cabe" in r["sem_lugar"][0]["motivo"], str(r["sem_lugar"]))
ok("a data sugerida não cai em domingo", all(date.fromisoformat(x["data"]).weekday() != 6 for x in r["sugestoes"]))
api("config_patio", trabalha_sabado=False)
r2 = api("sugerir_programacao", obra=OBRA, data_inicio=str(seg + timedelta(days=5)))   # sábado
ok("sem trabalho aos sábados, a sugestão pula para segunda", all(date.fromisoformat(x["data"]).weekday() == 0 for x in r2["sugestoes"]), str(r2["sugestoes"]))
api("config_patio", trabalha_sabado=True)
ok("sugerir não grava nada", api("get_pieces", obra=OBRA)["pieces"] and next(p for p in api("get_pieces", obra=OBRA)["pieces"] if p["tag"] == "PC").get("forma_pista") in (None, ""))
ap = api("aplicar_programacao", sugestoes=json.dumps(r["sugestoes"]))
ok("aplicar programa as peças sugeridas", ap["success"] and ap["programadas"] == len(r["sugestoes"]) and not ap["falhas"], str(ap))
ok("depois de aplicada, só sobra a que não cabe", [x["tag"] for x in api("sugerir_programacao", obra=OBRA, data_inicio=str(seg))["sem_lugar"]] == ["PF"])

print("[Giros e liberação da forma]")
pa = cod["PA"]
giros0 = next(f for f in api("get_formas_pistas")["formas_pistas"] if f["codigo"] == "PT-PISTA")["giros_realizados"]
for _ in range(4):
    api("advance_piece_phase", codigo_peca=pa, forcar=True)          # fase 5 (desmoldada) com forçar
ok("a peça desmoldada soma um giro na pista", next(f for f in api("get_formas_pistas")["formas_pistas"] if f["codigo"] == "PT-PISTA")["giros_realizados"] == giros0 + 1)
ok("a pista continua ocupada enquanto tem outras peças", next(f for f in api("get_formas_pistas")["formas_pistas"] if f["codigo"] == "PT-PISTA")["status"] == "Ocupada")
r = api("program_piece", codigo_peca=pa, forma_pista="PT-PISTA", data_programada=str(seg + timedelta(days=9)))
ok("peça já desmoldada não é programada de novo", not r.get("success"))

print("[Desforma pela resistência do lote]")
api("registrar_lote_concreto", codigo=LOTE, fck_especificado=30)
pb = cod["PB"]
api("vincular_lote_pecas", lote=LOTE, pecas=json.dumps([pb]))
for _ in range(3):
    api("advance_piece_phase", codigo_peca=pb, forcar=True)           # fase 4 (concretada)
r = api("advance_piece_phase", codigo_peca=pb)
ok("sem ruptura, a desforma é barrada e explica o mínimo (70% de 30 = 21 MPa)", not r.get("success") and r.get("bloqueado_fck") and "21 MPa" in r["error"], r.get("error", "")[:160])
api("registrar_corpo_prova", lote=LOTE, idade_dias=2, fck_obtido=15)
ok("2 dias com 15 MPa ainda não libera", not api("advance_piece_phase", codigo_peca=pb).get("success"))
api("registrar_corpo_prova", lote=LOTE, idade_dias=3, fck_obtido=22)
v = api("visao_patio")
d = next(x for x in v["desformas"] if x["tag"] == "PB")
ok("a visão mostra a peça concretada com a resistência liberada", d["resistencia_liberada"] and d["concretada_em"], str(d))
r = api("advance_piece_phase", codigo_peca=pb)
ok("3 dias com 22 MPa (≥ 21) libera a desforma sem forçar", r.get("success") and r["fase_numero"] == 5, str(r)[:140])
ok("recusa porcentagem fora da faixa", not api("config_patio", desforma_pct_fck=10).get("success"))

print("[Permissões]")
ok("a visão exige sessão", requests.post(f"{URL}/api/method/frappe.precast_api.visao_patio", json={}).status_code in (401, 403))
limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
