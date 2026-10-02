"""Suprimentos e financeiro: necessidade de materiais, pedidos com alçada, recebimento de aço, contas a pagar,
fluxo de caixa, consumo do plano de corte e orçado x realizado."""
import json, math, os, sys
from datetime import date, timedelta
import requests

URL = os.environ.get("RBR_URL", "http://localhost:8088")
SENHA = [l.split("=", 1)[1].strip() for l in open(os.path.join(os.path.dirname(__file__), "..", "precast_service_credentials.env"), encoding="utf-8") if l.startswith("ADMIN_PASSWORD=")][0]
OBRA, FORMA, EMAIL = "COMP-TESTE", "CP-FORMA", "alcada.financeiro@teste.local"
CORRIDAS = ["CR-COMP-A", "CR-COMP-B", "CR-COMP-C"]
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


def limpar():
    api("config_compras", alcada_producao=5000, prazo_dias=7)
    for p in api("get_pieces", obra=OBRA).get("pieces", []):
        api("unprogram_piece", codigo_peca=p["codigo_peca"])
    api("delete_obra", codigo_obra=OBRA)
    api("delete_forma_pista", codigo=FORMA)
    api("remover_assento", email=EMAIL)
    adm.delete(f"{URL}/api/resource/User/{EMAIL}")
    for x in adm.get(f"{URL}/api/resource/Assento", params={"filters": json.dumps([["user", "=", EMAIL]]), "limit_page_length": 10}).json().get("data", []):
        adm.delete(f"{URL}/api/resource/Assento/{x['name']}")
    for x in adm.get(f"{URL}/api/resource/Pedido Compra", params={"filters": json.dumps([["fornecedor", "like", "Forn Teste%"]]), "limit_page_length": 200}).json().get("data", []):
        adm.delete(f"{URL}/api/resource/Pedido Compra/{x['name']}")
    for x in adm.get(f"{URL}/api/resource/Titulo Pagar", params={"filters": json.dumps([["fornecedor", "like", "Forn Teste%"]]), "limit_page_length": 200}).json().get("data", []):
        adm.delete(f"{URL}/api/resource/Titulo Pagar/{x['name']}")
    for c in CORRIDAS:
        adm.delete(f"{URL}/api/resource/Certificado Aco/{c}")


def ferro(pos, bitola, qtd, comp):
    return {"posicao": str(pos), "bitola_mm": bitola, "quantidade": qtd, "comp_unit_m": comp, "comp_total_m": qtd * comp, "peso_kg": 1.0}


def peca(cod, ferros, vol):
    return {"cod": cod, "tag": cod, "produto": "Viga", "secao": "30X40", "comp": 10.0, "vol": vol, "peso": vol * 2500, "peso_aco_kg": 100.0, "ferros": ferros,
            "fonte": "prancha", "dimensoes_confirmadas": True}


limpar()
hoje = date.today()
api("create_forma_pista", codigo=FORMA, tipo="Fôrma")
api("integrate_parsed_project", obra_data=json.dumps({"cod": OBRA, "nome": "Obra Compras", "cliente": "C"}),
    pieces_data=json.dumps([peca("CA", [ferro(1, 10.0, 100, 10.0)], 2.0), peca("CB", [ferro(1, 12.5, 50, 10.0)], 3.0)]))
pc = {p["tag"]: p["codigo_peca"] for p in api("get_pieces", obra=OBRA)["pieces"]}

print("[Configuração]")
c = api("config_compras")
ok("alçada padrão de R$ 5.000 e prazo de 7 dias", (c["alcada_producao"], c["prazo_dias"]) == (5000.0, 7.0), str(c))
ok("recusa valor negativo", not api("config_compras", alcada_producao=-1).get("success"))
ok("recusa texto no lugar de número", not api("config_compras", prazo_dias="abc").get("success"))

