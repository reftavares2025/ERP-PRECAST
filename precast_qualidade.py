"""Rastreabilidade da peça: lote de concreto, corpos de prova, certificados do aço e o RG de cada peça.

O RG junta o que o sistema sabe de uma peça (projeto, fases com quem e quando, inspeções, concreto, aço, não
conformidades, expedição) e diz, item por item, se a documentação está completa. Com a exigência ligada, a peça
só entra num romaneio com o RG completo."""
import json

import frappe
from frappe.utils import flt, getdate, now_datetime

IDADE_REFERENCIA_DIAS = 28        # a resistência do projeto vale aos 28 dias
FASE_CONCRETADO = 4
FASE_LIBERADA = 6
CHAVE_EXIGIR_RG = "exigir_rg_expedicao"


def _erro(texto):
    return {"success": False, "error": texto}


def _lista(valor):
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except ValueError:
            valor = valor.split(",")
    return [str(v).strip() for v in (valor or []) if str(v).strip()]


def exigir_rg_para_expedir():
    return str(frappe.defaults.get_global_default(CHAVE_EXIGIR_RG) or "0") == "1"


def definir_exigir_rg(exigir):
    frappe.defaults.set_global_default(CHAVE_EXIGIR_RG, "1" if exigir else "0")


# ---------------------------------------------------------------- concreto

def status_do_lote(codigo):
    """Aguardando ruptura / Em ensaio (ainda sem 28 dias) / Aprovado / Reprovado."""
    cps = frappe.get_all("Corpo Prova", filters={"lote": codigo}, fields=["idade_dias", "resultado"])
    if not cps:
        return "Aguardando ruptura"
    de_referencia = [c for c in cps if (c.idade_dias or 0) >= IDADE_REFERENCIA_DIAS]
    if not de_referencia:
        return "Em ensaio"
    return "Aprovado" if all(c.resultado == "Aprovado" for c in de_referencia) else "Reprovado"


