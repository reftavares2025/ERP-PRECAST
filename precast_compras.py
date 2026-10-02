"""Suprimentos e financeiro: necessidade de materiais pela produção, pedidos de compra com alçada, recebimento que
alimenta o saldo de aço por corrida, contas a pagar, fluxo de caixa projetado e orçado x realizado por obra."""
import json
import math
from datetime import timedelta

import frappe
from frappe.utils import add_days, flt, getdate, now_datetime

ALCADA_PRODUCAO_PADRAO = 5000.0       # até esse valor Produção, Financeiro ou Direção aprovam; acima, só a Direção
PRAZO_ENTREGA_PADRAO_DIAS = 7
PRAZO_PAGAMENTO_PADRAO_DIAS = 28
CATEGORIAS = ("Aço", "Cimento", "Agregado", "Outros")
CHAVES = {"alcada_producao": "compras_alcada_producao", "prazo_dias": "compras_prazo_dias"}
ABERTOS = ("Solicitado", "Aprovado")
FASE_ARMACAO_PRONTA = 2
FASE_CONCRETADO = 4


def _erro(texto):
    return {"success": False, "error": texto}


def configuracao(alcada_producao=None, prazo_dias=None):
    for nome, valor, minimo in (("alcada_producao", alcada_producao, 0), ("prazo_dias", prazo_dias, 0)):
        if valor in (None, ""):
            continue
        try:
            numero = float(str(valor).replace(",", "."))
        except ValueError:
            return _erro("Informe a configuração das compras em números.")
        if numero < minimo:
            return _erro("A configuração das compras não pode ser negativa.")
        frappe.defaults.set_global_default(CHAVES[nome], str(numero))
    alcada, prazo = frappe.defaults.get_global_default(CHAVES["alcada_producao"]), frappe.defaults.get_global_default(CHAVES["prazo_dias"])
    return {"success": True, "alcada_producao": float(alcada) if alcada not in (None, "") else ALCADA_PRODUCAO_PADRAO,
            "prazo_dias": float(prazo) if prazo not in (None, "") else float(PRAZO_ENTREGA_PADRAO_DIAS)}


def quem_aprova(valor):
    """Setores que podem aprovar um pedido deste valor."""
    if valor <= configuracao()["alcada_producao"]:
        return ("Produção", "Financeiro", "Direção")
    return ("Direção",)


# ---------------------------------------------------------------- pedidos

