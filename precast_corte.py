"""Corte e dobra do aço: plano de corte a partir das listas de ferros das peças.

Cada bitola é um problema de barras de comprimento fixo: os cortes das peças escolhidas entram nas barras com o
menor desperdício (best-fit decrescente). Corte maior que a barra vira dois ou mais trechos com traspasse. O plano
guarda quais cortes saem de cada barra, para a bancada cortar e conferir, e o quanto de aço sobra."""
import json
import math

import frappe
from frappe.utils import now_datetime

BARRA_PADRAO_M = 12.0
TRASPASSE_PADRAO_DIAMETROS = 40       # NBR 6118: traspasse de CA-50 em barras comprimidas ou tracionadas pequenas
RETALHO_MINIMO_PADRAO_M = 0.5         # sobra a partir daqui volta para o estoque como retalho
KG_POR_M_POR_MM2 = 0.00617            # kg/m = ø² x 0,00617 (ø em mm)
CHAVES = {"barra_m": "corte_barra_m", "traspasse_diametros": "corte_traspasse_diametros", "retalho_minimo_m": "corte_retalho_minimo_m"}
PADROES = {"barra_m": BARRA_PADRAO_M, "traspasse_diametros": TRASPASSE_PADRAO_DIAMETROS, "retalho_minimo_m": RETALHO_MINIMO_PADRAO_M}
STATUS = ("Gerado", "Em corte", "Concluído", "Cancelado")
ATIVOS = ("Gerado", "Em corte")


def _erro(texto):
    return {"success": False, "error": texto}


def configuracao(barra_m=None, traspasse_diametros=None, retalho_minimo_m=None):
    """Lê (e, se vierem valores, grava) os parâmetros do plano de corte."""
    novos = {"barra_m": barra_m, "traspasse_diametros": traspasse_diametros, "retalho_minimo_m": retalho_minimo_m}
    for nome, valor in novos.items():
        if valor in (None, ""):
            continue
        try:
            numero = float(str(valor).replace(",", "."))
        except ValueError:
            return _erro("Informe os parâmetros do corte em números.")
        limites = {"barra_m": (3.0, 24.0), "traspasse_diametros": (20, 80), "retalho_minimo_m": (0.1, 3.0)}[nome]
        if not limites[0] <= numero <= limites[1]:
            return _erro(f"{nome.replace('_', ' ')} deve ficar entre {limites[0]:g} e {limites[1]:g}.")
        frappe.defaults.set_global_default(CHAVES[nome], str(numero))
    atuais = {}
    for nome, chave in CHAVES.items():
        valor = frappe.defaults.get_global_default(chave)
        atuais[nome] = float(valor) if valor not in (None, "") else PADROES[nome]
    return {"success": True, **atuais}


def kg_por_metro(bitola_mm):
    return bitola_mm * bitola_mm * KG_POR_M_POR_MM2


def empacotar(comprimentos, barra_m):
    """Best-fit decrescente. `comprimentos` é uma lista de (id, comprimento_m); devolve a lista de barras
    [{"cortes": [(id, comp)], "usado": m}]. O corte maior que a barra deve ter sido dividido antes."""
    ordem = sorted(comprimentos, key=lambda c: -c[1])
    barras = []
    for ident, comp in ordem:
        escolhida = None
        for barra in barras:
            livre = barra_m - barra["usado"]
            if comp <= livre + 1e-9 and (escolhida is None or livre < barra_m - escolhida["usado"]):
                escolhida = barra
        if escolhida is None:
            escolhida = {"cortes": [], "usado": 0.0}
            barras.append(escolhida)
        escolhida["cortes"].append((ident, comp))
        escolhida["usado"] += comp
    return barras


def _dividir(comp_m, barra_m, traspasse_m):
    """Corte maior que a barra: trechos de barra inteira, cada emenda gasta um traspasse."""
    if comp_m <= barra_m + 1e-9:
        return [comp_m]
    util = barra_m - traspasse_m
    trechos = max(2, math.ceil((comp_m - traspasse_m) / util))
    base = (comp_m + traspasse_m * (trechos - 1)) / trechos
    return [round(base, 3)] * trechos


