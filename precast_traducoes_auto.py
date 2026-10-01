"""Tradução automática das telas do ERPNext/RH que ainda estão em inglês.

`coletar()` varre os cadastros dos módulos vendidos e lista cada rótulo, descrição e opção sem tradução.
`gerar()` traduz a lista com o modelo da Groq e grava `precast_traducoes_geradas.json`; `aplicar_traducoes`
(em precast_traducoes.py) carrega esse arquivo junto com as traduções escritas à mão, que têm prioridade.
"""
import json
import os
import re
import time

import frappe

MODULOS = ["Accounts", "Buying", "Selling", "Stock", "Assets", "Setup", "HR", "Payroll", "Subcontracting", "CRM", "Projects", "Manufacturing",
           "Quality Management", "Maintenance", "Support", "Regional", "Contacts"]
ARQUIVO = os.path.join(os.path.dirname(__file__), "precast_traducoes_geradas.json")
LOTE = 45
MAX_TEXTO = 420
RE_TEM_LETRAS = re.compile(r"[A-Za-z]{3,}")


def _precisa(texto):
    if not texto or len(texto) > MAX_TEXTO or not RE_TEM_LETRAS.search(texto) or "{{" in texto or "<" in texto:
        return False
    if re.search(r"[À-ÿ]", texto):  # já está em português
        return False
    if "_" in texto or re.fullmatch(r"[a-z0-9 ./:-]+", texto):  # nomes internos de campo e valores técnicos, não texto de tela
        return False
    return frappe._(texto) == texto


def coletar():
    """Textos em inglês dos cadastros dos módulos vendidos, sem tradução em pt-BR."""
    frappe.local.lang = "pt-BR"
    textos = set()
    doctypes = frappe.get_all("DocType", filters={"module": ["in", MODULOS], "istable": ["in", [0, 1]]}, pluck="name")
    for nome in doctypes:
        try:
            meta = frappe.get_meta(nome)
        except Exception:
            continue
        candidatos = [nome]
        for campo in meta.fields:
            if campo.hidden:
                continue
            candidatos += [campo.label, campo.description]
            if campo.fieldtype == "Select" and campo.options:
                candidatos += [o.strip() for o in campo.options.split("\n")]
        textos.update(t.strip() for t in candidatos if t and _precisa(t.strip()))
    for tabela, campo in (("Workspace Sidebar Item", "label"), ("Desktop Icon", "label"), ("Workspace Sidebar", "name")):
        textos.update(t for t in frappe.get_all(tabela, pluck=campo) if t and _precisa(t))
    return sorted(textos)


PROMPT = ("Você traduz telas de um ERP industrial brasileiro (ERPNext) do inglês para o português do Brasil. "
          "Use a terminologia contábil, fiscal e de RH usada no Brasil. Mantenha o sentido exato, sem explicar. "
          "Preserve siglas (ERP, CRM, BOM, FIFO, GL), nomes próprios e marcadores como %s, {0}. Responda SOMENTE com um objeto JSON "
          "que mapeia cada texto original para a tradução, com as mesmas chaves recebidas.")


def _traduzir_lote(chave, modelo, textos):
    import requests
    corpo = {"model": modelo, "temperature": 0.1, "max_tokens": 3500,
             "response_format": {"type": "json_object"},
             "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": json.dumps(textos, ensure_ascii=False)}]}
    for tentativa in range(6):
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {chave}"}, json=corpo, timeout=90)
        if r.status_code == 200:
            return json.loads(r.json()["choices"][0]["message"]["content"])
        if r.status_code == 429:
            time.sleep(15 + 5 * tentativa)
            continue
        raise RuntimeError(f"Groq {r.status_code}: {r.text[:200]}")
    raise RuntimeError("Groq: limite de uso não liberou")


def gerar(maximo=None):
    chave = frappe.conf.get("groq_api_key")
    if not chave:
        frappe.throw("Falta a chave da Groq (groq_api_key) na configuração do site.")
    modelo = frappe.conf.get("groq_modelo") or "openai/gpt-oss-120b"
    try:
        feito = json.load(open(ARQUIVO, encoding="utf-8"))
    except (OSError, ValueError):
        feito = {}
    pendentes = [t for t in coletar() if t not in feito][: maximo or None]
    print(f"{len(pendentes)} textos para traduzir ({len(feito)} já prontos).", flush=True)
    for i in range(0, len(pendentes), LOTE):
        lote = pendentes[i:i + LOTE]
        try:
            resposta = _traduzir_lote(chave, modelo, lote)
        except Exception as e:
            print(f"lote {i // LOTE + 1}: {e}", flush=True)
            continue
        for origem in lote:
            destino = str(resposta.get(origem) or "").strip()
            if destino and destino != origem:
                feito[origem] = destino
        json.dump(feito, open(ARQUIVO, "w", encoding="utf-8"), ensure_ascii=False, indent=0, sort_keys=True)
        print(f"lote {i // LOTE + 1}/{-(-len(pendentes) // LOTE)}: {len(feito)} traduções", flush=True)
    return len(feito)


def carregar():
    try:
        return json.load(open(ARQUIVO, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
