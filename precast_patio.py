"""Planejamento de pátio e formas: quanto cada forma ou pista comporta, quando fica livre (ciclo de cura), a
programação sugerida das peças e a liberação da desforma pela resistência do concreto.

Cada forma tem um ciclo em dias: a peça programada no dia D ocupa a forma de D até D + ciclo - 1. Uma fôrma comporta
uma peça por ciclo; uma pista de protensão comporta peças enquanto a soma dos comprimentos (e do peso) couber; uma mesa
vibratória, enquanto a soma dos pesos couber."""
import math
import re
from datetime import timedelta

import frappe
from frappe.utils import add_days, flt, getdate, now_datetime

CICLO_PADRAO_DIAS = 1.0
DESFORMA_PCT_PADRAO = 70.0          # a desforma libera com 70% do fck (resistência de desforma)
HORIZONTE_DIAS = 60
CHAVES = {"desforma_pct_fck": "patio_desforma_pct_fck", "trabalha_sabado": "patio_trabalha_sabado"}
FASE_CONCRETADO = 4
FASE_DESMOLDADA = 5


def _erro(texto):
    return {"success": False, "error": texto}


def configuracao(desforma_pct_fck=None, trabalha_sabado=None):
    if desforma_pct_fck not in (None, ""):
        try:
            pct = float(str(desforma_pct_fck).replace(",", "."))
        except ValueError:
            return _erro("Informe a resistência de desforma em porcentagem do fck.")
        if not 30 <= pct <= 100:
            return _erro("A resistência de desforma deve ficar entre 30% e 100% do fck.")
        frappe.defaults.set_global_default(CHAVES["desforma_pct_fck"], str(pct))
    if trabalha_sabado not in (None, ""):
        frappe.defaults.set_global_default(CHAVES["trabalha_sabado"], "1" if str(trabalha_sabado).lower() in ("1", "true", "sim") else "0")
    pct_salvo = frappe.defaults.get_global_default(CHAVES["desforma_pct_fck"])
    sabado = frappe.defaults.get_global_default(CHAVES["trabalha_sabado"])
    return {"success": True, "desforma_pct_fck": float(pct_salvo) if pct_salvo else DESFORMA_PCT_PADRAO,
            "trabalha_sabado": True if sabado is None else str(sabado) == "1"}


def _num(valor):
    try:
        return float(re.sub(r"[^0-9.,]", "", str(valor)).replace(",", "."))
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- desforma

def desforma_liberada(codigo_peca, fck_exigido):
    """(liberada, explicação). Vale o corpo de prova da própria peça com o fck cheio (regra antiga) ou o lote de
    concreto da peça com a resistência de desforma (porcentagem do fck) em qualquer idade."""
    exigido = _num(fck_exigido)
    for c in frappe.get_all("Checklist Qualidade", filters={"codigo_peca": codigo_peca, "aprovado": 1}, fields=["fck_corpo_prova"]):
        if _num(c.fck_corpo_prova) and _num(c.fck_corpo_prova) >= exigido:
            return True, "corpo de prova da peça aprovado"
    lote = frappe.db.get_value("Peca Pre-Moldada", codigo_peca, "lote_concreto")
    pct = configuracao()["desforma_pct_fck"]
    if lote:
        base = exigido or flt(frappe.db.get_value("Lote Concreto", lote, "fck_especificado"))
        minimo = round(base * pct / 100.0, 1)
        melhor = max([flt(c.fck_obtido) for c in frappe.get_all("Corpo Prova", filters={"lote": lote}, fields=["fck_obtido"])] or [0])
        if melhor >= minimo > 0:
            return True, f"lote {lote} com {melhor:g} MPa (mínimo de desforma {minimo:g} MPa)"
        return False, (f"o lote {lote} tem {melhor:g} MPa nos corpos de prova e a desforma exige {minimo:g} MPa "
                       f"({pct:g}% do fck). Registre a ruptura na aba Qualidade")
    return False, (f"nenhum corpo de prova aprovado com fck >= {exigido:g} MPa e a peça não tem lote de concreto ligado "
                   f"(com o lote, a desforma libera com {pct:g}% do fck)" if exigido else "nenhum corpo de prova aprovado para esta peça")


# ---------------------------------------------------------------- ocupação

def _ciclo_dias(forma):
    return max(1, math.ceil(flt(forma.get("ciclo_dias")) or CICLO_PADRAO_DIAS))


def _janela(data, forma):
    inicio = getdate(data)
    return [add_days(inicio, i) for i in range(_ciclo_dias(forma))]