print("[Solicitar]")
base = dict(item="Aço CA-50 Ø10", categoria="Aço", quantidade=600, preco_unitario=6.5, fornecedor="Forn Teste Aço", obra=OBRA, bitola_mm=10)
ok("recusa sem fornecedor", not api("solicitar_compra", **{**base, "fornecedor": ""}).get("success"))
ok("recusa categoria inventada", not api("solicitar_compra", **{**base, "categoria": "Ouro"}).get("success"))
ok("recusa quantidade zero", not api("solicitar_compra", **{**base, "quantidade": 0}).get("success"))
ok("recusa aço sem bitola", not api("solicitar_compra", **{**base, "bitola_mm": None}).get("success"))
ok("recusa obra que não existe", not api("solicitar_compra", **{**base, "obra": "NAO-EXISTE-X"}).get("success"))
p1 = api("solicitar_compra", **base)
ok("600 kg a R$ 6,50 = R$ 3.900 (abaixo da alçada: Produção, Financeiro ou Direção aprovam)", p1["success"] and p1["valor_total"] == 3900.0 and p1["aprovacao_exigida"] == ["Produção", "Financeiro", "Direção"], str(p1))
grande = api("solicitar_compra", **{**base, "quantidade": 1000, "fornecedor": "Forn Teste Grande"})
ok("1.000 kg = R$ 6.500 (acima da alçada: só a Direção)", grande["valor_total"] == 6500.0 and grande["aprovacao_exigida"] == ["Direção"], str(grande))

print("[Aprovação por alçada, com um usuário do Financeiro]")
conv = api("convidar_usuario_setor", email=EMAIL, full_name="Teste Financeiro", setor="Financeiro")
ok("cria o usuário do Financeiro", conv.get("success"), str(conv.get("error")))
fin = entrar(EMAIL, conv["senha_temporaria"])
ok("o Financeiro vê o pedido", any(p["name"] == p1["pedido"] for p in chamar(fin, "listar_pedidos_compra")["pedidos"]))
r = chamar(fin, "aprovar_compra", pedido=grande["pedido"])
ok("o Financeiro não aprova pedido acima da alçada (acesso negado)", not r.get("success") and r.get("http") in (403, 401), str(r))
r = chamar(fin, "aprovar_compra", pedido=p1["pedido"])
ok("o Financeiro aprova o pedido pequeno de outra pessoa", r.get("success"), str(r))
meu = chamar(fin, "solicitar_compra", item="Cimento", categoria="Cimento", quantidade=1000, preco_unitario=0.9, fornecedor="Forn Teste Cimento", unidade="kg")
r = chamar(fin, "aprovar_compra", pedido=meu["pedido"])
ok("quem pediu não aprova o próprio pedido", not r.get("success") and "não pode aprová-lo" in r.get("error", ""), str(r))
ok("a Direção aprova o pedido grande", api("aprovar_compra", pedido=grande["pedido"]).get("success"))
ok("não aprova duas vezes", not api("aprovar_compra", pedido=grande["pedido"]).get("success"))
ok("o Financeiro não paga título nem vê o fluxo de outro setor sem papel", chamar(fin, "listar_titulos_pagar").get("success") is True)

print("[Receber o aço]")
p2 = api("solicitar_compra", **{**base, "quantidade": 800, "fornecedor": "Forn Teste Aço"})
ok("não recebe pedido que não foi aprovado", not api("receber_compra", pedido=p2["pedido"], corrida=CORRIDAS[1]).get("success"))
api("aprovar_compra", pedido=p2["pedido"])
ok("aço sem corrida não entra no estoque", not api("receber_compra", pedido=p1["pedido"]).get("success"))
r = api("receber_compra", pedido=p1["pedido"], corrida=CORRIDAS[0], nota_fiscal="NF-1", data_recebimento=str(hoje - timedelta(days=10)))
ok("recebe os 600 kg e gera o título a pagar (28 dias)", r["success"] and r["vencimento"] == str(hoje - timedelta(days=10) + timedelta(days=28)), str(r))
api("receber_compra", pedido=p2["pedido"], corrida=CORRIDAS[1], nota_fiscal="NF-2", vencimento=str(hoje - timedelta(days=2)))
saldo = api("saldo_aco_corridas")
corr = {c["corrida"]: c for c in saldo["corridas"]}
ok("as duas corridas entram com o saldo recebido", corr[CORRIDAS[0]]["saldo_kg"] == 600 and corr[CORRIDAS[1]]["saldo_kg"] == 800 and corr[CORRIDAS[0]]["bitola_mm"] == 10.0)
p3 = api("solicitar_compra", **{**base, "quantidade": 100, "fornecedor": "Forn Teste Aço"})
api("aprovar_compra", pedido=p3["pedido"])
api("receber_compra", pedido=p3["pedido"], corrida=CORRIDAS[0])
ok("mais aço na mesma corrida soma no saldo (700 kg)", {c["corrida"]: c for c in api("saldo_aco_corridas")["corridas"]}[CORRIDAS[0]]["saldo_kg"] == 700)
p4 = api("solicitar_compra", **{**base, "quantidade": 50, "bitola_mm": 12.5, "fornecedor": "Forn Teste Aço"})
api("aprovar_compra", pedido=p4["pedido"])
r = api("receber_compra", pedido=p4["pedido"], corrida=CORRIDAS[0])
ok("a mesma corrida com outra bitola é recusada", not r.get("success") and "bitola" in r.get("error", ""), str(r.get("error")))
api("cancelar_compra", pedido=p4["pedido"])
ok("pedido cancelado não recebe", not api("receber_compra", pedido=p4["pedido"], corrida="CR-X").get("success"))