def _ferros_da_peca(peca):
    try:
        return json.loads(peca.get("lista_ferros") or "[]")
    except ValueError:
        return []


def calcular(pecas, barra_m, traspasse_diametros, retalho_minimo_m):
    """`pecas`: lista de dicts com codigo_peca, tag e lista_ferros. Devolve o plano sem gravar."""
    avisos, demanda = [], {}
    sem_lista = []
    for peca in pecas:
        ferros = _ferros_da_peca(peca)
        if not ferros:
            sem_lista.append(peca.get("tag") or peca["codigo_peca"])
            continue
        for f in ferros:
            try:
                bitola, qtd, comp = round(float(f.get("bitola_mm")), 1), int(float(f.get("quantidade"))), float(f.get("comp_unit_m"))
            except (TypeError, ValueError):
                continue
            if bitola <= 0 or qtd <= 0 or comp <= 0:
                continue
            demanda.setdefault(bitola, []).append({"peca": peca["codigo_peca"], "tag": peca.get("tag") or peca["codigo_peca"],
                                                   "posicao": str(f.get("posicao", "")), "quantidade": qtd, "comp_m": comp})
    if sem_lista:
        avisos.append(f"{len(sem_lista)} peça(s) sem lista de ferros ficaram fora do plano: " + ", ".join(sem_lista[:6]))

    por_bitola, lista_de_corte, barras_planas = [], [], []
    necessario_kg = comprado_kg = sobra_util_m = 0.0
    total_barras = total_cortes = 0
    for bitola in sorted(demanda):
        traspasse = traspasse_diametros * bitola / 1000.0
        cortes, emendas = [], 0
        for linha in demanda[bitola]:
            lista_de_corte.append({"peca": linha["peca"], "tag": linha["tag"], "posicao": linha["posicao"], "bitola_mm": bitola,
                                   "quantidade": linha["quantidade"], "comp_m": linha["comp_m"]})
            trechos = _dividir(linha["comp_m"], barra_m, traspasse)
            if len(trechos) > 1:
                emendas += (len(trechos) - 1) * linha["quantidade"]
            for n in range(linha["quantidade"]):
                for t in trechos:
                    cortes.append(((linha["tag"], linha["posicao"]), t))
        barras = empacotar(cortes, barra_m)
        necessario = sum(c for _, c in cortes) * kg_por_metro(bitola)
        comprado = len(barras) * barra_m * kg_por_metro(bitola)
        sobras = [barra_m - b["usado"] for b in barras]
        util = sum(s for s in sobras if s >= retalho_minimo_m)
        padroes = {}
        for numero, barra in enumerate(barras, start=1):
            chave = tuple(sorted(round(c, 3) for _, c in barra["cortes"]))
            padroes.setdefault(chave, {"vezes": 0, "cortes": chave, "sobra_m": round(barra_m - barra["usado"], 3)})["vezes"] += 1
            for (tag, posicao), comp in barra["cortes"]:
                barras_planas.append({"bitola_mm": bitola, "barra": total_barras + numero, "tag": tag, "posicao": posicao, "comp_m": round(comp, 3)})
        por_bitola.append({
            "bitola_mm": bitola, "barras": len(barras), "cortes": len(cortes), "emendas": emendas,
            "aco_necessario_kg": round(necessario, 1), "aco_comprado_kg": round(comprado, 1),
            "aproveitamento_pct": round(100 * sum(b["usado"] for b in barras) / (len(barras) * barra_m), 1) if barras else 0,
            "sobra_aproveitavel_m": round(util, 2),
            "padroes": sorted(({"vezes": p["vezes"], "cortes": list(p["cortes"]), "sobra_m": p["sobra_m"]} for p in padroes.values()),
                              key=lambda p: -p["vezes"]),
        })
        total_barras += len(barras)
        total_cortes += len(cortes)
        necessario_kg += necessario
        comprado_kg += comprado
        sobra_util_m += util
        if emendas:
            avisos.append(f"Ø {bitola:g} mm: {emendas} emenda(s) porque há ferros maiores que a barra de {barra_m:g} m "
                          f"(traspasse de {traspasse_diametros:g}ø = {traspasse * 100:.0f} cm). Confira com a engenharia.")
    if not demanda:
        return _erro("Nenhuma das peças escolhidas tem lista de ferros. Leia o desenho pelas pranchas de detalhamento.")
    perda = 100 * (1 - necessario_kg / comprado_kg) if comprado_kg else 0.0
    return {"success": True,
            "parametros": {"barra_m": barra_m, "traspasse_diametros": traspasse_diametros, "retalho_minimo_m": retalho_minimo_m},
            "resumo": {"pecas": len(pecas) - len(sem_lista), "cortes": total_cortes, "barras": total_barras,
                       "aco_necessario_kg": round(necessario_kg, 1), "aco_comprado_kg": round(comprado_kg, 1),
                       "perda_pct": round(perda, 1), "sobra_aproveitavel_m": round(sobra_util_m, 2)},
            "por_bitola": por_bitola, "lista_de_corte": lista_de_corte, "barras": barras_planas, "avisos": avisos}


