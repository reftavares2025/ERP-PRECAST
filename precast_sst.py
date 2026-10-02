"""Segurança do trabalho, manutenção dos equipamentos e proteção de dados (LGPD).

SST: treinamentos (NR-35, NR-11...), exames (ASO), entrega de EPI e acidentes, com validade e vencimentos. Com a exigência
ligada, o operador por rosto só avança a fase que pede treinamento válido (pátio e expedição: NR-11; montagem em obra: NR-35).
Frota: ativos com horímetro ou odômetro, manutenção preventiva por intervalo e documentos com vencimento.
LGPD: o consentimento da biometria, o termo, a exportação e a exclusão dos dados do titular."""
import json
import unicodedata

import frappe
from frappe.utils import add_days, flt, getdate, now_datetime

TIPOS_SST = ("Treinamento", "ASO", "EPI", "Acidente", "Inspeção")
TIPOS_ATIVO = ("Caminhão", "Guindaste", "Ponte rolante", "Empilhadeira", "Equipamento")
CHAVE_EXIGIR_TREINAMENTO = "sst_exigir_treinamento"
FASES_COM_TREINAMENTO = {6: "NR-11", 7: "NR-35"}      # fase em que a peça está -> NR exigida de quem bipa (6: pátio e expedição; 7: montagem)
JANELA_ALERTA_DIAS = 30
VERSAO_TERMO = "1.0"
FINALIDADE_BIOMETRIA = "Reconhecimento facial para o acesso ao sistema e o registro de quem executou cada etapa da produção."


def _erro(texto):
    return {"success": False, "error": texto}


def _norm(texto):
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or "").strip().lower()) if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------- SST

def exigir_treinamento():
    return str(frappe.defaults.get_global_default(CHAVE_EXIGIR_TREINAMENTO) or "0") == "1"


def definir_exigir_treinamento(valor):
    frappe.defaults.set_global_default(CHAVE_EXIGIR_TREINAMENTO, "1" if valor else "0")


