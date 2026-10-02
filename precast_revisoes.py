"""Revisões de projeto: compara o desenho que chegou (R0e, R0h...) com as peças da obra, diz o que mudou em cada
peça e o que isso causa na produção que já andou, e guarda o histórico de revisões da obra."""
import json

import frappe
from frappe.utils import now_datetime

TOL_COMPRIMENTO_M = 0.005
TOL_VOLUME_M3 = 0.005
TOL_ACO_KG = 0.05
FASE_FORMA_PRONTA = 3        # forma e embutidos feitos
FASE_CONCRETADO = 4
FASE_LIBERADA = 6

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _chave_no_sistema(cod_obra, cod):
    """A mesma regra da gravação: o código de outra obra ganha o prefixo desta."""
    dono = frappe.db.get_value("Peca Pre-Moldada", cod, "obra")
    return f"{cod_obra}-{cod}" if dono and dono != cod_obra else cod


def _ferros_normalizados(ferros):
    saida = []
    for f in ferros or []:
        saida.append((str(f.get("posicao", "")).strip(), round(_num(f.get("bitola_mm")), 1), int(_num(f.get("quantidade"))),
                      round(_num(f.get("comp_unit_m")), 2)))
    return sorted(saida)


def _carregar_ferros(texto):
    try:
        return json.loads(texto or "[]")
    except ValueError:
        return []


def _mudancas(nova, atual):
    """Campos que mudaram entre a peça lida do desenho (nova) e a gravada (atual)."""
    saida = []
    sn, sa = str(nova.get("secao") or "").upper().replace(" ", ""), str(atual.secao or "").upper().replace(" ", "")
    if sn and sa and sn != sa:
        saida.append({"campo": "secao", "rotulo": "Seção", "de": f"{atual.secao} cm", "para": f"{nova.get('secao')} cm"})
    if abs(_num(nova.get("comp")) - _num(atual.comprimento_m)) > TOL_COMPRIMENTO_M and _num(nova.get("comp")):
        saida.append({"campo": "comprimento", "rotulo": "Comprimento", "de": f"{_num(atual.comprimento_m):g} m", "para": f"{_num(nova.get('comp')):g} m"})
    if abs(_num(nova.get("vol")) - _num(atual.volume_m3)) > TOL_VOLUME_M3 and _num(nova.get("vol")):
        saida.append({"campo": "volume", "rotulo": "Volume", "de": f"{_num(atual.volume_m3):g} m³", "para": f"{_num(nova.get('vol')):g} m³"})
    if nova.get("fonte") == "prancha":                      # só a prancha traz o aço de verdade
        if abs(_num(nova.get("peso_aco_kg")) - _num(atual.peso_aco_kg)) > TOL_ACO_KG:
            saida.append({"campo": "aco", "rotulo": "Aço", "de": f"{_num(atual.peso_aco_kg):g} kg", "para": f"{_num(nova.get('peso_aco_kg')):g} kg"})
        novos, antigos = _ferros_normalizados(nova.get("ferros")), _ferros_normalizados(_carregar_ferros(atual.lista_ferros))
        if novos != antigos and (novos or antigos):
            difer = len(set(novos) ^ set(antigos))
            saida.append({"campo": "ferros", "rotulo": "Lista de ferros", "de": f"{len(antigos)} posição(ões)",
                          "para": f"{len(novos)} posição(ões), {difer} linha(s) diferente(s)"})
    return saida


def _impacto(atual, mudancas, tem_historico):
    """O que a mudança causa numa peça que já andou na fábrica."""
    fase = int(atual.fase_numero or 1)
    entregue = bool(atual.get("romaneio"))
    campos = {m["campo"] for m in mudancas}
    mexe_na_forma = bool(campos & {"secao", "comprimento", "volume"})
    mexe_no_aco = bool(campos & {"aco", "ferros"})
    acoes = []
    if fase <= 1 and not tem_historico:
        return {"nivel": "nenhum", "fase": fase, "acoes": ["Ainda não começou: a peça já fica com o desenho novo."]}
    if mexe_no_aco:
        acoes.append("Aço: o corte e a armação seguem a lista antiga. Refazer o que já foi cortado ou armado." if fase >= 2
                     else "Corte e dobra em andamento: avisar o setor para usar a lista nova.")
    if mexe_na_forma:
        if fase >= FASE_CONCRETADO:
            acoes.append("A peça já foi concretada com a medida antiga. Abrir uma não conformidade e decidir entre refazer e aceitar.")
        elif fase >= FASE_FORMA_PRONTA:
            acoes.append("A forma já está montada com a medida antiga: ajustar a forma antes de concretar.")
        else:
            acoes.append("Avisar a armação e a forma da nova medida antes de seguir.")
    if entregue or fase >= FASE_LIBERADA:
        acoes.append("Peça pronta ou já expedida com o desenho antigo: avaliar retrabalho ou troca com a engenharia.")
        nivel = "critico"
    elif mexe_na_forma and fase >= FASE_CONCRETADO:
        nivel = "critico"
    else:
        nivel = "atencao"
    return {"nivel": nivel, "fase": fase, "acoes": acoes}