def registrar_lote(codigo, fck_especificado, data_concretagem=None, usina=None, traco=None, slump_cm=None,
                   temperatura_c=None, volume_m3=None, nota_fiscal=None, observacoes=None):
    codigo = (codigo or "").strip()
    if not codigo:
        return _erro("Informe o código do lote.")
    if frappe.db.exists("Lote Concreto", codigo):
        return _erro(f"O lote {codigo} já está cadastrado.")
    fck = flt(fck_especificado)
    if fck <= 0:
        return _erro("Informe o fck especificado do lote em MPa (maior que zero).")
    if data_concretagem and getdate(data_concretagem) > getdate():
        return _erro("A data da concretagem não pode ser no futuro.")
    frappe.get_doc({
        "doctype": "Lote Concreto", "codigo": codigo, "fck_especificado": fck,
        "data_concretagem": data_concretagem or getdate(), "usina": usina, "traco": traco,
        "slump_cm": flt(slump_cm) if slump_cm not in (None, "") else None,
        "temperatura_c": flt(temperatura_c) if temperatura_c not in (None, "") else None,
        "volume_m3": flt(volume_m3) if volume_m3 not in (None, "") else None,
        "nota_fiscal": nota_fiscal, "observacoes": observacoes,
        "registrado_por": frappe.utils.get_fullname(frappe.session.user),
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "codigo": codigo}


def listar_lotes(limite=300):
    lotes = frappe.get_all("Lote Concreto", order_by="data_concretagem desc, creation desc", limit=int(limite),
                           fields=["codigo", "data_concretagem", "usina", "traco", "fck_especificado", "slump_cm",
                                   "temperatura_c", "volume_m3", "nota_fiscal", "observacoes", "registrado_por"])
    pecas = {}
    for lote_da_peca in frappe.get_all("Peca Pre-Moldada", filters={"lote_concreto": ["is", "set"]}, pluck="lote_concreto"):
        pecas[lote_da_peca] = pecas.get(lote_da_peca, 0) + 1
    cps = frappe.get_all("Corpo Prova", fields=["lote", "idade_dias", "fck_obtido", "resultado", "data_ruptura"],
                         order_by="idade_dias asc")
    por_lote = {}
    for c in cps:
        por_lote.setdefault(c.lote, []).append(c)
    for lote in lotes:
        lote["pecas"] = pecas.get(lote.codigo, 0)
        lote["corpos_de_prova"] = por_lote.get(lote.codigo, [])
        lote["status"] = status_do_lote(lote.codigo)
    return lotes


def registrar_corpo_de_prova(lote, idade_dias, fck_obtido, data_ruptura=None, carga_kn=None, responsavel=None):
    if not frappe.db.exists("Lote Concreto", lote or ""):
        return _erro(f"Lote {lote} não encontrado.")
    try:
        idade = int(idade_dias)
    except (TypeError, ValueError):
        return _erro("Informe a idade do corpo de prova em dias.")
    if not 1 <= idade <= 365:
        return _erro("A idade do corpo de prova deve ficar entre 1 e 365 dias.")
    obtido = flt(fck_obtido)
    if obtido <= 0:
        return _erro("Informe a resistência obtida em MPa (maior que zero).")
    exigido = flt(frappe.db.get_value("Lote Concreto", lote, "fck_especificado"))
    if idade < IDADE_REFERENCIA_DIAS:
        resultado = "Parcial"
    else:
        resultado = "Aprovado" if obtido >= exigido else "Reprovado"
    frappe.get_doc({
        "doctype": "Corpo Prova", "lote": lote, "idade_dias": idade, "fck_obtido": obtido, "fck_especificado": exigido,
        "data_ruptura": data_ruptura or getdate(), "carga_kn": flt(carga_kn) if carga_kn not in (None, "") else None,
        "resultado": resultado, "responsavel": responsavel or frappe.utils.get_fullname(frappe.session.user),
    }).insert(ignore_permissions=True)
    abertas = _abrir_rnc_do_lote(lote, obtido, exigido) if resultado == "Reprovado" else 0
    frappe.db.commit()
    mensagem = {"Parcial": f"Ruptura aos {idade} dias registrada. A resistência vale aos {IDADE_REFERENCIA_DIAS} dias.",
                "Aprovado": f"Lote {lote} aprovado: {obtido:g} MPa ≥ {exigido:g} MPa.",
                "Reprovado": f"Lote {lote} reprovado: {obtido:g} MPa < {exigido:g} MPa. "
                             f"{abertas} peça(s) ficaram com não conformidade aberta."}[resultado]
    return {"success": True, "resultado": resultado, "status_do_lote": status_do_lote(lote),
            "rnc_abertas": abertas, "message": mensagem}


def _abrir_rnc_do_lote(lote, obtido, exigido):
    """Lote reprovado aos 28 dias: cada peça concretada com ele ganha uma não conformidade (e não sai da fábrica)."""
    descricao = f"Lote de concreto {lote} reprovado: {obtido:g} MPa obtidos, {exigido:g} MPa exigidos."
    abertas = 0
    for peca in frappe.get_all("Peca Pre-Moldada", filters={"lote_concreto": lote}, pluck="name"):
        if frappe.db.exists("Nao Conformidade", {"codigo_peca": peca, "descricao": ["like", f"Lote de concreto {lote} reprovado%"],
                                                 "status": ["!=", "Aprovada"]}):
            continue
        frappe.get_doc({"doctype": "Nao Conformidade", "codigo_peca": peca, "descricao": descricao, "status": "Aberta",
                        "aberto_por": frappe.utils.get_fullname(frappe.session.user),
                        "data_abertura": now_datetime()}).insert(ignore_permissions=True)
        abertas += 1
    return abertas


def vincular_lote(lote, pecas):
    if not frappe.db.exists("Lote Concreto", lote or ""):
        return _erro(f"Lote {lote} não encontrado.")
    codigos = _lista(pecas)
    if not codigos:
        return _erro("Escolha ao menos uma peça.")
    if status_do_lote(lote) == "Reprovado":
        return _erro(f"O lote {lote} está reprovado e não pode ser ligado a novas peças.")
    inexistentes = [c for c in codigos if not frappe.db.exists("Peca Pre-Moldada", c)]
    if inexistentes:
        return _erro("Peça(s) não encontrada(s): " + ", ".join(inexistentes[:5]))
    trocadas = 0
    for c in codigos:
        anterior = frappe.db.get_value("Peca Pre-Moldada", c, "lote_concreto")
        if anterior and anterior != lote:
            trocadas += 1
        frappe.db.set_value("Peca Pre-Moldada", c, "lote_concreto", lote, update_modified=False)
    frappe.db.commit()
    return {"success": True, "vinculadas": len(codigos), "trocadas": trocadas}


# ---------------------------------------------------------------- aço

def registrar_certificado(corrida, bitola_mm, fabricante=None, norma=None, data_recebimento=None,
                          nota_fiscal=None, certificado_anexo=None):
    corrida = (corrida or "").strip()
    if not corrida:
        return _erro("Informe a corrida (lote) do aço.")
    if frappe.db.exists("Certificado Aco", corrida):
        return _erro(f"A corrida {corrida} já está cadastrada.")
    bitola = flt(bitola_mm)
    if bitola <= 0:
        return _erro("Informe a bitola do aço em mm (maior que zero).")
    frappe.get_doc({
        "doctype": "Certificado Aco", "corrida": corrida, "bitola_mm": bitola, "fabricante": fabricante,
        "norma": norma or "CA-50", "data_recebimento": data_recebimento or getdate(), "nota_fiscal": nota_fiscal,
        "certificado_anexo": certificado_anexo, "registrado_por": frappe.utils.get_fullname(frappe.session.user),
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "corrida": corrida}


def listar_certificados(limite=300):
    certificados = frappe.get_all("Certificado Aco", order_by="data_recebimento desc, creation desc", limit=int(limite),
                                  fields=["corrida", "bitola_mm", "fabricante", "norma", "data_recebimento",
                                          "nota_fiscal", "certificado_anexo"])
    uso = {}
    for linha in frappe.get_all("Peca Pre-Moldada", filters={"corridas_aco": ["is", "set"]}, fields=["corridas_aco"]):
        for corrida in _lista(linha.corridas_aco):
            uso[corrida] = uso.get(corrida, 0) + 1
    for c in certificados:
        c["pecas"] = uso.get(c.corrida, 0)
    return certificados


def vincular_corridas(pecas, corridas):
    codigos, corridas = _lista(pecas), _lista(corridas)
    if not codigos or not corridas:
        return _erro("Escolha ao menos uma peça e uma corrida de aço.")
    faltam = [c for c in corridas if not frappe.db.exists("Certificado Aco", c)]
    if faltam:
        return _erro("Corrida(s) sem certificado cadastrado: " + ", ".join(faltam[:5]))
    inexistentes = [c for c in codigos if not frappe.db.exists("Peca Pre-Moldada", c)]
    if inexistentes:
        return _erro("Peça(s) não encontrada(s): " + ", ".join(inexistentes[:5]))
    for c in codigos:
        atuais = _lista(frappe.db.get_value("Peca Pre-Moldada", c, "corridas_aco"))
        novas = atuais + [x for x in corridas if x not in atuais]
        frappe.db.set_value("Peca Pre-Moldada", c, "corridas_aco", ", ".join(novas), update_modified=False)
    frappe.db.commit()
    return {"success": True, "vinculadas": len(codigos)}


# ---------------------------------------------------------------- RG da peça

def _item(nome, estado, detalhe):
    return {"item": nome, "estado": estado, "detalhe": detalhe}   # estado: ok | pendente | falha


def _conferencias(peca, fase, lote, status_lote, corridas, certificados, inspecoes, rncs_abertas):
    itens = []
    ultimas = {}
    for i in inspecoes:                      # a inspeção mais recente de cada etapa vale
        ultimas.setdefault(i["etapa"], i)
    reprovadas = [e for e, i in ultimas.items() if not i["aprovado"]]
    if reprovadas:
        itens.append(_item("Inspeções de qualidade", "falha", "Reprovada em: " + ", ".join(reprovadas)))
    elif ultimas:
        itens.append(_item("Inspeções de qualidade", "ok", f"{len(ultimas)} etapa(s) inspecionada(s) e aprovada(s)"))
    else:
        itens.append(_item("Inspeções de qualidade", "pendente", "Nenhuma inspeção registrada"))

    if lote:
        itens.append(_item("Lote de concreto", "ok", f"Lote {lote}"))
    else:
        itens.append(_item("Lote de concreto", "falha" if fase >= FASE_CONCRETADO else "pendente",
                           "Nenhum lote ligado à peça"))
    estado = {"Aprovado": "ok", "Reprovado": "falha"}.get(status_lote, "pendente")
    itens.append(_item("Resistência do concreto (28 dias)", estado,
                       status_lote if lote else "Depende do lote de concreto"))

    if corridas:
        itens.append(_item("Certificado do aço", "ok", "Corrida(s): " + ", ".join(corridas)))
        necessarias = {round(flt(f.get("bitola_mm")), 1) for f in peca["ferros"] if f.get("bitola_mm")}
        presentes = {round(flt(c["bitola_mm"]), 1) for c in certificados}
        sem_certificado = sorted(necessarias - presentes)
        if sem_certificado:
            itens.append(_item("Bitolas cobertas pelos certificados", "falha",
                               "Sem certificado para " + ", ".join(f"{b:g} mm" for b in sem_certificado)))
        elif necessarias:
            itens.append(_item("Bitolas cobertas pelos certificados", "ok", ", ".join(f"{b:g} mm" for b in sorted(necessarias))))
    else:
        itens.append(_item("Certificado do aço", "pendente" if fase < 2 else "falha", "Nenhuma corrida ligada à peça"))

    itens.append(_item("Não conformidades", "falha" if rncs_abertas else "ok",
                       f"{rncs_abertas} aberta(s)" if rncs_abertas else "Nenhuma aberta"))
    itens.append(_item("Fabricação concluída", "ok" if fase >= FASE_LIBERADA else "pendente",
                       "Liberada pelo pátio" if fase >= FASE_LIBERADA else f"Fase {fase} de {FASE_LIBERADA}"))
    return itens


def rg_da_peca(codigo_peca):
    if not frappe.db.exists("Peca Pre-Moldada", codigo_peca or ""):
        return _erro(f"Peça {codigo_peca} não encontrada.")
    from frappe.precast_api import _NOMES_FASES
    doc = frappe.get_doc("Peca Pre-Moldada", codigo_peca)
    fase = int(doc.fase_numero or 1)
    try:
        ferros = json.loads(doc.get("lista_ferros") or "[]")
    except ValueError:
        ferros = []
    obra = frappe.db.get_value("Obra", doc.obra, ["nome_obra", "fck_padrao"], as_dict=True) if doc.obra else None

    fases = [{"fase": _NOMES_FASES.get(h.fase_nova, str(h.fase_nova)), "data_hora": h.data_hora, "usuario": h.usuario,
              "forma_pista": h.forma_pista}
             for h in frappe.get_all("Fase Historico", filters={"codigo_peca": codigo_peca}, order_by="data_hora asc",
                                     fields=["fase_nova", "data_hora", "usuario", "forma_pista"])]
    inspecoes = frappe.get_all("Checklist Qualidade", filters={"codigo_peca": codigo_peca}, order_by="data_inspecao desc",
                               fields=["etapa", "aprovado", "inspetor", "data_inspecao", "observacoes", "fck_corpo_prova"])
    rncs = frappe.get_all("Nao Conformidade", filters={"codigo_peca": codigo_peca}, order_by="data_abertura desc",
                          fields=["name", "descricao", "status", "data_abertura", "aberto_por"])

    lote_codigo = doc.get("lote_concreto")
    lote = None
    status_lote = None
    if lote_codigo and frappe.db.exists("Lote Concreto", lote_codigo):
        lote = frappe.db.get_value("Lote Concreto", lote_codigo, ["codigo", "data_concretagem", "usina", "traco",
                                   "fck_especificado", "slump_cm", "temperatura_c", "volume_m3", "nota_fiscal"], as_dict=True)
        lote["corpos_de_prova"] = frappe.get_all("Corpo Prova", filters={"lote": lote_codigo}, order_by="idade_dias asc",
                                                 fields=["idade_dias", "fck_obtido", "resultado", "data_ruptura", "responsavel"])
        status_lote = status_do_lote(lote_codigo)

    corridas = _lista(doc.get("corridas_aco"))
    certificados = [frappe.db.get_value("Certificado Aco", c, ["corrida", "bitola_mm", "fabricante", "norma",
                    "data_recebimento", "nota_fiscal", "certificado_anexo"], as_dict=True)
                    for c in corridas if frappe.db.exists("Certificado Aco", c)]

    romaneio = None
    if doc.get("romaneio"):
        romaneio = frappe.db.get_value("Romaneio", doc.romaneio, ["codigo", "caminhao", "motorista", "data_expedicao", "status"], as_dict=True)

    base = {"ferros": ferros}
    conferencias = _conferencias(base, fase, lote_codigo, status_lote, corridas, certificados, inspecoes,
                                 sum(1 for r in rncs if r.status != "Aprovada"))
    return {
        "success": True,
        "peca": {"codigo_peca": doc.codigo_peca, "tag": doc.tag, "obra": doc.obra, "obra_nome": obra.nome_obra if obra else None,
                 "produto": doc.produto, "secao": doc.secao, "comprimento_m": doc.comprimento_m, "volume_m3": doc.get("volume_m3"),
                 "peso_kg": doc.peso_kg, "fck": doc.fck or (obra.fck_padrao if obra else None), "fase_numero": fase,
                 "fase": _NOMES_FASES.get(fase, str(fase)), "prancha_url": doc.prancha_url, "print_url": doc.print_url,
                 "folha_prancha": doc.get("folha_prancha"), "aco_kg": doc.get("peso_aco_kg")},
        "conferencias": conferencias,
        "completo": all(c["estado"] == "ok" for c in conferencias),
        "fases": fases, "inspecoes": inspecoes, "lote": lote, "status_do_lote": status_lote,
        "certificados": certificados, "nao_conformidades": rncs, "romaneio": romaneio,
        "emitido_em": now_datetime(),
    }


def pecas_sem_rg_completo(codigos):
    """Para o romaneio: peças cujo RG não está completo, com o primeiro motivo de cada uma."""
    saida = []
    for c in codigos:
        rg = rg_da_peca(c)
        if not rg.get("success"):
            continue
        # a fase 6 é exigida pelo próprio romaneio; aqui vale a documentação
        pendentes = [i for i in rg["conferencias"] if i["estado"] != "ok" and i["item"] != "Fabricação concluída"]
        if pendentes:
            saida.append(f"{c} ({pendentes[0]['item']}: {pendentes[0]['detalhe']})")
    return saida


def resumo():
    """Tudo o que a aba Qualidade precisa numa chamada."""
    return {"success": True, "lotes": listar_lotes(), "certificados": listar_certificados(),
            "exigir_rg_expedicao": exigir_rg_para_expedir()}