def solicitar(item, categoria, quantidade, preco_unitario, fornecedor, obra=None, bitola_mm=None, unidade="kg", prazo_dias=None, observacoes=None):
    item, fornecedor = (item or "").strip(), (fornecedor or "").strip()
    if not item or not fornecedor:
        return _erro("Informe o item e o fornecedor.")
    if categoria not in CATEGORIAS:
        return _erro("Escolha a categoria do pedido: " + ", ".join(CATEGORIAS) + ".")
    qtd, preco = flt(quantidade), flt(preco_unitario)
    if qtd <= 0 or preco <= 0:
        return _erro("A quantidade e o preço unitário devem ser maiores que zero.")
    if categoria == "Aço" and flt(bitola_mm) <= 0:
        return _erro("Pedido de aço precisa da bitola em mm.")
    if obra and not frappe.db.exists("Obra", obra):
        return _erro(f"Obra {obra} não encontrada.")
    valor = round(qtd * preco, 2)
    doc = frappe.get_doc({
        "doctype": "Pedido Compra", "obra": obra, "fornecedor": fornecedor, "item": item, "categoria": categoria,
        "bitola_mm": flt(bitola_mm) or None, "quantidade": qtd, "unidade": unidade or "kg", "preco_unitario": preco, "valor_total": valor,
        "status": "Solicitado", "solicitante": frappe.session.user, "data_solicitacao": now_datetime(),
        "prazo_dias": int(flt(prazo_dias)) if prazo_dias not in (None, "") else int(configuracao()["prazo_dias"]), "observacoes": observacoes,
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "pedido": doc.name, "valor_total": valor, "aprovacao_exigida": list(quem_aprova(valor))}


def _pedido(nome):
    return frappe.db.get_value("Pedido Compra", nome or "", ["name", "status", "valor_total", "categoria", "bitola_mm", "quantidade", "unidade", "fornecedor",
                                                             "obra", "solicitante", "prazo_dias", "item"], as_dict=True)


def aprovar(nome):
    p = _pedido(nome)
    if not p:
        return _erro("Pedido não encontrado.")
    if p.status != "Solicitado":
        return _erro(f"O pedido está {p.status.lower()} e não pode ser aprovado.")
    if p.solicitante == frappe.session.user and "Direção" not in _setores_do_usuario() and frappe.session.user != "Administrator":
        return _erro("Quem fez o pedido não pode aprová-lo. Peça a outra pessoa.")
    frappe.db.set_value("Pedido Compra", nome, {"status": "Aprovado", "aprovador": frappe.session.user, "data_aprovacao": now_datetime()})
    frappe.db.commit()
    return {"success": True, "status": "Aprovado"}


def _setores_do_usuario():
    from frappe.precast_api import SETORES_ASSENTO, _papel_do_setor
    papeis = set(frappe.get_roles(frappe.session.user))
    return {s for s in SETORES_ASSENTO if _papel_do_setor(s) in papeis}


def cancelar(nome):
    p = _pedido(nome)
    if not p:
        return _erro("Pedido não encontrado.")
    if p.status not in ABERTOS:
        return _erro(f"O pedido está {p.status.lower()} e não pode ser cancelado.")
    frappe.db.set_value("Pedido Compra", nome, "status", "Cancelado")
    frappe.db.commit()
    return {"success": True}


def receber(nome, corrida=None, nota_fiscal=None, vencimento=None, data_recebimento=None):
    p = _pedido(nome)
    if not p:
        return _erro("Pedido não encontrado.")
    if p.status != "Aprovado":
        return _erro("Só o pedido aprovado pode ser recebido.")
    corrida = (corrida or "").strip()
    if p.categoria == "Aço":
        if not corrida:
            return _erro("Informe a corrida (lote) do aço recebido: ela liga o saldo ao certificado.")
        if frappe.db.exists("Certificado Aco", corrida):
            existente = frappe.db.get_value("Certificado Aco", corrida, ["bitola_mm", "quantidade_kg", "saldo_kg"], as_dict=True)
            if abs(flt(existente.bitola_mm) - flt(p.bitola_mm)) > 0.01:
                return _erro(f"A corrida {corrida} já existe com bitola {flt(existente.bitola_mm):g} mm e o pedido é de {flt(p.bitola_mm):g} mm.")
            frappe.db.set_value("Certificado Aco", corrida, {"quantidade_kg": flt(existente.quantidade_kg) + flt(p.quantidade),
                                                             "saldo_kg": flt(existente.saldo_kg) + flt(p.quantidade)})
        else:
            frappe.get_doc({"doctype": "Certificado Aco", "corrida": corrida, "bitola_mm": flt(p.bitola_mm), "fabricante": p.fornecedor, "norma": "CA-50",
                            "data_recebimento": data_recebimento or getdate(), "nota_fiscal": nota_fiscal, "quantidade_kg": flt(p.quantidade),
                            "saldo_kg": flt(p.quantidade), "registrado_por": frappe.utils.get_fullname(frappe.session.user)}).insert(ignore_permissions=True)
    data = getdate(data_recebimento) if data_recebimento else getdate()
    venc = getdate(vencimento) if vencimento else add_days(data, PRAZO_PAGAMENTO_PADRAO_DIAS)
    frappe.db.set_value("Pedido Compra", nome, {"status": "Recebido", "data_recebimento": now_datetime(), "corrida": corrida or None,
                                                "nota_fiscal": nota_fiscal, "vencimento": venc})
    frappe.get_doc({"doctype": "Titulo Pagar", "pedido": nome, "fornecedor": p.fornecedor, "obra": p.obra, "valor": flt(p.valor_total),
                    "vencimento": venc, "status": "Aberto", "nota_fiscal": nota_fiscal}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "status": "Recebido", "vencimento": str(venc)}


def listar_pedidos(obra=None, status=None):
    filtros = {}
    if obra:
        filtros["obra"] = obra
    if status:
        filtros["status"] = status
    linhas = frappe.get_all("Pedido Compra", filters=filtros, order_by="creation desc", limit=500,
                            fields=["name", "obra", "fornecedor", "item", "categoria", "bitola_mm", "quantidade", "unidade", "preco_unitario", "valor_total", "status",
                                    "solicitante", "aprovador", "data_solicitacao", "data_aprovacao", "data_recebimento", "prazo_dias", "vencimento", "corrida", "nota_fiscal"])
    for l in linhas:
        l["aprovacao_exigida"] = list(quem_aprova(flt(l["valor_total"])))
    return linhas


# ---------------------------------------------------------------- contas a pagar

def listar_titulos(status=None):
    filtros = {"status": status} if status else {}
    hoje = getdate()
    linhas = frappe.get_all("Titulo Pagar", filters=filtros, order_by="vencimento asc", limit=500,
                            fields=["name", "pedido", "fornecedor", "obra", "valor", "vencimento", "status", "pago_em", "nota_fiscal"])
    for l in linhas:
        l["vencido"] = l["status"] == "Aberto" and getdate(l["vencimento"]) < hoje
    return linhas


def pagar(titulo, data=None):
    if not frappe.db.exists("Titulo Pagar", titulo or ""):
        return _erro("Título não encontrado.")
    if frappe.db.get_value("Titulo Pagar", titulo, "status") == "Pago":
        return _erro("O título já está pago.")
    frappe.db.set_value("Titulo Pagar", titulo, {"status": "Pago", "pago_em": getdate(data) if data else getdate()})
    frappe.db.commit()
    return {"success": True}


def fluxo_caixa(semanas=8):
    """Por semana: o que vence a pagar (títulos abertos) e o que entra (faturas em aberto do ERP), com o saldo acumulado."""
    semanas = max(1, min(int(semanas), 26))
    hoje = getdate()
    inicio = hoje - timedelta(days=hoje.weekday())
    pagar_titulos = frappe.get_all("Titulo Pagar", filters={"status": "Aberto"}, fields=["valor", "vencimento"])
    receber_ok, faturas = True, []
    try:
        faturas = frappe.get_all("Sales Invoice", filters={"docstatus": 1, "outstanding_amount": [">", 0]}, fields=["outstanding_amount", "due_date"])
    except Exception:
        receber_ok = False
    atrasado_pagar = sum(flt(t.valor) for t in pagar_titulos if getdate(t.vencimento) < hoje)
    atrasado_receber = sum(flt(f.outstanding_amount) for f in faturas if f.due_date and getdate(f.due_date) < hoje)
    linhas, saldo = [], 0.0
    for i in range(semanas):
        de, ate = add_days(inicio, 7 * i), add_days(inicio, 7 * i + 6)
        # a primeira semana absorve tudo o que já venceu: nada some do fluxo
        na_semana = lambda dia: (de <= dia <= ate) or (i == 0 and dia < de)
        pagar_semana = sum(flt(t.valor) for t in pagar_titulos if na_semana(getdate(t.vencimento)))
        receber_semana = sum(flt(f.outstanding_amount) for f in faturas if f.due_date and na_semana(getdate(f.due_date)))
        saldo += receber_semana - pagar_semana
        linhas.append({"de": de.isoformat(), "ate": ate.isoformat(), "pagar": round(pagar_semana, 2), "receber": round(receber_semana, 2), "saldo_acumulado": round(saldo, 2)})
    return {"success": True, "semanas": linhas, "receber_disponivel": receber_ok,
            "em_atraso": {"pagar": round(atrasado_pagar, 2), "receber": round(atrasado_receber, 2)}}


# ---------------------------------------------------------------- aço: saldo e consumo

def saldo_aco():
    linhas = frappe.get_all("Certificado Aco", fields=["corrida", "bitola_mm", "quantidade_kg", "saldo_kg", "data_recebimento", "fabricante"], order_by="data_recebimento asc")
    por_bitola = {}
    for l in linhas:
        por_bitola[round(flt(l.bitola_mm), 1)] = por_bitola.get(round(flt(l.bitola_mm), 1), 0.0) + flt(l.saldo_kg)
    return linhas, por_bitola


def consumir_aco(por_bitola):
    """O plano de corte concluído gasta aço das corridas mais antigas (FIFO). Devolve o que faltou de saldo."""
    faltou = {}
    for bitola, kg in (por_bitola or {}).items():
        restante = flt(kg)
        for c in frappe.get_all("Certificado Aco", filters={"bitola_mm": float(bitola), "saldo_kg": [">", 0]}, fields=["corrida", "saldo_kg"], order_by="data_recebimento asc, creation asc"):
            if restante <= 0:
                break
            gasto = min(flt(c.saldo_kg), restante)
            frappe.db.set_value("Certificado Aco", c.corrida, "saldo_kg", round(flt(c.saldo_kg) - gasto, 3))
            restante -= gasto
        if restante > 0.001:
            faltou[str(bitola)] = round(restante, 1)
    return faltou


# ---------------------------------------------------------------- necessidade de materiais

def necessidade(obra=None):
    from frappe.precast_corte import kg_por_metro, configuracao as conf_corte
    from frappe.precast_api import FATOR_CIMENTO_KG_POR_M3
    barra = conf_corte()["barra_m"]
    prazo = int(configuracao()["prazo_dias"])
    filtros = {"fase_numero": ["<=", 3]}
    if obra and obra != "ALL":
        filtros["obra"] = obra
    pecas = frappe.get_all("Peca Pre-Moldada", filters=filtros, fields=["name", "obra", "fase_numero", "lista_ferros", "volume_m3", "data_programada"])
    aco, volume, datas = {}, 0.0, {}
    for p in pecas:
        if int(p.fase_numero or 1) < FASE_CONCRETADO:
            volume += flt(p.volume_m3)
        if int(p.fase_numero or 1) >= FASE_ARMACAO_PRONTA:
            continue                                    # o aço desta peça já foi cortado e armado
        try:
            ferros = json.loads(p.lista_ferros or "[]")
        except ValueError:
            ferros = []
        for f in ferros:
            bitola = round(flt(f.get("bitola_mm")), 1)
            if bitola <= 0:
                continue
            kg = flt(f.get("quantidade")) * flt(f.get("comp_unit_m")) * kg_por_metro(bitola)
            aco[bitola] = aco.get(bitola, 0.0) + kg
            if p.data_programada:
                datas[bitola] = min(datas.get(bitola, getdate(p.data_programada)), getdate(p.data_programada))
    _, saldo = saldo_aco()
    caminho = {}
    for pc in frappe.get_all("Pedido Compra", filters={"status": ["in", list(ABERTOS)], "categoria": "Aço"}, fields=["bitola_mm", "quantidade"]):
        caminho[round(flt(pc.bitola_mm), 1)] = caminho.get(round(flt(pc.bitola_mm), 1), 0.0) + flt(pc.quantidade)
    linhas = []
    for bitola in sorted(aco):
        faltam = max(0.0, aco[bitola] - saldo.get(bitola, 0.0) - caminho.get(bitola, 0.0))
        comprar_ate = add_days(datas[bitola], -prazo) if bitola in datas else None
        linhas.append({"bitola_mm": bitola, "necessario_kg": round(aco[bitola], 1), "saldo_kg": round(saldo.get(bitola, 0.0), 1),
                       "a_caminho_kg": round(caminho.get(bitola, 0.0), 1), "falta_kg": round(faltam, 1),
                       "barras_sugeridas": math.ceil(faltam / (barra * kg_por_metro(bitola))) if faltam > 0 else 0,
                       "comprar_ate": comprar_ate.isoformat() if comprar_ate else None,
                       "atrasado": bool(comprar_ate and faltam > 0 and comprar_ate < getdate())})
    cimento_nec = round(volume * FATOR_CIMENTO_KG_POR_M3, 1)
    cimento_caminho = sum(flt(pc.quantidade) for pc in frappe.get_all("Pedido Compra", filters={"status": ["in", list(ABERTOS)], "categoria": "Cimento"}, fields=["quantidade"]))
    return {"success": True, "obra": obra or "ALL", "aco": linhas, "barra_m": barra, "prazo_dias": prazo,
            "concreto": {"volume_m3": round(volume, 2), "cimento_necessario_kg": cimento_nec, "cimento_a_caminho_kg": round(cimento_caminho, 1),
                         "cimento_falta_kg": round(max(0.0, cimento_nec - cimento_caminho), 1)}}


# ---------------------------------------------------------------- orçado x realizado

def orcado_realizado():
    obras = frappe.get_all("Obra", fields=["codigo_obra", "nome_obra"], order_by="codigo_obra asc")
    saida = []
    for o in obras:
        pecas = frappe.get_all("Peca Pre-Moldada", filters={"obra": o.codigo_obra}, fields=["custo_estimado_peca", "preco_venda_sugerido"])
        if not pecas:
            continue
        orcado = sum(flt(p.custo_estimado_peca) for p in pecas)
        venda = sum(flt(p.preco_venda_sugerido) for p in pecas)
        pedidos = frappe.get_all("Pedido Compra", filters={"obra": o.codigo_obra, "status": ["in", ["Aprovado", "Recebido"]]}, fields=["status", "valor_total"])
        comprometido = sum(flt(p.valor_total) for p in pedidos)
        recebido = sum(flt(p.valor_total) for p in pedidos if p.status == "Recebido")
        saida.append({"obra": o.codigo_obra, "nome": o.nome_obra, "pecas": len(pecas), "orcado": round(orcado, 2), "preco_venda": round(venda, 2),
                      "comprometido": round(comprometido, 2), "recebido": round(recebido, 2),
                      "consumo_pct": round(100 * comprometido / orcado, 1) if orcado else None,
                      "margem_pct": round(100 * (venda - comprometido) / venda, 1) if venda else None,
                      "estourou": bool(orcado and comprometido > orcado)})
    return saida
