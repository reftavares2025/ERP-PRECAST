"""Padrão de camadas e cores do AutoCAD para o ERP Precast ler o projeto.

O padrão vem do modelo de cores dos projetos: cada tipo de elemento pré-moldado tem a sua camada, e a
cor é a da camada (PorCamada). O texto com o código da peça (P-10, VC-01) fica na camada do elemento.
O leitor continua lendo desenhos fora do padrão; o relatório de conformidade diz ao projetista o que
faltou para a leitura ficar exata.
"""
import re

# Código de peça: prefixo de tipo + número (P-10, VC-01, VM12, BL3...). Igual ao do leitor.
RE_CODIGO_PECA = re.compile(r"^(PM|VM|VC|VP|P|BM|BL|VG|VR|BR|ES|PL|TE|LJ|CP|CA|MK|V|E)[\.\-_]?\s?(\d{1,4}[A-Z]?)$", re.IGNORECASE)

# O que o leitor procura para criar peças: as pranchas de detalhamento.
PRANCHAS_DE_DETALHAMENTO = [
    "Cada peça tem uma folha com o carimbo (REVISÃO, DESCRIÇÃO, VISTO) no modelo do desenho.",
    "O título da peça fica na camada DT-Título: PM.01=02=03 (30X40X8,60) e (3x); VM-1.1 = 2.1 (25X60X7,18) - 2X; PM.03 ao 07 / 21 ao 25 (40X50X15,69) 10X.",
    "Alternativa: carimbo com os atributos PECA, DIMENSOES e NX preenchidos (e AÇO, CONCRETO, TXAÇO, FCK).",
    "A lista de materiais é uma tabela do AutoCAD na folha: N, DIAM, Q, COMP. UNIT., COMP. TOTAL, PESO, com RESUMO DE AÇO, VOLUME DE CONCRETO e TAXA DE AÇO.",
]

COR_NOMES = {1: "vermelho", 2: "amarelo", 3: "verde", 4: "ciano", 5: "azul", 6: "magenta", 7: "branco"}

# Elementos pré-moldados: camada, cor ACI, produto, o que desenhar.
ELEMENTOS = [
    {"camada": "pilar", "cor": 4, "produto": "Pilar", "uso": "Pilares (sólidos 3D) e o texto do código, ex. P-10."},
    {"camada": "viga_parede", "cor": 6, "produto": "Viga", "uso": "Vigas de parede."},
    {"camada": "viga_PORTÃO", "cor": 107, "produto": "Viga", "uso": "Vigas de portão."},
    {"camada": "Viga_Cobertura", "cor": 5, "produto": "Viga", "uso": "Vigas de cobertura e o texto do código, ex. VC-01."},
    {"camada": "Vigas Mezanino", "cor": 3, "produto": "Viga", "uso": "Vigas do mezanino."},
    {"camada": "TERÇAS", "cor": 20, "produto": "Terça", "uso": "Terças."},
    {"camada": "LAJES", "cor": 253, "produto": "Laje Alveolar", "uso": "Lajes."},
    {"camada": "LAJES MEZANINO", "cor": 254, "produto": "Laje Alveolar", "uso": "Lajes do mezanino."},
    {"camada": "laje alveolar", "cor": 252, "produto": "Laje Alveolar", "uso": "Painéis de laje alveolar."},
    {"camada": "PLACA DE FECHAMENTO", "cor": 253, "produto": "Painel de Fechamento", "uso": "Placas de fechamento.", "apelidos": ["PLACAS", "placas_de_fechamento"]},
    {"camada": "PLACA DE ARRIMO", "cor": 45, "produto": "Painel de Fechamento", "uso": "Placas de arrimo."},
    {"camada": "ESCADAS", "cor": 93, "produto": "Escada", "uso": "Escadas."},
]

# Camadas de apoio: não geram peça.
APOIO = [
    {"camada": "cotas", "cor": 1, "uso": "Cotas."},
    {"camada": "textos", "cor": 7, "uso": "Textos gerais."},
    {"camada": "selo", "cor": 7, "uso": "Carimbo da prancha (obra, cliente, projeto)."},
    {"camada": "eixos", "cor": 30, "uso": "Eixos (linha tracejada HIDDEN)."},
]

# Fora do escopo do pré-moldado: o leitor ignora.
IGNORADAS = [
    {"camada": "TELHAS COBERTURA", "cor": 163}, {"camada": "estrutura_metálica", "cor": 192}, {"camada": "PAREDE", "cor": 252},
    {"camada": "ESQUADRIAS", "cor": 150}, {"camada": "Vidraçaria", "cor": 170}, {"camada": "TUBO 75", "cor": 90},
]