def _pecas_da_forma(codigo_forma, ignorar=None):
    filtros = {"forma_pista": codigo_forma, "data_programada": ["is", "set"], "fase_numero": ["<", FASE_DESMOLDADA]}
    return [p for p in frappe.get_all("Peca Pre-Moldada", filters=filtros, fields=["name", "tag", "obra", "data_programada", "comprimento_m", "peso_kg", "fase_numero"])
            if p.name != ignorar]


def _carga(forma, pecas):
    """Quanto da forma o conjunto de peças usa, de 0 a 1 ou mais (acima de 1 não cabe)."""
    tipo = forma.get("tipo") or ""
    if not pecas:
        return 0.0
    cap_kg, comp_m = flt(forma.get("capacidade_kg")), flt(forma.get("comprimento_m"))
    soma_kg, soma_m = sum(flt(p["peso_kg"]) for p in pecas), sum(flt(p["comprimento_m"]) for p in pecas)
    if tipo == "Fôrma":
        return float(len(pecas))
    usos = []
    if cap_kg:
        usos.append(soma_kg / cap_kg)
    if tipo == "Pista de Protensão" and comp_m:
        usos.append(soma_m / comp_m)
    return max(usos) if usos else 1.0


def _folga(forma, peca):
    """Quanto sobra da forma depois da peça (0 a 1): a escolha automática prefere a forma mais justa para ela."""
    if (forma.get("tipo") or "") == "Fôrma":
        usos = [flt(peca["peso_kg"]) / flt(forma["capacidade_kg"]) if flt(forma.get("capacidade_kg")) else 0.0,
                flt(peca["comprimento_m"]) / flt(forma["comprimento_m"]) if flt(forma.get("comprimento_m")) else 0.0]
        return 1.0 - max(usos)
    return 1.0 - _carga(forma, [peca])


def _no_dia(forma, dia, existentes):
    return [p for p in existentes if dia in _janela(p["data_programada"], forma)]


def validar(peca, forma, data, ignorar=None, forcar=False):
    """None se a peça pode ser programada na forma nesta data; senão o motivo (texto para a pessoa).
    A manutenção e o tamanho da peça nunca passam; a ocupação passa com `forcar`."""
    if forma.get("status") == "Manutenção":
        return f"A forma {forma['codigo']} está em manutenção."
    if flt(forma.get("giros_realizados")) >= (flt(forma.get("giros_limite_manutencao")) or 50):
        return f"A forma {forma['codigo']} chegou ao limite de {int(flt(forma.get('giros_limite_manutencao')) or 50)} giros: faça a manutenção antes."
    if flt(forma.get("comprimento_m")) and flt(peca["comprimento_m"]) > flt(forma["comprimento_m"]):
        return f"A peça {peca['tag']} ({flt(peca['comprimento_m']):g} m) não cabe na forma {forma['codigo']} ({flt(forma['comprimento_m']):g} m)."
    if flt(forma.get("capacidade_kg")) and flt(peca["peso_kg"]) > flt(forma["capacidade_kg"]):
        return f"A peça {peca['tag']} ({flt(peca['peso_kg']):g} kg) passa da capacidade da forma {forma['codigo']} ({flt(forma['capacidade_kg']):g} kg)."
    if forcar:
        return None
    existentes = _pecas_da_forma(forma["codigo"], ignorar)
    for dia in _janela(data, forma):
        ja = _no_dia(forma, dia, existentes)
        if _carga(forma, ja + [peca]) > 1.0 + 1e-9:
            quem = ", ".join(p["tag"] for p in ja[:3]) or "outras peças"
            return f"A forma {forma['codigo']} já está ocupada em {dia.strftime('%d/%m')} ({quem}). Escolha outro dia ou outra forma."
    return None


def _forma(codigo):
    return frappe.db.get_value("Forma Pista", codigo, ["codigo", "tipo", "status", "comprimento_m", "largura_m", "capacidade_kg",
                                                      "giros_realizados", "giros_limite_manutencao", "ciclo_dias"], as_dict=True)


def _peca(codigo):
    return frappe.db.get_value("Peca Pre-Moldada", codigo, ["name", "tag", "obra", "comprimento_m", "peso_kg", "fase_numero",
                                                           "forma_pista", "data_programada", "produto"], as_dict=True)


def programar(codigo_peca, codigo_forma, data, forcar=False):
    peca, forma = _peca(codigo_peca), _forma(codigo_forma)
    if not peca:
        return _erro(f"Peça {codigo_peca} não encontrada")
    if not forma:
        return _erro(f"Forma/Pista {codigo_forma} não encontrada")
    try:
        getdate(data)
    except Exception:
        return _erro("Informe a data da programação.")
    if int(peca.fase_numero or 1) >= FASE_DESMOLDADA:
        return _erro("A peça já foi desmoldada e não precisa mais de forma.")
    motivo = validar({**peca, "peso_kg": peca.peso_kg}, forma, data, ignorar=codigo_peca, forcar=forcar)
    if motivo:
        return {"success": False, "error": motivo, "conflito": "ocupada" in motivo}
    anterior = peca.forma_pista
    frappe.db.set_value("Peca Pre-Moldada", codigo_peca, {"forma_pista": codigo_forma, "data_programada": getdate(data)})
    if forma.status == "Livre":
        frappe.db.set_value("Forma Pista", codigo_forma, "status", "Ocupada")
    if anterior and anterior != codigo_forma:
        _liberar_se_vazia(anterior)
    return {"success": True}