def comparar(cod_obra, pieces_data):
    """Compara as peças lidas com as gravadas na obra. Não grava nada."""
    gravadas = {p.name: p for p in frappe.get_all(
        "Peca Pre-Moldada", filters={"obra": cod_obra},
        fields=["name", "tag", "secao", "comprimento_m", "volume_m3", "peso_aco_kg", "lista_ferros", "fase_numero", "romaneio",
                "lote_concreto", "corridas_aco"])}
    novas, alteradas, iguais, vistas = [], [], [], set()
    for p in pieces_data:
        cod = (p.get("cod") or "").strip()
        if not cod:
            continue
        chave = _chave_no_sistema(cod_obra, cod)
        vistas.add(chave)
        atual = gravadas.get(chave)
        if not atual:
            novas.append({"codigo": chave, "tag": p.get("tag") or cod, "secao": p.get("secao"), "comprimento_m": p.get("comp")})
            continue
        mud = _mudancas(p, atual)
        if not mud:
            iguais.append(chave)
            continue
        historico = bool(frappe.db.exists("Fase Historico", {"codigo_peca": chave}) or frappe.db.exists("Checklist Qualidade", {"codigo_peca": chave}))
        alteradas.append({"codigo": chave, "tag": atual.tag or chave, "mudancas": mud, "impacto": _impacto(atual, mud, historico)})
    ausentes = []
    for nome, atual in gravadas.items():
        if nome in vistas:
            continue
        historico = bool(frappe.db.exists("Fase Historico", {"codigo_peca": nome}) or frappe.db.exists("Checklist Qualidade", {"codigo_peca": nome}))
        andou = int(atual.fase_numero or 1) > 1 or historico
        ausentes.append({"codigo": nome, "tag": atual.tag or nome, "fase": int(atual.fase_numero or 1), "ja_andou": andou})
    por_nivel = {n: sum(1 for a in alteradas if a["impacto"]["nivel"] == n) for n in ("nenhum", "atencao", "critico")}
    return {"novas": novas, "alteradas": alteradas, "iguais": len(iguais), "ausentes": ausentes,
            "resumo": {"novas": len(novas), "alteradas": len(alteradas), "iguais": len(iguais), "ausentes": len(ausentes),
                       "ausentes_com_producao": sum(1 for a in ausentes if a["ja_andou"]),
                       "atencao": por_nivel["atencao"], "critico": por_nivel["critico"]}}


def _texto_aviso(revisao, item):
    partes = "; ".join(f"{m['rotulo'].lower()} {m['de']} → {m['para']}" for m in item["mudancas"])
    return f"Revisão {revisao or 'nova'}: {partes}. " + " ".join(item["impacto"]["acoes"])


def aplicar(cod_obra, revisao, arquivo, modo, diff):
    """Depois da gravação: avisa as peças que já andaram e registra a revisão no histórico da obra."""
    for item in diff["alteradas"]:
        if item["impacto"]["nivel"] != "nenhum":
            frappe.db.set_value("Peca Pre-Moldada", item["codigo"], "aviso_engenharia", _texto_aviso(revisao, item)[:900], update_modified=False)
    numero = frappe.db.count("Revisao Projeto", {"obra": cod_obra}) + 1
    registro = {"alteradas": diff["alteradas"][:200], "novas": diff["novas"][:200], "ausentes": diff["ausentes"][:200]}
    frappe.get_doc({
        "doctype": "Revisao Projeto", "obra": cod_obra, "numero": numero, "revisao": revisao or "sem identificação",
        "arquivo": arquivo, "modo": modo, "data_hora": now_datetime(), "usuario": frappe.utils.get_fullname(frappe.session.user),
        "resumo": json.dumps(diff["resumo"], ensure_ascii=False), "diff": json.dumps(registro, ensure_ascii=False),
    }).insert(ignore_permissions=True)
    return numero


def listar(cod_obra):
    linhas = frappe.get_all("Revisao Projeto", filters={"obra": cod_obra}, order_by="numero desc",
                            fields=["numero", "revisao", "arquivo", "modo", "data_hora", "usuario", "resumo", "diff"])
    for linha in linhas:
        for campo in ("resumo", "diff"):
            try:
                linha[campo] = json.loads(linha[campo] or "{}")
            except ValueError:
                linha[campo] = {}
    return linhas
