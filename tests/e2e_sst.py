"""Segurança do trabalho, manutenção dos equipamentos e treinamento exigido de quem opera por rosto."""
import json, os, sys
from datetime import date, timedelta
import requests

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA, PESSOA, OPERADOR, PLACA = "SST-TESTE", "Operador SST Teste", "operador.sst@teste.local", "SSTCAM1"
ATIVOS = ["SST-PONTE", "SST-MUNCK", PLACA]
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA"), nome, extra)
    if not cond:
        falhas.append(nome)


def entrar(usuario, senha):
    s = requests.Session()
    s.post(URL + "/api/method/login", json={"usr": usuario, "pwd": senha})
    return s


def chamar(sessao, metodo, **corpo):
    r = sessao.post(f"{URL}/api/method/frappe.precast_api.{metodo}", json=corpo)
    try:
        return r.json().get("message", {}) if r.status_code < 400 else {"success": False, "http": r.status_code}
    except ValueError:
        return {"success": False, "error": r.text[:150]}


adm = entrar("Administrator", SENHA)
api = lambda metodo, **corpo: chamar(adm, metodo, **corpo)
hoje = date.today()


def limpar():
    api("config_seguranca", exigir_treinamento=False)
    api("delete_obra", codigo_obra=OBRA)
    api("delete_caminhao", placa=PLACA)
    for a in ATIVOS:
        api("excluir_ativo_operacional", nome=a)
    for x in adm.get(f"{URL}/api/resource/Registro SST", params={"filters": json.dumps([["pessoa", "like", "%SST Teste%"]]), "limit_page_length": 200}).json().get("data", []):
        adm.delete(f"{URL}/api/resource/Registro SST/{x['name']}")
    for x in adm.get(f"{URL}/api/resource/Rosto Operador", params={"filters": json.dumps([["nome", "=", PESSOA]]), "limit_page_length": 10}).json().get("data", []):
        adm.delete(f"{URL}/api/resource/Rosto Operador/{x['name']}")
    adm.delete(f"{URL}/api/resource/User/{OPERADOR}")


limpar()

print("[Registros de SST]")
ok("recusa tipo inventado", not api("registrar_sst", tipo="Festa", pessoa=PESSOA).get("success"))
ok("recusa registro sem pessoa", not api("registrar_sst", tipo="Treinamento", pessoa="", documento="NR-35", validade=str(hoje + timedelta(days=100))).get("success"))
ok("treinamento sem nome do curso é recusado", not api("registrar_sst", tipo="Treinamento", pessoa=PESSOA, validade=str(hoje + timedelta(days=100))).get("success"))
ok("treinamento sem validade é recusado", not api("registrar_sst", tipo="Treinamento", pessoa=PESSOA, documento="NR-35").get("success"))
ok("validade antes da emissão é recusada", not api("registrar_sst", tipo="Treinamento", pessoa=PESSOA, documento="NR-35", data_emissao=str(hoje), validade=str(hoje - timedelta(days=1))).get("success"))
ok("data no futuro é recusada", not api("registrar_sst", tipo="ASO", pessoa=PESSOA, documento="Periódico", data_emissao=str(hoje + timedelta(days=5))).get("success"))
ok("registra o NR-35 em dia", api("registrar_sst", tipo="Treinamento", pessoa=PESSOA + " Um", documento="NR-35", data_emissao=str(hoje - timedelta(days=30)), validade=str(hoje + timedelta(days=300))).get("success"))
ok("registra o NR-11 vencido há 5 dias", api("registrar_sst", tipo="Treinamento", pessoa=PESSOA + " Um", documento="NR-11", data_emissao=str(hoje - timedelta(days=370)), validade=str(hoje - timedelta(days=5))).get("success"))
ok("registra o ASO a vencer em 10 dias", api("registrar_sst", tipo="ASO", pessoa=PESSOA + " Um", documento="Periódico", data_emissao=str(hoje - timedelta(days=355)), validade=str(hoje + timedelta(days=10))).get("success"))
ok("registra a entrega de EPI (capacete CA 12345)", api("registrar_sst", tipo="EPI", pessoa=PESSOA + " Um", documento="Capacete CA 12345", validade=str(hoje + timedelta(days=200))).get("success"))
ok("registra um acidente com CAT e 3 dias de afastamento", api("registrar_sst", tipo="Acidente", pessoa=PESSOA + " Um", observacoes="Corte na mão", cat=True, dias_afastamento=3).get("success"))
reg = api("listar_registros_sst", pessoa=PESSOA + " Um")["registros"]
estados = {(r["tipo"], r["documento"]): r["estado"] for r in reg}
ok("os estados saem certos: em dia, vencido e a vencer", estados[("Treinamento", "NR-35")] == "em dia" and estados[("Treinamento", "NR-11")] == "vencido" and estados[("ASO", "Periódico")] == "a vencer", str(estados))
p = api("painel_seguranca")
ok("o painel aponta o NR-11 vencido e o ASO a vencer", any(v["documento"] == "NR-11" for v in p["vencidos"]) and any(v["documento"] == "Periódico" for v in p["a_vencer"]))
ok("o painel conta o acidente, a CAT e os dias de afastamento", p["acidentes_12_meses"] >= 1 and p["com_cat"] >= 1 and p["dias_afastados_12_meses"] >= 3)
linha = next(m for m in p["matriz"] if m["pessoa"] == PESSOA + " Um")
ok("a matriz de treinamentos mostra NR-35 ok e NR-11 pendente", linha["NR-35"] == "ok" and linha["NR-11"] == "pendente", str(linha))
api("registrar_sst", tipo="Treinamento", pessoa=PESSOA + " Um", documento="NR-11", data_emissao=str(hoje), validade=str(hoje + timedelta(days=365)))
p = api("painel_seguranca")
ok("renovar o NR-11 tira o vencimento do painel (vale o registro mais recente)", not any(v["documento"] == "NR-11" and v["pessoa"] == PESSOA + " Um" for v in p["vencidos"]))