def _liberar_se_vazia(codigo_forma):
    if not frappe.db.exists("Forma Pista", codigo_forma):
        return
    if frappe.db.get_value("Forma Pista", codigo_forma, "status") == "Ocupada" and not _pecas_da_forma(codigo_forma):
        frappe.db.set_value("Forma Pista", codigo_forma, "status", "Livre")


def peca_desmoldada(codigo_peca):
    """A peça saiu da forma (fase 5): a forma ganha um giro e fica livre se não tem mais peça nela."""
    forma = frappe.db.get_value("Peca Pre-Moldada", codigo_peca, "forma_pista")
    if not forma or not frappe.db.exists("Forma Pista", forma):
        return
    giros = int(flt(frappe.db.get_value("Forma Pista", forma, "giros_realizados"))) + 1
    frappe.db.set_value("Forma Pista", forma, "giros_realizados", giros)
    _liberar_se_vazia(forma)


# ---------------------------------------------------------------- sugestão automática

def _dia_util(dia, sabado):
    return dia.weekday() != 6 and (sabado or dia.weekday() != 5)


def sugerir(obra=None, data_inicio=None, pecas=None):
    """Programação automática das peças ainda sem forma: a primeira data e a forma mais justa em que cada uma cabe."""
    conf = configuracao()
    inicio = getdate(data_inicio) if data_inicio else getdate()
    filtros = {"fase_numero": ["<=", 3], "forma_pista": ["is", "not set"]}
    if obra and obra != "ALL":
        filtros["obra"] = obra
    candidatas = frappe.get_all("Peca Pre-Moldada", filters=filtros, fields=["name", "tag", "obra", "comprimento_m", "peso_kg", "fase_numero", "produto"],
                                order_by="obra asc, fase_numero desc, peso_kg desc")
    if pecas:
        wanted = set(pecas if isinstance(pecas, list) else __import__("json").loads(pecas))
        candidatas = [p for p in candidatas if p.name in wanted]
    formas = [_forma(f.codigo) for f in frappe.get_all("Forma Pista", fields=["codigo"], order_by="codigo asc")]
    if not formas:
        return _erro("Cadastre ao menos uma forma ou pista antes de programar.")
    reservas = {f["codigo"]: _pecas_da_forma(f["codigo"]) for f in formas}   # inclui o que a sugestão vai acrescentando
    sugestoes, sem_lugar = [], []
    for peca in candidatas:
        peca = dict(peca)
        escolha, motivos = None, set()
        for deslocamento in range(HORIZONTE_DIAS):
            dia = add_days(inicio, deslocamento)
            if not _dia_util(dia, conf["trabalha_sabado"]):
                continue
            opcoes = []
            for forma in formas:
                motivo_fixo = validar(peca, forma, dia, forcar=True)       # manutenção, giros e tamanho
                if motivo_fixo:
                    motivos.add(motivo_fixo)
                    continue
                if any(_carga(forma, _no_dia(forma, d, reservas[forma["codigo"]]) + [peca]) > 1.0 + 1e-9 for d in _janela(dia, forma)):
                    continue
                folga = _folga(forma, peca)
                opcoes.append((folga, forma["codigo"], forma))
            if opcoes:
                opcoes.sort(key=lambda o: (o[0], o[1]))                      # a forma mais justa para a peça
                escolha = (dia, opcoes[0][2])
                break
        if not escolha:
            sem_lugar.append({"codigo_peca": peca["name"], "tag": peca["tag"], "obra": peca["obra"],
                              "motivo": _motivo_principal(motivos) or f"Sem forma livre nos próximos {HORIZONTE_DIAS} dias."})
            continue
        dia, forma = escolha
        reservas[forma["codigo"]].append({"name": peca["name"], "tag": peca["tag"], "obra": peca["obra"], "data_programada": dia,
                                          "comprimento_m": peca["comprimento_m"], "peso_kg": peca["peso_kg"], "fase_numero": peca["fase_numero"]})
        sugestoes.append({"codigo_peca": peca["name"], "tag": peca["tag"], "obra": peca["obra"], "forma": forma["codigo"], "data": dia.isoformat()})
    return {"success": True, "sugestoes": sugestoes, "sem_lugar": sem_lugar}