def nome_da_cor(cor):
    return COR_NOMES.get(cor, f"cor {cor}")


def _texto(entidade):
    try:
        return (entidade.dxf.text if entidade.dxftype() == "TEXT" else entidade.plain_text()).strip()
    except Exception:
        return ""


def _camada_do_padrao(nome, tabela):
    """Devolve a entrada do padrão para o nome de camada do desenho (sem diferenciar maiúsculas)."""
    n = nome.strip().lower()
    for item in tabela:
        if n == item["camada"].lower() or n in [a.lower() for a in item.get("apelidos", [])]:
            return item
    return None


def _entidades(doc, profundidade=2):
    """Entidades do desenho: modelo, folhas e o conteúdo dos blocos inseridos (carimbo, detalhes)."""
    def percorrer(entidades, nivel):
        for e in entidades:
            yield e
            if e.dxftype() == "INSERT" and nivel > 0 and e.dxf.name in doc.blocks:
                yield from percorrer(doc.blocks.get(e.dxf.name), nivel - 1)
    for layout in doc.layouts:
        yield from percorrer(layout, profundidade)


def avaliar(doc):
    """Confere o desenho contra o padrão e devolve um relatório por camada do padrão."""
    cores_no_desenho = {c.dxf.name.lower(): c.dxf.color for c in doc.layers}
    contagem, codigos = {}, set()
    for e in _entidades(doc):
        camada = e.dxf.layer
        el = _camada_do_padrao(camada, ELEMENTOS)
        ap = None if el else _camada_do_padrao(camada, APOIO)
        alvo = el or ap
        if alvo is None:
            continue
        contagem[alvo["camada"]] = contagem.get(alvo["camada"], 0) + 1
        if el and e.dxftype() in ("TEXT", "MTEXT"):
            txt = _texto(e)
            if RE_CODIGO_PECA.match(txt):
                codigos.add(re.sub(r"[\s\.\-_]", "", txt.upper()))
    itens = []
    for grupo, tabela in (("elemento", ELEMENTOS), ("apoio", APOIO)):
        for i in tabela:
            nomes = [i["camada"].lower()] + [a.lower() for a in i.get("apelidos", [])]
            cor_real = next((cores_no_desenho[n] for n in nomes if n in cores_no_desenho), None)
            achados = contagem.get(i["camada"], 0)
            itens.append({**i, "grupo": grupo, "cor_nome": nome_da_cor(i["cor"]), "encontrados": achados, "ok": achados > 0,
                          "cor_no_desenho": cor_real, "cor_confere": cor_real is None or cor_real == i["cor"]})
    elementos = [x for x in itens if x["grupo"] == "elemento"]
    selo = next(x for x in itens if x["camada"] == "selo")
    faltando = []
    if not any(x["ok"] for x in elementos):
        faltando.append("Nenhuma camada de elemento do padrão tem conteúdo (pilar, Viga_Cobertura, TERÇAS...)")
    if not codigos:
        faltando.append("Texto com o código da peça (P-10, VC-01) na camada do elemento")
    if not selo["ok"]:
        faltando.append("Carimbo na camada selo")
    cor_errada = [f"{x['camada']} (padrão {x['cor']}, no desenho {x['cor_no_desenho']})" for x in itens if not x["cor_confere"]]
    return {"itens": itens, "conforme": not faltando and not cor_errada, "faltando": faltando, "cor_errada": cor_errada,
            "pecas_marcadas": len(codigos)}


def padrao():
    """O padrão em formato de dados, para a tela e para o guia do projetista."""
    return {"pranchas": PRANCHAS_DE_DETALHAMENTO,
            "elementos": [{**i, "cor_nome": nome_da_cor(i["cor"])} for i in ELEMENTOS],
            "apoio": [{**i, "cor_nome": nome_da_cor(i["cor"])} for i in APOIO],
            "ignoradas": [{**i, "cor_nome": nome_da_cor(i["cor"])} for i in IGNORADAS]}


def script_autocad():
    """Script (.scr) para o projetista rodar no AutoCAD (comando SCRIPT): cria as camadas do padrão com as cores."""
    linhas = ["-LAYER"]
    for i in ELEMENTOS + APOIO:
        linhas += ["N", i["camada"], "C", str(i["cor"]), i["camada"]]
    linhas += [""]  # linha vazia encerra o comando -LAYER
    return "\r\n".join(linhas) + "\r\n"