def registrar_sst(tipo, pessoa, documento=None, data_emissao=None, validade=None, observacoes=None, funcao=None, obra=None,
                  cat=False, dias_afastamento=None):
    if tipo not in TIPOS_SST:
        return _erro("Escolha o tipo do registro: " + ", ".join(TIPOS_SST) + ".")
    pessoa = (pessoa or "").strip()
    if not pessoa:
        return _erro("Informe a pessoa.")
    if tipo in ("Treinamento", "ASO", "EPI") and not (documento or "").strip():
        return _erro({"Treinamento": "Informe qual treinamento (por exemplo NR-35).", "ASO": "Informe o tipo do exame (admissional, periódico...).",
                      "EPI": "Informe o EPI entregue e o número do CA."}[tipo])
    emissao = getdate(data_emissao) if data_emissao else getdate()
    if emissao > getdate():
        return _erro("A data do registro não pode ser no futuro.")
    fim = getdate(validade) if validade else None
    if fim and fim < emissao:
        return _erro("A validade não pode ser anterior à data de emissão.")
    if tipo == "Treinamento" and not fim:
        return _erro("Informe a validade do treinamento.")
    frappe.get_doc({
        "doctype": "Registro SST", "tipo": tipo, "pessoa": pessoa, "funcao": funcao, "documento": (documento or "").strip(), "data_emissao": emissao,
        "validade": fim, "observacoes": observacoes, "obra": obra, "cat": 1 if str(cat).lower() in ("1", "true", "sim") else 0,
        "dias_afastamento": int(flt(dias_afastamento)) if dias_afastamento not in (None, "") else None,
        "registrado_por": frappe.utils.get_fullname(frappe.session.user),
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True}


def _estado(validade, hoje):
    if not validade:
        return "sem validade"
    dias = (getdate(validade) - hoje).days
    return "vencido" if dias < 0 else "a vencer" if dias <= JANELA_ALERTA_DIAS else "em dia"


def listar_sst(tipo=None, pessoa=None, limite=500):
    filtros = {}
    if tipo:
        filtros["tipo"] = tipo
    if pessoa:
        filtros["pessoa"] = pessoa
    hoje = getdate()
    linhas = frappe.get_all("Registro SST", filters=filtros, order_by="data_emissao desc, creation desc", limit=int(limite),
                            fields=["name", "tipo", "pessoa", "funcao", "documento", "data_emissao", "validade", "observacoes", "obra", "cat", "dias_afastamento", "registrado_por"])
    for l in linhas:
        l["estado"] = _estado(l["validade"], hoje)
    return linhas


def treinamento_valido(pessoa, nr):
    """True se a pessoa tem o treinamento (a mais recente emissão) dentro da validade."""
    hoje = getdate()
    alvo = _norm(nr)
    candidatos = [r for r in frappe.get_all("Registro SST", filters={"tipo": "Treinamento"}, fields=["pessoa", "documento", "validade", "data_emissao"], order_by="data_emissao desc")
                  if _norm(r.pessoa) == _norm(pessoa) and _norm(r.documento).startswith(alvo)]
    return bool(candidatos) and getdate(candidatos[0].validade) >= hoje


def bloqueio_por_treinamento(usuario, fase_atual):
    """Texto do bloqueio, ou None. Vale para quem entrou por rosto, com a exigência ligada."""
    nr = FASES_COM_TREINAMENTO.get(int(fase_atual or 1))
    if not nr or not exigir_treinamento():
        return None
    nome = frappe.db.get_value("Rosto Operador", {"usuario": usuario}, "nome")
    if not nome:
        return None
    if treinamento_valido(nome, nr):
        return None
    return f"{nome} não tem o treinamento {nr} em dia. Cadastre ou renove em Segurança antes de operar esta etapa."


def painel_sst():
    hoje = getdate()
    registros = listar_sst()
    vencidos = [r for r in registros if r["estado"] == "vencido" and r["tipo"] != "Acidente"]
    a_vencer = [r for r in registros if r["estado"] == "a vencer"]
    # só o registro mais recente de cada pessoa e documento conta como vencido
    ultimo = {}
    for r in registros:
        if r["tipo"] in ("Treinamento", "ASO", "EPI"):
            ultimo.setdefault((_norm(r["pessoa"]), r["tipo"], _norm(r["documento"])), r)
    vencidos = [r for r in ultimo.values() if r["estado"] == "vencido"]
    a_vencer = [r for r in ultimo.values() if r["estado"] == "a vencer"]
    ano = add_days(hoje, -365)
    acidentes = [r for r in registros if r["tipo"] == "Acidente" and getdate(r["data_emissao"]) >= ano]
    pessoas = sorted({r["pessoa"] for r in registros})
    matriz = []
    for nome in pessoas:
        linha = {"pessoa": nome}
        for nr in sorted(set(FASES_COM_TREINAMENTO.values())):
            linha[nr] = "ok" if treinamento_valido(nome, nr) else "pendente"
        matriz.append(linha)
    return {"success": True, "exigir_treinamento": exigir_treinamento(), "exigencias": {str(f): nr for f, nr in FASES_COM_TREINAMENTO.items()},
            "vencidos": sorted(vencidos, key=lambda r: str(r["validade"])), "a_vencer": sorted(a_vencer, key=lambda r: str(r["validade"])),
            "acidentes_12_meses": len(acidentes), "com_cat": sum(1 for a in acidentes if a["cat"]),
            "dias_afastados_12_meses": sum(int(a["dias_afastamento"] or 0) for a in acidentes), "matriz": matriz}


# ---------------------------------------------------------------- ativos e manutenção

def salvar_ativo(nome, tipo, unidade_medida="Horas", leitura_atual=0, intervalo_manutencao=None, vencimento_documento=None, identificacao=None):
    nome = (nome or "").strip()
    if not nome:
        return _erro("Informe o nome do equipamento.")
    if tipo not in TIPOS_ATIVO:
        return _erro("Escolha o tipo do equipamento: " + ", ".join(TIPOS_ATIVO) + ".")
    if unidade_medida not in ("Horas", "Km"):
        return _erro("A medida do equipamento é Horas ou Km.")
    leitura, intervalo = flt(leitura_atual), flt(intervalo_manutencao)
    if leitura < 0 or intervalo < 0:
        return _erro("Leitura e intervalo não podem ser negativos.")
    valores = {"tipo": tipo, "unidade_medida": unidade_medida, "leitura_atual": leitura, "intervalo_manutencao": intervalo or None,
               "vencimento_documento": getdate(vencimento_documento) if vencimento_documento else None, "identificacao": identificacao}
    if frappe.db.exists("Ativo Operacional", nome):
        anterior = flt(frappe.db.get_value("Ativo Operacional", nome, "leitura_atual"))
        if leitura < anterior:
            return _erro(f"A leitura não pode voltar: o equipamento já marcava {anterior:g}.")
        frappe.db.set_value("Ativo Operacional", nome, valores)
    else:
        frappe.get_doc({"doctype": "Ativo Operacional", "nome": nome, "status": "Operando", "leitura_ultima_manutencao": leitura, **valores}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "nome": nome}


def _situacao_manutencao(a):
    intervalo = flt(a.intervalo_manutencao)
    if not intervalo:
        return "sem intervalo", None
    usado = flt(a.leitura_atual) - flt(a.leitura_ultima_manutencao)
    faltam = intervalo - usado
    return ("vencida" if faltam <= 0 else "próxima" if faltam <= intervalo * 0.1 else "em dia"), round(faltam, 1)


def listar_ativos():
    hoje = getdate()
    ano = add_days(hoje, -365)
    custos = {}
    for m in frappe.get_all("Manutencao Ativo", filters={"data": [">=", ano]}, fields=["ativo", "custo"]):
        custos[m.ativo] = custos.get(m.ativo, 0.0) + flt(m.custo)
    linhas = []
    for a in frappe.get_all("Ativo Operacional", order_by="nome asc",
                            fields=["nome", "tipo", "identificacao", "unidade_medida", "leitura_atual", "intervalo_manutencao", "leitura_ultima_manutencao", "vencimento_documento", "status"]):
        situacao, faltam = _situacao_manutencao(a)
        a["manutencao"], a["faltam"] = situacao, faltam
        a["documento"] = _estado(a["vencimento_documento"], hoje) if a["vencimento_documento"] else "sem data"
        a["custo_12_meses"] = round(custos.get(a["nome"], 0.0), 2)
        linhas.append(a)
    return linhas


def registrar_manutencao(ativo, tipo, descricao=None, custo=None, leitura=None, data=None):
    if not frappe.db.exists("Ativo Operacional", ativo or ""):
        return _erro("Equipamento não encontrado.")
    if tipo not in ("Preventiva", "Corretiva"):
        return _erro("A manutenção é Preventiva ou Corretiva.")
    atual = flt(frappe.db.get_value("Ativo Operacional", ativo, "leitura_atual"))
    marcada = flt(leitura) if leitura not in (None, "") else atual
    if marcada < atual:
        return _erro(f"A leitura da manutenção ({marcada:g}) é menor que a atual ({atual:g}).")
    if flt(custo) < 0:
        return _erro("O custo não pode ser negativo.")
    quando = getdate(data) if data else getdate()
    if quando > getdate():
        return _erro("A data da manutenção não pode ser no futuro.")
    frappe.get_doc({"doctype": "Manutencao Ativo", "ativo": ativo, "tipo": tipo, "data": quando, "leitura": marcada, "custo": flt(custo) or 0,
                    "descricao": descricao, "responsavel": frappe.utils.get_fullname(frappe.session.user)}).insert(ignore_permissions=True)
    mudancas = {"leitura_atual": marcada}
    if tipo == "Preventiva":
        mudancas["leitura_ultima_manutencao"] = marcada
    frappe.db.set_value("Ativo Operacional", ativo, mudancas)
    frappe.db.commit()
    return {"success": True}


def atualizar_leitura(ativo, leitura):
    if not frappe.db.exists("Ativo Operacional", ativo or ""):
        return _erro("Equipamento não encontrado.")
    nova, atual = flt(leitura), flt(frappe.db.get_value("Ativo Operacional", ativo, "leitura_atual"))
    if nova < atual:
        return _erro(f"A leitura não pode voltar: já marcava {atual:g}.")
    frappe.db.set_value("Ativo Operacional", ativo, "leitura_atual", nova)
    frappe.db.commit()
    return {"success": True}


def historico_manutencao(ativo):
    return frappe.get_all("Manutencao Ativo", filters={"ativo": ativo}, order_by="data desc, creation desc", limit=100,
                          fields=["tipo", "data", "leitura", "custo", "descricao", "responsavel"])


def ativo_com_pendencia(nome):
    """Texto do problema do equipamento (manutenção vencida, documento vencido, parado), ou None."""
    a = frappe.db.get_value("Ativo Operacional", nome or "", ["nome", "intervalo_manutencao", "leitura_atual", "leitura_ultima_manutencao", "vencimento_documento", "status"], as_dict=True)
    if not a:
        return None
    if a.status != "Operando":
        return f"{a.nome} está {a.status.lower()}."
    if _situacao_manutencao(a)[0] == "vencida":
        return f"{a.nome} passou do intervalo de manutenção preventiva."
    if a.vencimento_documento and getdate(a.vencimento_documento) < getdate():
        return f"O documento de {a.nome} está vencido."
    return None


# ---------------------------------------------------------------- LGPD

def termo():
    empresa = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company") or "a empresa"
    return {"success": True, "versao": VERSAO_TERMO, "finalidade": FINALIDADE_BIOMETRIA, "empresa": empresa, "texto": (
        f"TERMO DE CONSENTIMENTO PARA O USO DA IMAGEM DO ROSTO (LGPD, art. 11)\n\n"
        f"{empresa} usa o reconhecimento facial para duas finalidades: permitir o seu acesso ao sistema de produção e registrar quem executou cada etapa da fabricação das peças.\n\n"
        "O que fica guardado: uma identificação numérica do seu rosto (não a foto), o seu nome, o setor e a data do último acesso. A imagem da câmera fica só no seu celular e não é enviada.\n\n"
        "Quanto tempo: enquanto você trabalhar neste setor. Ao sair da empresa ou se você retirar o consentimento, a identificação do rosto é apagada.\n\n"
        "Os seus direitos: você pode pedir a qualquer momento uma cópia dos dados guardados, a correção deles, a retirada do consentimento e a exclusão da identificação do rosto, "
        "procurando o responsável pelo sistema. Sem o consentimento você entra pelo e-mail e senha, sem prejuízo ao seu trabalho.\n\n"
        "Os registros de produção (qual etapa foi feita, quando) são mantidos pela obrigação de rastreabilidade das peças, sem o seu nome depois da exclusão.\n\n"
        "(Modelo para a sua empresa revisar com o seu jurídico antes de usar.)")}


def registrar_consentimento(titular, nome, origem="cadastro pelo celular"):
    frappe.get_doc({"doctype": "Consentimento Dados", "titular": titular, "nome": nome, "finalidade": FINALIDADE_BIOMETRIA, "versao": VERSAO_TERMO,
                    "data_hora": now_datetime(), "origem": origem}).insert(ignore_permissions=True)


def consentimento_ativo(titular):
    return bool(frappe.db.exists("Consentimento Dados", {"titular": titular, "revogado_em": ["is", "not set"]}))


def exportar_titular(usuario):
    rosto = frappe.db.get_value("Rosto Operador", {"usuario": usuario}, ["usuario", "nome", "setores", "ativo", "ultimo_acesso", "creation"], as_dict=True)
    consentimentos = frappe.get_all("Consentimento Dados", filters={"titular": usuario}, fields=["finalidade", "versao", "data_hora", "origem", "revogado_em"], order_by="data_hora asc")
    if not rosto and not consentimentos:
        return _erro("Não há dados deste titular.")
    etapas = frappe.db.count("Fase Historico", {"usuario": usuario})
    return {"success": True, "titular": usuario, "cadastro": {**(rosto or {}), "identificacao_do_rosto": "guardada (numérica, não é a foto)" if rosto else "não há"},
            "consentimentos": consentimentos, "etapas_registradas_na_producao": etapas}


def excluir_titular(usuario):
    """Apaga a identificação do rosto e retira o consentimento. As etapas de produção ficam, sem o nome da pessoa."""
    rosto = frappe.db.get_value("Rosto Operador", {"usuario": usuario}, "name")
    if not rosto and not frappe.db.exists("Consentimento Dados", {"titular": usuario}):
        return _erro("Não há dados deste titular.")
    if rosto:
        frappe.delete_doc("Rosto Operador", rosto, ignore_permissions=True, force=True)
    for nome in frappe.get_all("Consentimento Dados", filters={"titular": usuario, "revogado_em": ["is", "not set"]}, pluck="name"):
        frappe.db.set_value("Consentimento Dados", nome, "revogado_em", now_datetime())
    pseudonimo = "titular-removido-" + frappe.generate_hash(usuario, 6)
    anonimizadas = 0
    for nome in frappe.get_all("Fase Historico", filters={"usuario": usuario}, pluck="name"):
        frappe.db.set_value("Fase Historico", nome, "usuario", pseudonimo, update_modified=False)
        anonimizadas += 1
    frappe.db.commit()
    return {"success": True, "etapas_anonimizadas": anonimizadas}
