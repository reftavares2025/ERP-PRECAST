"""Relatório de peças: o responsável escolhe o cliente, marca todas, algumas ou uma peça e o sistema reúne os dados
que ele quer ver no papel. A consulta é feita em bloco (uma por assunto) para valer também com centenas de peças."""
import json
import re

import frappe
from frappe.utils import flt

LIMITE_PECAS = 500
SECOES = ("dados", "producao", "rastreabilidade", "qualidade", "ferros", "entrega")


def _erro(texto):
    return {"success": False, "error": texto}


def _natural(tag):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(tag or ""))]


def clientes():
    """Clientes com obra cadastrada, e as obras e o número de peças de cada um."""
    obras = frappe.get_all("Obra", fields=["codigo_obra", "nome_obra", "cliente_nome", "cidade_uf"], order_by="cliente_nome asc, codigo_obra asc")
    contagem = {}
    for p in frappe.get_all("Peca Pre-Moldada", fields=["obra"]):
        contagem[p.obra] = contagem.get(p.obra, 0) + 1
    saida = {}
    for o in obras:
        nome = (o.cliente_nome or o.nome_obra or o.codigo_obra).strip()
        c = saida.setdefault(nome, {"cliente": nome, "obras": [], "pecas": 0})
        n = contagem.get(o.codigo_obra, 0)
        c["obras"].append({"codigo": o.codigo_obra, "nome": o.nome_obra, "cidade_uf": o.cidade_uf, "pecas": n})
        c["pecas"] += n
    return sorted(saida.values(), key=lambda c: c["cliente"].lower())


def pecas_da_selecao(cliente=None, obra=None):
    """Peças do cliente (todas as obras dele) ou de uma obra, com o que a tela precisa para listar."""
    filtros_obra = {}
    if obra:
        filtros_obra["codigo_obra"] = obra
    obras = frappe.get_all("Obra", filters=filtros_obra, fields=["codigo_obra", "nome_obra", "cliente_nome"])
    if cliente:
        obras = [o for o in obras if (o.cliente_nome or o.nome_obra or o.codigo_obra).strip() == cliente.strip()]
    codigos_obra = [o.codigo_obra for o in obras]
    if not codigos_obra:
        return []
    linhas = frappe.get_all("Peca Pre-Moldada", filters={"obra": ["in", codigos_obra]},
                            fields=["name as codigo_peca", "tag", "obra", "produto", "secao", "comprimento_m", "peso_kg", "fase_numero", "status_producao"])
    return sorted([dict(l) for l in linhas], key=lambda l: (l["obra"], _natural(l["tag"])))


