"""Logística e montagem: ordem de montagem, carga dos caminhões, içamento com guindaste e cronograma da montagem.

A carga sai na ordem em que a obra precisa das peças (a primeira a montar vai por último no caminhão), cada caminhão
respeita peso e comprimento, o guindaste é conferido pela tabela de carga no raio de trabalho e o cronograma compara o
que estava planejado com o que foi montado."""
import json
import re
import unicodedata

import frappe
from frappe.utils import add_days, flt, getdate

BALANCO_PADRAO_M = 2.0              # quanto a peça pode passar da carroceria (balanço)
FATOR_PADRAO = 1.25                 # fator de segurança dinâmico do içamento
LIMITE_ATENCAO = 0.80
FASE_LIBERADA = 6
FASE_MONTADA = 8
ORDEM_PRODUTO = (("funda", "bloco", "estaca", "sapata"), ("pilar",), ("viga",), ("laje", "terca", "tesoura", "escada"), ("painel", "fecha"))


def _erro(texto):
    return {"success": False, "error": texto}


def _sem_acento(texto):
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or "").lower()) if unicodedata.category(c) != "Mn")


def _ordem_produto(produto):
    p = _sem_acento(produto)
    for posicao, chaves in enumerate(ORDEM_PRODUTO):
        if any(c in p for c in chaves):
            return posicao
    return len(ORDEM_PRODUTO)


def _natural(tag):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(tag or ""))]


def _ordenar(pecas):
    """Ordem de montagem: a sequência definida, depois fundação, pilar, viga, laje e painel, e por fim a numeração da tag."""
    return sorted(pecas, key=lambda p: (p.get("sequencia_montagem") or 10 ** 6, _ordem_produto(p.get("produto")), _natural(p.get("tag")), p["codigo_peca"]))


CAMPOS = ["name as codigo_peca", "tag", "produto", "peso_kg", "comprimento_m", "fase_numero", "romaneio", "sequencia_montagem", "data_montagem_prevista"]


def _pecas(obra, filtros=None):
    f = {"obra": obra, **(filtros or {})}
    return [dict(p) for p in frappe.get_all("Peca Pre-Moldada", filters=f, fields=CAMPOS)]


def definir_sequencia(obra, pecas=None):
    """Grava a ordem de montagem. `pecas` é a lista de códigos na ordem desejada; sem ela, vale a ordem padrão
    (fundação, pilar, viga, laje, painel)."""
    existentes = {p["codigo_peca"]: p for p in _pecas(obra)}
    if not existentes:
        return _erro("A obra não tem peças.")
    if pecas:
        lista = json.loads(pecas) if isinstance(pecas, str) else pecas
        faltam = [c for c in lista if c not in existentes]
        if faltam:
            return _erro("Peça(s) que não são desta obra: " + ", ".join(faltam[:5]))
        resto = [p["codigo_peca"] for p in _ordenar([p for c, p in existentes.items() if c not in set(lista)])]
        ordem = list(lista) + resto
    else:
        ordem = [p["codigo_peca"] for p in _ordenar([{**p, "sequencia_montagem": None} for p in existentes.values()])]
    for n, c in enumerate(ordem, start=1):
        frappe.db.set_value("Peca Pre-Moldada", c, "sequencia_montagem", n, update_modified=False)
    frappe.db.commit()
    return {"success": True, "pecas": len(ordem)}


# ---------------------------------------------------------------- cargas

def _caminhoes():
    saida = []
    for c in frappe.get_all("Caminhao", fields=["placa", "capacidade_kg", "comprimento_m"], order_by="capacidade_kg asc"):
        if flt(c.capacidade_kg) > 0:
            saida.append({"placa": c.placa, "capacidade_kg": flt(c.capacidade_kg), "comprimento_m": flt(c.comprimento_m)})
    return saida