def pecas_para_corte(obra):
    """Peças da obra ainda em Corte e Dobra, com a marca de quais já estão num plano ativo."""
    ativos = {p.name for p in frappe.get_all("Plano Corte", filters={"obra": obra, "status": ["in", list(ATIVOS)]}, fields=["name"])}
    saida = []
    for p in frappe.get_all("Peca Pre-Moldada", filters={"obra": obra, "fase_numero": 1}, order_by="tag asc",
                            fields=["name", "tag", "produto", "secao", "peso_aco_kg", "lista_ferros", "plano_corte"]):
        saida.append({"codigo_peca": p.name, "tag": p.tag, "produto": p.produto, "secao": p.secao, "aco_kg": p.peso_aco_kg,
                      "ferros": len(_ferros_da_peca(p)), "plano": p.plano_corte if p.plano_corte in ativos else None})
    return saida


def gerar(obra, pecas=None, barra_m=None):
    if not frappe.db.exists("Obra", obra or ""):
        return _erro(f"Obra {obra} não encontrada.")
    conf = configuracao(barra_m=barra_m)
    if not conf.get("success"):
        return conf
    elegiveis = {p["codigo_peca"]: p for p in pecas_para_corte(obra)}
    if pecas:
        codigos = [str(c).strip() for c in (json.loads(pecas) if isinstance(pecas, str) else pecas)]
        fora = [c for c in codigos if c not in elegiveis]
        if fora:
            return _erro("Peça(s) que não estão em Corte e Dobra nesta obra: " + ", ".join(fora[:5]))
    else:
        codigos = [c for c, p in elegiveis.items() if not p["plano"]]
    ja_em_plano = [c for c in codigos if elegiveis[c]["plano"]]
    if ja_em_plano:
        return _erro("Peça(s) que já estão num plano de corte ativo: " + ", ".join(ja_em_plano[:5]) + ". Cancele o plano antes de gerar de novo.")
    if not codigos:
        return _erro("Não há peças em Corte e Dobra para planejar nesta obra.")
    docs = [frappe.db.get_value("Peca Pre-Moldada", c, ["name as codigo_peca", "tag", "lista_ferros"], as_dict=True) for c in codigos]
    plano = calcular(docs, conf["barra_m"], conf["traspasse_diametros"], conf["retalho_minimo_m"])
    if not plano.get("success"):
        return plano
    numero = frappe.db.count("Plano Corte", {"obra": obra}) + 1
    registro = frappe.get_doc({
        "doctype": "Plano Corte", "obra": obra, "numero": numero, "status": "Gerado", "data_hora": now_datetime(),
        "usuario": frappe.utils.get_fullname(frappe.session.user), "barra_m": conf["barra_m"],
        "barras": plano["resumo"]["barras"], "perda_pct": plano["resumo"]["perda_pct"], "aco_comprado_kg": plano["resumo"]["aco_comprado_kg"],
        "pecas": json.dumps(codigos), "resultado": json.dumps(plano, ensure_ascii=False),
    }).insert(ignore_permissions=True)
    for c in codigos:
        frappe.db.set_value("Peca Pre-Moldada", c, "plano_corte", registro.name, update_modified=False)
    frappe.db.commit()
    return {"success": True, "plano": registro.name, "numero": numero, **plano}