def _motivo_principal(motivos):
    """O que mais explica ao responsável por que a peça não entrou: o tamanho antes da manutenção de uma forma."""
    ordenados = sorted(motivos)
    return next((m for m in ordenados if "cabe" in m or "capacidade" in m), ordenados[0] if ordenados else None)


def aplicar_sugestoes(sugestoes):
    gravadas, falhas = 0, []
    for s in sugestoes:
        r = programar(s["codigo_peca"], s["forma"], s["data"])
        if r.get("success"):
            gravadas += 1
        else:
            falhas.append({"codigo_peca": s["codigo_peca"], "erro": r["error"]})
    frappe.db.commit()
    return {"success": True, "programadas": gravadas, "falhas": falhas}


# ---------------------------------------------------------------- visão do pátio

def _concretagem(codigo_peca):
    quando = frappe.db.get_value("Fase Historico", {"codigo_peca": codigo_peca, "fase_nova": FASE_CONCRETADO}, "data_hora", order_by="data_hora desc")
    return quando


def visao(data_inicio=None, dias=14):
    inicio = getdate(data_inicio) if data_inicio else getdate()
    dias = max(1, min(int(dias), 31))
    datas = [add_days(inicio, i) for i in range(dias)]
    hoje = getdate()
    formas_saida = []
    for f in frappe.get_all("Forma Pista", fields=["codigo"], order_by="codigo asc"):
        forma = _forma(f.codigo)
        pecas = _pecas_da_forma(f.codigo)
        linha = []
        for d in datas:
            ja = _no_dia(forma, d, pecas)
            linha.append({"data": d.isoformat(), "carga_pct": round(min(_carga(forma, ja), 9.99) * 100) if ja else 0,
                          "pecas": [p["tag"] for p in ja]})
        formas_saida.append({"codigo": forma["codigo"], "tipo": forma["tipo"], "status": forma["status"], "ciclo_dias": _ciclo_dias(forma),
                             "giros": int(flt(forma["giros_realizados"])), "giros_limite": int(flt(forma["giros_limite_manutencao"]) or 50),
                             "dias": linha})
    atrasadas = [{"codigo_peca": p.name, "tag": p.tag, "obra": p.obra, "forma": p.forma_pista, "data": str(p.data_programada), "fase": p.fase_numero}
                 for p in frappe.get_all("Peca Pre-Moldada", filters={"data_programada": ["<", hoje], "fase_numero": ["<", FASE_CONCRETADO], "forma_pista": ["is", "set"]},
                                         fields=["name", "tag", "obra", "forma_pista", "data_programada", "fase_numero"], order_by="data_programada asc")]
    desformas = []
    agora = now_datetime()
    for p in frappe.get_all("Peca Pre-Moldada", filters={"fase_numero": FASE_CONCRETADO}, fields=["name", "tag", "obra", "forma_pista", "fck", "lote_concreto"]):
        concretou = _concretagem(p.name)
        forma = _forma(p.forma_pista) if p.forma_pista else None
        ciclo = _ciclo_dias(forma) if forma else 1
        prevista = (concretou + timedelta(days=ciclo)) if concretou else None
        liberada, explicacao = desforma_liberada(p.name, p.fck)
        desformas.append({"codigo_peca": p.name, "tag": p.tag, "obra": p.obra, "forma": p.forma_pista, "concretada_em": str(concretou) if concretou else None,
                          "desforma_prevista": str(prevista) if prevista else None, "pronta_pelo_prazo": bool(prevista and agora >= prevista),
                          "resistencia_liberada": liberada, "resistencia": explicacao})
    sem_forma = frappe.db.count("Peca Pre-Moldada", {"fase_numero": ["<=", 3], "forma_pista": ["is", "not set"]})
    return {"success": True, "datas": [d.isoformat() for d in datas], "formas": formas_saida, "atrasadas": atrasadas, "desformas": desformas,
            "sem_forma": sem_forma, "manutencao": [f["codigo"] for f in formas_saida if f["status"] == "Manutenção" or f["giros"] >= f["giros_limite"]]}


def configurar_forma(codigo, ciclo_dias):
    if not frappe.db.exists("Forma Pista", codigo or ""):
        return _erro("Forma/Pista não encontrada.")
    try:
        ciclo = float(str(ciclo_dias).replace(",", "."))
    except ValueError:
        return _erro("Informe o ciclo em dias.")
    if not 0.5 <= ciclo <= 14:
        return _erro("O ciclo da forma deve ficar entre 0,5 e 14 dias.")
    frappe.db.set_value("Forma Pista", codigo, "ciclo_dias", ciclo)
    frappe.db.commit()
    return {"success": True, "ciclo_dias": ciclo}