def planejar_cargas(obra, pecas=None, balanco_m=None):
    if not frappe.db.exists("Obra", obra or ""):
        return _erro(f"Obra {obra} não encontrada.")
    caminhoes = _caminhoes()
    if not caminhoes:
        return _erro("Nenhum caminhão com capacidade cadastrado. Cadastre a frota em Logística > Cadastros.")
    balanco = flt(balanco_m) if balanco_m not in (None, "") else BALANCO_PADRAO_M
    prontas = _pecas(obra, {"fase_numero": FASE_LIBERADA, "romaneio": ["in", ["", None]]})
    if pecas:
        wanted = set(json.loads(pecas) if isinstance(pecas, str) else pecas)
        prontas = [p for p in prontas if p["codigo_peca"] in wanted]
    if not prontas:
        return _erro("Não há peças liberadas do pátio (fase 6) e fora de romaneio nesta obra.")
    maior = max(caminhoes, key=lambda c: c["capacidade_kg"])
    comprimentos = [c["comprimento_m"] for c in caminhoes if c["comprimento_m"]]
    limite_comp = (max(comprimentos) + balanco) if comprimentos else None
    cargas, atual, nao_atendidas = [], None, []
    for p in _ordenar(prontas):
        peso, comp = flt(p["peso_kg"]), flt(p["comprimento_m"])
        if peso > maior["capacidade_kg"]:
            nao_atendidas.append({**_resumo_peca(p), "motivo": f"Pesa {peso:g} kg e o maior caminhão leva {maior['capacidade_kg']:g} kg."})
            continue
        if limite_comp and comp > limite_comp:
            nao_atendidas.append({**_resumo_peca(p), "motivo": f"Tem {comp:g} m e a maior carroceria leva até {limite_comp:g} m (com balanço de {balanco:g} m)."})
            continue
        if atual and atual["peso"] + peso <= maior["capacidade_kg"]:
            atual["pecas"].append(p)
            atual["peso"] += peso
        else:
            atual = {"pecas": [p], "peso": peso}
            cargas.append(atual)
    saida = []
    for numero, carga in enumerate(cargas, start=1):
        comp_max = max(flt(p["comprimento_m"]) for p in carga["pecas"])
        servem = [c for c in caminhoes if c["capacidade_kg"] >= carga["peso"] and (not c["comprimento_m"] or comp_max <= c["comprimento_m"] + balanco)]
        caminhao = servem[0] if servem else maior
        from frappe.precast_sst import ativo_com_pendencia
        saida.append({"viagem": numero, "caminhao": caminhao["placa"], "aviso": ativo_com_pendencia(caminhao["placa"]), "capacidade_kg": caminhao["capacidade_kg"], "peso_kg": round(carga["peso"], 1),
                      "utilizacao_pct": round(100 * carga["peso"] / caminhao["capacidade_kg"], 1), "comprimento_max_m": round(comp_max, 2),
                      "pecas": [_resumo_peca(p) for p in carga["pecas"]],
                      "ordem_carregamento": [p["codigo_peca"] for p in reversed(carga["pecas"])]})
    return {"success": True, "obra": obra, "cargas": saida, "nao_atendidas": nao_atendidas,
            "resumo": {"viagens": len(saida), "pecas": sum(len(c["pecas"]) for c in saida), "peso_kg": round(sum(c["peso_kg"] for c in saida), 1)}}


def _resumo_peca(p):
    return {"codigo_peca": p["codigo_peca"], "tag": p["tag"], "produto": p.get("produto"), "peso_kg": flt(p["peso_kg"]),
            "comprimento_m": flt(p["comprimento_m"]), "sequencia": p.get("sequencia_montagem")}


def aplicar_cargas(obra, data_expedicao, cargas):
    """Cria um romaneio por viagem. O mesmo caminhão em mais de uma viagem sai em dias seguidos."""
    from frappe.precast_api import create_romaneio
    lista = json.loads(cargas) if isinstance(cargas, str) else cargas
    dias_por_placa, criados, falhas = {}, [], []
    for carga in lista:
        placa = carga["caminhao"]
        dias_por_placa[placa] = dias_por_placa.get(placa, -1) + 1
        data = add_days(getdate(data_expedicao), dias_por_placa[placa])
        r = create_romaneio(obra, placa, str(data), carga["ordem_carregamento"][::-1])
        if r.get("success"):
            frappe.db.set_value("Romaneio", r["codigo"], "ordem_carga", json.dumps(carga["ordem_carregamento"]))
            criados.append({"viagem": carga["viagem"], "romaneio": r["codigo"], "caminhao": placa, "data": str(data)})
        else:
            falhas.append({"viagem": carga["viagem"], "caminhao": placa, "erro": r.get("error")})
    frappe.db.commit()
    return {"success": True, "romaneios": criados, "falhas": falhas}


# ---------------------------------------------------------------- içamento

def _tabela(equip):
    try:
        linhas = json.loads(equip.get("tabela_carga") or "[]")
    except ValueError:
        linhas = []
    return sorted(({"raio_m": flt(l["raio_m"]), "capacidade_kg": flt(l["capacidade_kg"])} for l in linhas), key=lambda l: l["raio_m"])