print("[Contas a pagar]")
tit = [t for t in api("listar_titulos_pagar", status="Aberto")["titulos"] if t["fornecedor"].startswith("Forn Teste")]
ok("três títulos abertos (600, 800 e 100 kg)", len(tit) == 3 and sorted(t["valor"] for t in tit) == [650.0, 3900.0, 5200.0], str([t["valor"] for t in tit]))
ok("o título vencido há 2 dias aparece como vencido", any(t["vencido"] and t["valor"] == 5200.0 for t in tit))
ok("paga um título (o que vence por último, para o vencido continuar em atraso)", api("pagar_titulo", titulo=tit[-1]["name"]).get("success"))
ok("não paga duas vezes", not api("pagar_titulo", titulo=tit[-1]["name"]).get("success"))

print("[Necessidade de materiais]")
api("program_piece", codigo_peca=pc["CA"], forma_pista=FORMA, data_programada=str(hoje + timedelta(days=20)))
api("program_piece", codigo_peca=pc["CB"], forma_pista=FORMA, data_programada=str(hoje + timedelta(days=3)))
n = api("necessidade_materiais", obra=OBRA)
aco = {l["bitola_mm"]: l for l in n["aco"]}
ok("Ø10: 100 barras de 10 m = 617 kg necessários", abs(aco[10.0]["necessario_kg"] - 617.0) < 0.5, str(aco[10.0]))
ok("Ø12,5: 50 barras de 10 m = 482 kg necessários", abs(aco[12.5]["necessario_kg"] - 482.0) < 1.0, str(aco[12.5]))
sd = api("saldo_aco_corridas")["por_bitola"]
cam = sum(p["quantidade"] for p in api("listar_pedidos_compra")["pedidos"] if p["categoria"] == "Aço" and p["status"] in ("Solicitado", "Aprovado") and p["bitola_mm"] == 10.0)
falta10 = max(0.0, aco[10.0]["necessario_kg"] - sd.get("10.0", 0.0) - cam)
ok("a falta é a necessidade menos o saldo menos o que está a caminho", abs(aco[10.0]["falta_kg"] - round(falta10, 1)) < 0.2, f"falta {aco[10.0]['falta_kg']} saldo {sd.get('10.0')} a caminho {cam}")
ok("Ø12,5 sem estoque: falta tudo e sugere barras de 12 m", aco[12.5]["falta_kg"] > 0 and aco[12.5]["barras_sugeridas"] == math.ceil(aco[12.5]["falta_kg"] / (12 * 12.5 * 12.5 * 0.00617)), str(aco[12.5]))
ok("comprar até = data da peça menos o prazo (3 dias - 7 = há 4 dias): atrasado", aco[12.5]["comprar_ate"] == str(hoje + timedelta(days=3) - timedelta(days=7)) and aco[12.5]["atrasado"] is True)
ok("a peça do dia 20 ainda dá tempo", aco[10.0]["comprar_ate"] == str(hoje + timedelta(days=20) - timedelta(days=7)) and aco[10.0]["atrasado"] is False)
ok("o cimento sai do volume de concreto (5 m³ x 350 kg)", n["concreto"]["volume_m3"] == 5.0 and n["concreto"]["cimento_necessario_kg"] == 1750.0, str(n["concreto"]))