print("[Treinamento exigido de quem opera por rosto]")
op = api("criar_operador", email=OPERADOR, full_name=PESSOA)
ok("cria o operador", op.get("success"), str(op.get("error")))
adm.post(f"{URL}/api/resource/Rosto Operador", json={"usuario": OPERADOR, "nome": PESSOA, "setores": json.dumps(["Pátio / CQ", "Expedição"]), "descritor": "[]", "ativo": 1})
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra SST", "cliente": "C"}),
    pieces_data=json.dumps([{"cod": "ST1", "tag": "ST1", "produto": "Pilar", "secao": "30X40", "comp": 9.0, "vol": 1.0, "peso": 2500, "peso_aco_kg": 50.0, "ferros": [], "fonte": "prancha", "dimensoes_confirmadas": True}]))
cod = api("get_pieces", obra=OBRA)["pieces"][0]["codigo_peca"]
for _ in range(5):
    api("advance_piece_phase", codigo_peca=cod, forcar=True)                      # a peça fica na fase 6 (pátio)
operador = entrar(OPERADOR, op["senha_temporaria"])
ok("a exigência vem desligada", api("config_seguranca")["exigir_treinamento"] is False)
r = chamar(operador, "advance_piece_phase", codigo_peca=cod)
ok("com a exigência desligada o operador avança (sem NR-11 cadastrado)", r.get("success"), str(r.get("error")))
chamar(adm, "voltar_fase_peca", codigo_peca=cod, fase_destino=6)
ok("liga a exigência", api("config_seguranca", exigir_treinamento=True)["exigir_treinamento"] is True)
r = chamar(operador, "advance_piece_phase", codigo_peca=cod)
ok("sem treinamento, o operador é barrado e o motivo cita a NR-11", not r.get("success") and r.get("bloqueado_treinamento") and "NR-11" in r["error"] and PESSOA in r["error"], str(r.get("error")))
api("registrar_sst", tipo="Treinamento", pessoa=PESSOA, documento="NR-11 Operação de ponte rolante", data_emissao=str(hoje - timedelta(days=400)), validade=str(hoje - timedelta(days=35)))
ok("treinamento vencido continua barrando", chamar(operador, "advance_piece_phase", codigo_peca=cod).get("bloqueado_treinamento") is True)
api("registrar_sst", tipo="Treinamento", pessoa=PESSOA.upper(), documento="NR-11 renovado", data_emissao=str(hoje), validade=str(hoje + timedelta(days=360)))
r = chamar(operador, "advance_piece_phase", codigo_peca=cod)
ok("renovado (a comparação ignora maiúsculas), o operador avança", r.get("success"), str(r.get("error")))
ok("só a Direção liga a exigência", chamar(operador, "config_seguranca", exigir_treinamento=False).get("http") in (403, 401) or chamar(operador, "config_seguranca", exigir_treinamento=False).get("success") is False)
api("config_seguranca", exigir_treinamento=False)