def relatorio(codigos, secoes=None):
    lista = json.loads(codigos) if isinstance(codigos, str) else list(codigos or [])
    lista = list(dict.fromkeys(str(c).strip() for c in lista if str(c).strip()))
    if not lista:
        return _erro("Escolha ao menos uma peça para o relatório.")
    if len(lista) > LIMITE_PECAS:
        return _erro(f"Escolha até {LIMITE_PECAS} peças por relatório. Para mais, gere um relatório por obra.")
    pedidas = json.loads(secoes) if isinstance(secoes, str) else secoes
    pedidas = [s for s in (pedidas if pedidas is not None else SECOES) if s in SECOES]

    pecas = frappe.get_all("Peca Pre-Moldada", filters={"name": ["in", lista]},
                           fields=["name as codigo_peca", "tag", "obra", "cliente", "produto", "secao", "comprimento_m", "volume_m3", "peso_kg", "fck", "fase_numero",
                                   "status_producao", "forma_pista", "data_programada", "peso_aco_kg", "taxa_aco_kg_m3", "folha_prancha", "lista_ferros",
                                   "lote_concreto", "corridas_aco", "romaneio", "aviso_engenharia"])
    achadas = {p.codigo_peca for p in pecas}
    faltam = [c for c in lista if c not in achadas]
    if faltam:
        return _erro("Peça(s) não encontrada(s): " + ", ".join(faltam[:5]))
    from frappe.precast_api import _NOMES_FASES
    obras = {o.codigo_obra: o for o in frappe.get_all("Obra", fields=["codigo_obra", "nome_obra", "cliente_nome", "cidade_uf", "fck_padrao"])}

    historico, inspecoes, rncs, lotes, cps, certificados, romaneios = {}, {}, {}, {}, {}, {}, {}
    nomes = {}
    pessoa = lambda u: nomes.setdefault(u, frappe.utils.get_fullname(u) if u else "")
    if "producao" in pedidas:
        for h in frappe.get_all("Fase Historico", filters={"codigo_peca": ["in", lista]}, fields=["codigo_peca", "fase_nova", "data_hora", "usuario", "forma_pista"], order_by="data_hora asc"):
            historico.setdefault(h.codigo_peca, []).append({"fase": _NOMES_FASES.get(h.fase_nova, str(h.fase_nova)), "data_hora": str(h.data_hora)[:16], "quem": pessoa(h.usuario), "forma_pista": h.forma_pista})
    if "qualidade" in pedidas:
        for i in frappe.get_all("Checklist Qualidade", filters={"codigo_peca": ["in", lista]}, fields=["codigo_peca", "etapa", "aprovado", "inspetor", "data_inspecao", "observacoes"], order_by="data_inspecao asc"):
            inspecoes.setdefault(i.codigo_peca, []).append({"etapa": i.etapa, "aprovado": bool(i.aprovado), "inspetor": i.inspetor, "data": str(i.data_inspecao or "")[:16], "parecer": i.observacoes})
        for n in frappe.get_all("Nao Conformidade", filters={"codigo_peca": ["in", lista]}, fields=["codigo_peca", "descricao", "status", "data_abertura"], order_by="data_abertura asc"):
            rncs.setdefault(n.codigo_peca, []).append({"descricao": n.descricao, "status": n.status, "aberta_em": str(n.data_abertura or "")[:16]})
    if "rastreabilidade" in pedidas:
        codigos_lote = {p.lote_concreto for p in pecas if p.lote_concreto}
        if codigos_lote:
            for l in frappe.get_all("Lote Concreto", filters={"codigo": ["in", list(codigos_lote)]}, fields=["codigo", "data_concretagem", "usina", "fck_especificado"]):
                lotes[l.codigo] = {"codigo": l.codigo, "data_concretagem": str(l.data_concretagem or ""), "usina": l.usina, "fck_especificado": l.fck_especificado}
            for c in frappe.get_all("Corpo Prova", filters={"lote": ["in", list(codigos_lote)]}, fields=["lote", "idade_dias", "fck_obtido", "resultado"], order_by="idade_dias asc"):
                cps.setdefault(c.lote, []).append({"idade_dias": c.idade_dias, "fck_obtido": c.fck_obtido, "resultado": c.resultado})
        corridas = {x.strip() for p in pecas for x in (p.corridas_aco or "").split(",") if x.strip()}
        if corridas:
            for c in frappe.get_all("Certificado Aco", filters={"corrida": ["in", list(corridas)]}, fields=["corrida", "bitola_mm", "fabricante", "norma"]):
                certificados[c.corrida] = {"corrida": c.corrida, "bitola_mm": c.bitola_mm, "fabricante": c.fabricante, "norma": c.norma}
    if "entrega" in pedidas:
        codigos_rom = {p.romaneio for p in pecas if p.romaneio}
        if codigos_rom:
            for r in frappe.get_all("Romaneio", filters={"codigo": ["in", list(codigos_rom)]}, fields=["codigo", "caminhao", "data_expedicao", "status", "data_entrega", "recebedor_nome"]):
                romaneios[r.codigo] = {"romaneio": r.codigo, "caminhao": r.caminhao, "data_expedicao": str(r.data_expedicao or ""), "status": r.status,
                                       "data_entrega": str(r.data_entrega or ""), "recebedor": r.recebedor_nome}

    saida = []
    for p in sorted(pecas, key=lambda x: (x.obra, _natural(x.tag))):
        obra = obras.get(p.obra)
        item = {"codigo_peca": p.codigo_peca, "tag": p.tag, "obra": p.obra, "obra_nome": obra.nome_obra if obra else None,
                "cliente": (obra.cliente_nome if obra else None) or p.cliente, "produto": p.produto, "fase": _NOMES_FASES.get(int(p.fase_numero or 1)),
                "fase_numero": int(p.fase_numero or 1)}
        if "dados" in pedidas:
            item["dados"] = {"secao": p.secao, "comprimento_m": p.comprimento_m, "volume_m3": p.volume_m3, "peso_kg": p.peso_kg, "fck": p.fck or (obra.fck_padrao if obra else None),
                             "aco_kg": p.peso_aco_kg, "taxa_aco": p.taxa_aco_kg_m3, "folha": p.folha_prancha}
        if "producao" in pedidas:
            item["producao"] = {"situacao": p.status_producao, "forma_pista": p.forma_pista, "data_programada": str(p.data_programada or ""), "historico": historico.get(p.codigo_peca, []),
                                "aviso_engenharia": p.aviso_engenharia}
        if "rastreabilidade" in pedidas:
            lote = lotes.get(p.lote_concreto)
            item["rastreabilidade"] = {"lote": ({**lote, "corpos_de_prova": cps.get(lote["codigo"], [])} if lote else None),
                                       "certificados": [certificados[c] for c in [x.strip() for x in (p.corridas_aco or "").split(",") if x.strip()] if c in certificados]}
        if "qualidade" in pedidas:
            item["qualidade"] = {"inspecoes": inspecoes.get(p.codigo_peca, []), "nao_conformidades": rncs.get(p.codigo_peca, [])}
        if "ferros" in pedidas:
            try:
                item["ferros"] = json.loads(p.lista_ferros or "[]")
            except ValueError:
                item["ferros"] = []
        if "entrega" in pedidas:
            item["entrega"] = romaneios.get(p.romaneio)
        saida.append(item)

    empresa = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company") or ""
    nomes_clientes = sorted({i["cliente"] for i in saida if i["cliente"]})
    return {"success": True, "emitido_em": str(frappe.utils.now_datetime())[:16], "emitido_por": frappe.utils.get_fullname(frappe.session.user), "empresa": empresa,
            "clientes": nomes_clientes, "obras": sorted({i["obra"] for i in saida}), "secoes": pedidas, "total": len(saida), "pecas": saida,
            "resumo": {"peso_kg": round(sum(flt(p.peso_kg) for p in pecas), 1), "volume_m3": round(sum(flt(p.volume_m3) for p in pecas), 2),
                       "aco_kg": round(sum(flt(p.peso_aco_kg) for p in pecas), 1)}}