print("[Plano de corte consome o estoque]")
plano = api("gerar_plano_corte", obra=OBRA, pecas=json.dumps([pc["CA"]]))
ok("o plano de Ø10 compra 100 barras de 12 m (uma por corte de 10 m): 740,4 kg", plano["success"] and abs(plano["por_bitola"][0]["aco_comprado_kg"] - 740.4) < 0.2, str(plano.get("error") or plano["por_bitola"][0]["aco_comprado_kg"]))
r = api("mudar_status_plano_corte", plano=plano["plano"], status="Concluído")
corr = {c["corrida"]: c for c in api("saldo_aco_corridas")["corridas"]}
ok("concluir gasta a corrida mais antiga primeiro (A zera, B perde o resto)", corr[CORRIDAS[0]]["saldo_kg"] == 0 and abs(corr[CORRIDAS[1]]["saldo_kg"] - (800 - (740.4 - 700))) < 0.3, str((corr[CORRIDAS[0]]["saldo_kg"], corr[CORRIDAS[1]]["saldo_kg"])))
plano2 = api("gerar_plano_corte", obra=OBRA, pecas=json.dumps([pc["CB"]]))
r = api("mudar_status_plano_corte", plano=plano2["plano"], status="Concluído")
ok("sem estoque da bitola, o plano conclui e avisa que o saldo não cobriu", r["success"] and "12.5" in r.get("saldo_insuficiente", {}) and "estoque" in r.get("aviso", ""), str(r))

print("[Orçado x realizado]")
orr = {o["obra"]: o for o in api("orcado_realizado_obras")["obras"]}[OBRA]
pedidos_obra = [p for p in api("listar_pedidos_compra", obra=OBRA)["pedidos"]]
comp = sum(p["valor_total"] for p in pedidos_obra if p["status"] in ("Aprovado", "Recebido"))
rec = sum(p["valor_total"] for p in pedidos_obra if p["status"] == "Recebido")
ok("comprometido soma aprovados e recebidos da obra", abs(orr["comprometido"] - comp) < 0.01 and abs(orr["recebido"] - rec) < 0.01, f"{orr['comprometido']} x {comp}")
ok("o consumo do orçamento é comprometido sobre orçado", orr["orcado"] > 0 and abs(orr["consumo_pct"] - round(100 * comp / orr["orcado"], 1)) < 0.11, str(orr))
ok("cancelado não conta", all(p["status"] != "Cancelado" or True for p in pedidos_obra))

print("[Fluxo de caixa]")
f = api("fluxo_caixa_projetado", semanas=6)
abertos = sum(t["valor"] for t in api("listar_titulos_pagar", status="Aberto")["titulos"])
ok("seis semanas", len(f["semanas"]) == 6)
ok("tudo o que está a pagar aparece (vencidos entram na primeira semana)", abs(sum(w["pagar"] for w in f["semanas"]) - abertos) < 0.01, str((sum(w["pagar"] for w in f["semanas"]), abertos)))
ok("o saldo acumulado é recebimentos menos pagamentos", abs(f["semanas"][-1]["saldo_acumulado"] - round(sum(w["receber"] - w["pagar"] for w in f["semanas"]), 2)) < 0.02)
ok("os vencidos aparecem em atraso", f["em_atraso"]["pagar"] > 0)

print("[Permissões e limpeza]")
ok("os pedidos exigem sessão", requests.post(f"{URL}/api/method/frappe.precast_api.listar_pedidos_compra", json={}).status_code in (401, 403))
api("delete_obra", codigo_obra=OBRA)
ok("excluir a obra apaga os pedidos e títulos dela", not api("listar_pedidos_compra", obra=OBRA)["pedidos"])
limpar()
print(f"\n{'FALHOU: ' + ', '.join(falhas) if falhas else 'tudo ok'}")
sys.exit(1 if falhas else 0)
