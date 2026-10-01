"""Preparação fiscal: dados da empresa e dos produtos que a emissão de NF-e vai usar, e o checklist que
mostra o que ainda falta. Este módulo não emite nota: guarda e valida o cadastro para a integração fiscal.

Os dados ficam num único valor global (frappe.defaults), sem tabela nova.
"""
import json
import re
from datetime import date

import frappe

CHAVE = "precast_fiscal"

REGIMES = ["Simples Nacional", "Lucro Presumido", "Lucro Real", "MEI"]
AMBIENTES = ["Homologação", "Produção"]
UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
       "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]

CAMPOS_TEXTO = [
    "razao_social", "nome_fantasia", "cnpj", "inscricao_estadual", "inscricao_municipal", "cnae", "regime",
    "logradouro", "numero", "complemento", "bairro", "cidade", "uf", "cep", "telefone",
    "email_contador", "ambiente", "serie_nfe", "proximo_numero_nfe", "certificado_validade",
]
CAMPOS_MARCA = ["ie_isento", "certificado_a1_disponivel", "homologacao_testada"]

# Produto -> sugestão de NCM/CFOP. Só vale depois que o dono confirma e salva (o contador valida).
PRODUTOS_FISCAIS = ["Pilar", "Viga", "Painel de Fechamento", "Laje Alveolar", "Bloco de Fundação", "Terça", "Escada", "Estaca", "Outros"]
SUGESTAO_NCM = "68109100"   # elementos pré-fabricados para construção ou engenharia civil, de cimento/concreto
SUGESTAO_CFOP_DENTRO = "5101"
SUGESTAO_CFOP_FORA = "6101"


def so_digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def cnpj_valido(valor):
    n = so_digitos(valor)
    if len(n) != 14 or len(set(n)) == 1:
        return False
    def dv(base, pesos):
        soma = sum(int(d) * p for d, p in zip(base, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = dv(n[:12], p1)
    d2 = dv(n[:12] + d1, [6] + p1)
    return n[12:] == d1 + d2


def ler():
    bruto = frappe.defaults.get_global_default(CHAVE)
    try:
        dados = json.loads(bruto) if bruto else {}
    except ValueError:
        dados = {}
    dados.setdefault("produtos", {})
    return dados


def _limpar_produtos(produtos):
    saida = {}
    for nome, f in (produtos or {}).items():
        if nome not in PRODUTOS_FISCAIS or not isinstance(f, dict):
            continue
        saida[nome] = {
            "ncm": so_digitos(f.get("ncm"))[:8],
            "cfop_dentro_uf": so_digitos(f.get("cfop_dentro_uf"))[:4],
            "cfop_fora_uf": so_digitos(f.get("cfop_fora_uf"))[:4],
            "cst_csosn": so_digitos(f.get("cst_csosn"))[:3],
        }
    return saida


def gravar(dados):
    """Valida o formato (não o conteúdo fiscal) e grava. Devolve o que foi gravado."""
    atual = ler()
    novo = dict(atual)
    for campo in CAMPOS_TEXTO:
        if campo in dados:
            novo[campo] = str(dados[campo] or "").strip()[:200]
    for campo in CAMPOS_MARCA:
        if campo in dados:
            novo[campo] = bool(dados[campo])
    novo["cnpj"] = so_digitos(novo.get("cnpj"))
    novo["cep"] = so_digitos(novo.get("cep"))
    if novo.get("uf") and novo["uf"].upper() not in UFS:
        frappe.throw(f"UF inválida: {novo['uf']}.")
    novo["uf"] = (novo.get("uf") or "").upper()
    if novo.get("regime") and novo["regime"] not in REGIMES:
        frappe.throw("Regime tributário inválido.")
    if novo.get("ambiente") and novo["ambiente"] not in AMBIENTES:
        frappe.throw("Ambiente inválido.")
    if "produtos" in dados:
        novo["produtos"] = _limpar_produtos(dados["produtos"])
    frappe.defaults.set_global_default(CHAVE, json.dumps(novo, ensure_ascii=False))
    return novo


def prontidao(d):
    """Lista do que falta para a empresa poder emitir nota. Cada item diz o que fazer."""
    p = d.get("produtos") or {}
    produtos_ok = all(len(p.get(n, {}).get("ncm", "")) == 8 and len(p.get(n, {}).get("cfop_dentro_uf", "")) == 4
                      for n in PRODUTOS_FISCAIS)
    validade = d.get("certificado_validade") or ""
    certificado_ok = bool(d.get("certificado_a1_disponivel"))
    if certificado_ok and validade:
        try:
            certificado_ok = date.fromisoformat(validade) > date.today()
        except ValueError:
            certificado_ok = False
    endereco_ok = all(d.get(c) for c in ("logradouro", "numero", "bairro", "cidade", "uf")) and len(d.get("cep", "")) == 8
    itens = [
        ("cnpj", "CNPJ válido", cnpj_valido(d.get("cnpj")), "Informe o CNPJ da empresa (14 dígitos)."),
        ("razao", "Razão social", bool(d.get("razao_social")), "Como está no cartão CNPJ."),
        ("ie", "Inscrição estadual (ou marcada como isenta)", bool(d.get("inscricao_estadual")) or bool(d.get("ie_isento")), "Peça ao contador. Indústria precisa de IE ativa na SEFAZ."),
        ("regime", "Regime tributário", d.get("regime") in REGIMES, "Simples Nacional, Lucro Presumido, Lucro Real ou MEI."),
        ("cnae", "CNAE principal", len(so_digitos(d.get("cnae"))) == 7, "7 dígitos, do cartão CNPJ."),
        ("endereco", "Endereço completo", endereco_ok, "Rua, número, bairro, cidade, UF e CEP."),
        ("contador", "E-mail do contador", "@" in (d.get("email_contador") or ""), "A nota e o XML vão para a contabilidade."),
        ("certificado", "Certificado digital A1 válido", certificado_ok, "Compre o A1 (arquivo .pfx) da empresa e informe a validade. O certificado em si não é guardado aqui."),
        ("serie", "Série e próximo número da NF-e", bool(d.get("serie_nfe")) and bool(d.get("proximo_numero_nfe")), "Normalmente série 1; o número continua de onde a empresa parou."),
        ("produtos", "NCM e CFOP de todos os produtos", produtos_ok, "Confirme com o contador os valores sugeridos na tabela e salve."),
        ("homologacao", "Teste em homologação feito", bool(d.get("homologacao_testada")), "Marque depois que a integração emitir uma nota de teste na SEFAZ."),
    ]
    lista = [{"chave": c, "rotulo": r, "ok": bool(ok), "dica": dica} for c, r, ok, dica in itens]
    pronto = sum(1 for i in lista if i["ok"])
    return {"itens": lista, "percentual": round(100 * pronto / len(lista)), "pronto": pronto == len(lista)}


def sugestoes():
    return {"ncm": SUGESTAO_NCM, "cfop_dentro_uf": SUGESTAO_CFOP_DENTRO, "cfop_fora_uf": SUGESTAO_CFOP_FORA}