def salvar_equipamento(nome, tipo, capacidade_max_kg, tabela_carga=None, fator_seguranca=None):
    nome = (nome or "").strip()
    if not nome:
        return _erro("Informe o nome do equipamento.")
    capacidade = flt(capacidade_max_kg)
    if capacidade <= 0:
        return _erro("Informe a capacidade máxima do equipamento em kg.")
    fator = flt(fator_seguranca) if fator_seguranca not in (None, "") else FATOR_PADRAO
    if not 1.0 <= fator <= 3.0:
        return _erro("O fator de segurança deve ficar entre 1,0 e 3,0.")
    tabela = json.loads(tabela_carga) if isinstance(tabela_carga, str) and tabela_carga.strip() else (tabela_carga or [])
    try:
        limpa = [{"raio_m": float(l["raio_m"]), "capacidade_kg": float(l["capacidade_kg"])} for l in tabela]
    except (KeyError, TypeError, ValueError):
        return _erro("A tabela de carga precisa de raio (m) e capacidade (kg) em cada linha.")
    if any(l["raio_m"] <= 0 or l["capacidade_kg"] <= 0 for l in limpa):
        return _erro("Raio e capacidade da tabela de carga devem ser maiores que zero.")
    valores = {"tipo": tipo or "Guindaste", "capacidade_max_kg": capacidade, "fator_seguranca": fator, "tabela_carga": json.dumps(limpa)}
    if frappe.db.exists("Equipamento Icamento", nome):
        frappe.db.set_value("Equipamento Icamento", nome, valores)
    else:
        frappe.get_doc({"doctype": "Equipamento Icamento", "nome": nome, **valores}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "nome": nome}


def listar_equipamentos():
    linhas = frappe.get_all("Equipamento Icamento", fields=["nome", "tipo", "capacidade_max_kg", "fator_seguranca", "tabela_carga"], order_by="nome asc")
    for l in linhas:
        l["tabela_carga"] = _tabela(l)
    return linhas


def excluir_equipamento(nome):
    if not frappe.db.exists("Equipamento Icamento", nome or ""):
        return _erro("Equipamento não encontrado.")
    frappe.delete_doc("Equipamento Icamento", nome, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"success": True}


def _capacidade_no_raio(equip, raio):
    tabela = _tabela(equip)
    if not tabela:
        return flt(equip["capacidade_max_kg"]), False
    for linha in tabela:
        if linha["raio_m"] >= raio:
            return linha["capacidade_kg"], True        # a linha de raio maior ou igual: lado conservador
    return 0.0, True                                    # além do alcance da tabela


def _raio_maximo(equip, carga_kg):
    tabela = _tabela(equip)
    if not tabela:
        return None
    ok = [l["raio_m"] for l in tabela if l["capacidade_kg"] >= carga_kg]
    return max(ok) if ok else 0.0


def plano_icamento(obra, equipamento, raio_m):
    equip = frappe.db.get_value("Equipamento Icamento", equipamento or "", ["nome", "tipo", "capacidade_max_kg", "fator_seguranca", "tabela_carga"], as_dict=True)
    if not equip:
        return _erro("Equipamento de içamento não encontrado.")
    raio = flt(raio_m)
    if raio <= 0:
        return _erro("Informe o raio de trabalho do guindaste em metros.")
    pecas = _pecas(obra)
    if not pecas:
        return _erro("A obra não tem peças.")
    fator = flt(equip.fator_seguranca) or FATOR_PADRAO
    capacidade, tem_tabela = _capacidade_no_raio(equip, raio)
    linhas = []
    for p in pecas:
        carga = flt(p["peso_kg"]) * fator
        util = (carga / capacidade) if capacidade else 9.99
        estado = "ok" if util < LIMITE_ATENCAO else "atencao" if util <= 1.0 else "nao"
        linhas.append({"codigo_peca": p["codigo_peca"], "tag": p["tag"], "produto": p.get("produto"), "peso_kg": flt(p["peso_kg"]),
                       "carga_com_fator_kg": round(carga, 1), "utilizacao_pct": round(min(util, 9.99) * 100, 1), "estado": estado,
                       "raio_maximo_m": _raio_maximo(equip, carga)})
    linhas.sort(key=lambda l: -l["utilizacao_pct"])
    contagem = {e: sum(1 for l in linhas if l["estado"] == e) for e in ("ok", "atencao", "nao")}
    from frappe.precast_sst import ativo_com_pendencia
    avisos = [ativo_com_pendencia(equip.nome)] if ativo_com_pendencia(equip.nome) else []
    if not tem_tabela:
        avisos.append("O equipamento não tem tabela de carga: o plano usa a capacidade máxima, que só vale no menor raio. Cadastre a tabela do fabricante.")
    if capacidade == 0:
        avisos.append(f"O raio de {raio:g} m passa do alcance da tabela de carga do equipamento.")
    return {"success": True, "obra": obra, "equipamento": equip.nome, "raio_m": raio, "fator_seguranca": fator,
            "capacidade_no_raio_kg": capacidade, "pecas": linhas, "resumo": contagem, "avisos": avisos}