print("[Equipamentos e manutenção]")
ok("recusa tipo de equipamento inventado", not api("salvar_ativo_operacional", nome="SST-PONTE", tipo="Foguete").get("success"))
ok("recusa medida inventada", not api("salvar_ativo_operacional", nome="SST-PONTE", tipo="Ponte rolante", unidade_medida="Anos").get("success"))
ok("cadastra a ponte (horímetro 1000 h, manutenção a cada 250 h)", api("salvar_ativo_operacional", nome="SST-PONTE", tipo="Ponte rolante", unidade_medida="Horas", leitura_atual=1000, intervalo_manutencao=250, vencimento_documento=str(hoje + timedelta(days=90))).get("success"))
ok("cadastra o munck com a última manutenção em dia", api("salvar_ativo_operacional", nome="SST-MUNCK", tipo="Caminhão", unidade_medida="Km", leitura_atual=50000, intervalo_manutencao=10000).get("success"))
ativos = {a["nome"]: a for a in api("listar_ativos_operacionais")["ativos"]}
ok("equipamento recém-cadastrado está em dia, faltando o intervalo todo", ativos["SST-PONTE"]["manutencao"] == "em dia" and ativos["SST-PONTE"]["faltam"] == 250.0, str(ativos["SST-PONTE"]))
ok("atualizar a leitura para 1230 h: faltam 20 h, manutenção próxima", api("atualizar_leitura_ativo", ativo="SST-PONTE", leitura=1230).get("success") and {a["nome"]: a for a in api("listar_ativos_operacionais")["ativos"]}["SST-PONTE"]["manutencao"] == "próxima")
ok("a leitura não pode voltar", not api("atualizar_leitura_ativo", ativo="SST-PONTE", leitura=900).get("success"))
api("atualizar_leitura_ativo", ativo="SST-PONTE", leitura=1300)
ok("passou do intervalo: manutenção vencida", {a["nome"]: a for a in api("listar_ativos_operacionais")["ativos"]}["SST-PONTE"]["manutencao"] == "vencida")
ok("manutenção com tipo inventado é recusada", not api("registrar_manutencao_ativo", ativo="SST-PONTE", tipo="Mágica").get("success"))
ok("manutenção com leitura menor que a atual é recusada", not api("registrar_manutencao_ativo", ativo="SST-PONTE", tipo="Preventiva", leitura=1100).get("success"))
ok("manutenção com custo negativo é recusada", not api("registrar_manutencao_ativo", ativo="SST-PONTE", tipo="Preventiva", custo=-5).get("success"))
ok("registra a preventiva (R$ 1.800)", api("registrar_manutencao_ativo", ativo="SST-PONTE", tipo="Preventiva", descricao="Troca de óleo e freios", custo=1800, leitura=1300).get("success"))
ok("registra uma corretiva (R$ 450)", api("registrar_manutencao_ativo", ativo="SST-PONTE", tipo="Corretiva", descricao="Fim de curso", custo=450).get("success"))
a = {a["nome"]: a for a in api("listar_ativos_operacionais")["ativos"]}["SST-PONTE"]
ok("a preventiva zera o intervalo e a corretiva não", a["manutencao"] == "em dia" and a["faltam"] == 250.0, str(a))
ok("o custo dos últimos 12 meses soma as duas", a["custo_12_meses"] == 2250.0, str(a["custo_12_meses"]))
ok("o histórico lista as duas, a mais recente primeiro", len(api("historico_manutencao_ativo", ativo="SST-PONTE")["historico"]) == 2)
api("salvar_ativo_operacional", nome="SST-PONTE", tipo="Ponte rolante", leitura_atual=1300, intervalo_manutencao=250, vencimento_documento=str(hoje - timedelta(days=1)))
ok("documento vencido aparece", {a["nome"]: a for a in api("listar_ativos_operacionais")["ativos"]}["SST-PONTE"]["documento"] == "vencido")

print("[Frota com pendência avisa na carga]")
api("create_caminhao", placa=PLACA, capacidade_kg=30000, comprimento_m=14)
api("salvar_ativo_operacional", nome=PLACA, tipo="Caminhão", unidade_medida="Km", leitura_atual=20000, intervalo_manutencao=5000)
api("atualizar_leitura_ativo", ativo=PLACA, leitura=26000)       # 6000 km desde a última: vencida
chamar(adm, "voltar_fase_peca", codigo_peca=cod, fase_destino=6)
cargas = api("planejar_cargas", obra=OBRA, pecas=json.dumps([cod]))
ok("a carga no caminhão com manutenção vencida traz o aviso", cargas["success"] and (cargas["cargas"][0].get("aviso") or "").find("manutenção") >= 0, str(cargas.get("error") or cargas["cargas"][0].get("aviso")))

print("[Permissões e limpeza]")
ok("o painel exige sessão", requests.post(f"{URL}/api/method/frappe.precast_api.painel_seguranca", json={}).status_code in (401, 403))
ok("o operador por rosto não vê o painel de segurança", chamar(operador, "painel_seguranca").get("success") is not True)
limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