def _liberar_pecas(nome_plano, codigos):
    for c in codigos:
        if frappe.db.get_value("Peca Pre-Moldada", c, "plano_corte") == nome_plano:
            frappe.db.set_value("Peca Pre-Moldada", c, "plano_corte", None, update_modified=False)


def mudar_status(nome_plano, status):
    if status not in STATUS:
        return _erro("Situação inválida para o plano de corte.")
    if not frappe.db.exists("Plano Corte", nome_plano or ""):
        return _erro("Plano de corte não encontrado.")
    atual = frappe.db.get_value("Plano Corte", nome_plano, "status")
    if atual in ("Concluído", "Cancelado"):
        return _erro(f"O plano já está {atual.lower()} e não muda mais.")
    frappe.db.set_value("Plano Corte", nome_plano, "status", status)
    if status == "Cancelado":
        _liberar_pecas(nome_plano, json.loads(frappe.db.get_value("Plano Corte", nome_plano, "pecas") or "[]"))
    faltou = {}
    if status == "Concluído":
        # o aço cortado sai do estoque, das corridas mais antigas para as mais novas
        from frappe.precast_compras import consumir_aco
        resultado = json.loads(frappe.db.get_value("Plano Corte", nome_plano, "resultado") or "{}")
        faltou = consumir_aco({b["bitola_mm"]: b["aco_comprado_kg"] for b in resultado.get("por_bitola", [])})
    frappe.db.commit()
    resposta = {"success": True, "status": status}
    if faltou:
        resposta["saldo_insuficiente"] = faltou
        resposta["aviso"] = "O estoque de aço cadastrado não cobre o plano: " + ", ".join(f"Ø {b} mm faltou {kg} kg" for b, kg in faltou.items()) + ". Confira os recebimentos."
    return resposta


def listar(obra):
    return frappe.get_all("Plano Corte", filters={"obra": obra}, order_by="numero desc",
                          fields=["name", "numero", "status", "data_hora", "usuario", "barra_m", "barras", "perda_pct", "aco_comprado_kg", "desatualizado"])


def abrir(nome_plano):
    if not frappe.db.exists("Plano Corte", nome_plano or ""):
        return _erro("Plano de corte não encontrado.")
    d = frappe.db.get_value("Plano Corte", nome_plano, ["name", "obra", "numero", "status", "data_hora", "usuario", "pecas", "resultado", "desatualizado"], as_dict=True)
    return {"success": True, "plano": d.name, "obra": d.obra, "numero": d.numero, "status": d.status, "data_hora": d.data_hora,
            "usuario": d.usuario, "desatualizado": bool(d.desatualizado), "pecas": json.loads(d.pecas or "[]"), **json.loads(d.resultado or "{}")}


def marcar_desatualizado(codigo_peca):
    """A lista de ferros da peça mudou (revisão do projeto): o plano ativo que a usa deixou de valer."""
    nome = frappe.db.get_value("Peca Pre-Moldada", codigo_peca, "plano_corte")
    if nome and frappe.db.get_value("Plano Corte", nome, "status") in ATIVOS:
        frappe.db.set_value("Plano Corte", nome, "desatualizado", 1)
        return nome
    return None