# ---------------------------------------------------------------- cronograma

def _data_montagem(codigo_peca):
    quando = frappe.db.get_value("Fase Historico", {"codigo_peca": codigo_peca, "fase_nova": FASE_MONTADA}, "data_hora", order_by="data_hora desc")
    return getdate(quando) if quando else None


def cronograma(obra, data_inicio=None, pecas_por_dia=None, aplicar=False):
    """Compara o planejado com o montado. Com `data_inicio` e `pecas_por_dia`, calcula (e, com `aplicar`, grava) as datas
    previstas pela ordem de montagem; sem eles, usa as datas já gravadas."""
    pecas = _ordenar(_pecas(obra))
    if not pecas:
        return _erro("A obra não tem peças.")
    hoje = getdate()
    if data_inicio and pecas_por_dia:
        try:
            ritmo = max(1, int(float(pecas_por_dia)))
        except ValueError:
            return _erro("Informe quantas peças a equipe monta por dia.")
        from frappe.precast_patio import configuracao
        sabado = configuracao()["trabalha_sabado"]
        dia, usados = getdate(data_inicio), 0
        for p in pecas:
            while dia.weekday() == 6 or (dia.weekday() == 5 and not sabado):
                dia = add_days(dia, 1)
            p["data_montagem_prevista"] = dia
            usados += 1
            if usados >= ritmo:
                dia, usados = add_days(dia, 1), 0
        if str(aplicar).lower() in ("1", "true", "sim"):
            for n, p in enumerate(pecas, start=1):
                frappe.db.set_value("Peca Pre-Moldada", p["codigo_peca"], {"data_montagem_prevista": p["data_montagem_prevista"], "sequencia_montagem": p.get("sequencia_montagem") or n},
                                    update_modified=False)
            frappe.db.commit()
    planejadas = {p["codigo_peca"]: getdate(p["data_montagem_prevista"]) for p in pecas if p.get("data_montagem_prevista")}
    if not planejadas:
        return _erro("A obra ainda não tem datas de montagem. Informe a data de início e o ritmo da equipe.")
    realizadas = {p["codigo_peca"]: _data_montagem(p["codigo_peca"]) for p in pecas if int(p["fase_numero"] or 1) >= FASE_MONTADA}
    realizadas = {c: d or hoje for c, d in realizadas.items()}
    inicio = min(list(planejadas.values()) + list(realizadas.values()))
    fim = max(list(planejadas.values()) + list(realizadas.values()) + [hoje])
    serie, dia = [], inicio
    while dia <= fim and len(serie) < 800:
        serie.append({"data": dia.isoformat(), "planejado": sum(1 for d in planejadas.values() if d <= dia),
                      "realizado": sum(1 for d in realizadas.values() if d <= dia) if dia <= hoje else None})
        dia = add_days(dia, 1)
    planejado_hoje = sum(1 for d in planejadas.values() if d <= hoje)
    atrasadas = [{"codigo_peca": p["codigo_peca"], "tag": p["tag"], "prevista": planejadas[p["codigo_peca"]].isoformat(), "dias_atraso": (hoje - planejadas[p["codigo_peca"]]).days,
                  "fase": int(p["fase_numero"] or 1)}
                 for p in pecas if p["codigo_peca"] in planejadas and p["codigo_peca"] not in realizadas and planejadas[p["codigo_peca"]] < hoje]
    previsao = None
    if realizadas:
        decorridos = max(1, (hoje - min(realizadas.values())).days + 1)
        faltam = len(pecas) - len(realizadas)
        ritmo_real = len(realizadas) / decorridos
        previsao = (add_days(hoje, int(round(faltam / ritmo_real))).isoformat() if faltam else hoje.isoformat()) if ritmo_real else None
    return {"success": True, "obra": obra, "serie": serie, "atrasadas": sorted(atrasadas, key=lambda a: -a["dias_atraso"]),
            "resumo": {"pecas": len(pecas), "planejadas_ate_hoje": planejado_hoje, "montadas": len(realizadas), "desvio": len(realizadas) - planejado_hoje,
                       "termino_planejado": max(planejadas.values()).isoformat(), "termino_previsto": previsao}}
