"""Leitura das pranchas de detalhamento de peças dentro do desenho do AutoCAD.

Uma prancha de peça é a folha de detalhamento de uma peça pré-moldada: título com o código, a seção e o
comprimento, vistas e cortes com alturas, as barras de aço (posição, bitola, quantidade, comprimento) e a
lista de materiais com resumo de aço, volume de concreto e taxa de aço.

No desenho, o projetista escreve o título da prancha na camada `DT-Título`:
    PM.01=02=03 (30X40X8,60)    e, ao lado, (3x)     -> 3 peças: PM.01, PM.02 e PM.03
    VM-1.1 = 2.1  (25X60X7,18) - 2X
    PM.03 ao 07  /  21 ao 25 (40X50X15,69)    10X
    PM.1  (40x50x1205.0)                      -> código em cima, medidas (cm) embaixo
O carimbo da folha (bloco com REVISÃO / DESCRIÇÃO / VISTO) dá a moldura de cada prancha.
Só o que está nessas folhas vira peça: tabelas de carga, plantas e legendas não criam peças.
"""
import re
import unicodedata

CAMADA_TITULO = "dt-titulo"
PALAVRAS_CARIMBO = ("revisao", "descricao", "visto")

RE_NUM = r"\d+(?:[.,]\d+)?"
RE_DIMENSAO = re.compile(rf"\(\s*({RE_NUM})\s*[xX×]\s*({RE_NUM})\s*[xX×]\s*({RE_NUM})\s*\)")
RE_QTD_SOZINHA = re.compile(r"^\(?\s*(\d{1,3})\s*[xX]\s*\)?$")
RE_QTD_NO_TEXTO = re.compile(r"(?:QTDE?\.?:?\s*(\d{1,3})\s*[xX]?|[-–]\s*(\d{1,3})\s*[xX]\b)", re.IGNORECASE)
RE_PREFIXO = re.compile(r"^([A-Za-zÀ-ÿ]{1,4})\s*([.\-_]?)\s*")
RE_CODIGO = re.compile(r"^[A-Za-z]{1,4}\s*[.\-_]?\s*\d")

PRODUTOS_POR_PREFIXO = [
    (("PM", "P", "PIL"), "PILAR / PILAR"),
    (("VM", "VG", "VR", "V", "VC", "VP"), "VIGA / VIGA"),
    (("BR",), "VIGA / BRAÇO"),
    (("BM", "BL", "B"), "FUNDAÇÃO / BLOCO"),
    (("PL", "PN", "PF"), "PAINEL / FECHAMENTO"),
    (("ES", "E"), "ESCADA / ACESSO"),
    (("TE", "T"), "TERÇA / COBERTURA"),
    (("LJ", "L"), "LAJE / LAJE"),
    (("CA",), "CALHA / COBERTURA"),
]


def _sem_acento(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")


def _norm(texto):
    return _sem_acento(texto).lower().strip()


def _numero(valor):
    """'80.372' -> 80.372; '0,9420' -> 0.942; '1.114,57' -> 1114.57."""
    s = str(valor or "").strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _texto_da_entidade(e):
    try:
        if e.dxftype() == "TEXT":
            return e.dxf.text.strip()
        if e.dxftype() == "ATTRIB" or e.dxftype() == "ATTDEF":
            return e.dxf.text.strip()
        return e.plain_text().strip()
    except Exception:
        return ""


def produto_do_codigo(codigo):
    letras = re.match(r"[A-Za-z]+", codigo or "")
    pref = (letras.group(0) if letras else "").upper()
    for prefixos, produto in PRODUTOS_POR_PREFIXO:
        if pref in prefixos:
            return produto
    return "OUTROS / PEÇA"


# ---------------------------------------------------------------- códigos
def expandir_codigos(texto):
    """'PM.01=02=03' -> [PM.01, PM.02, PM.03]; 'PM.03 ao 07 / 21 ao 25' -> PM.03..PM.07 e PM.21..PM.25."""
    texto = re.sub(r"\s+", " ", (texto or "").strip())
    texto = re.sub(r"^(?:CAIXA|PLATIBANDA|COBERTURA)\s*-\s*", "", texto, flags=re.IGNORECASE)
    if not texto or not RE_CODIGO.match(texto):
        return []
    m = RE_PREFIXO.match(texto)
    prefixo = (m.group(1) + m.group(2)) if m else ""
    codigos = []
    for grupo in re.split(r"\s*[/,;]\s*", texto):
        grupo = grupo.strip()
        if not grupo:
            continue
        partes = re.split(r"\s*=\s*", grupo)
        for parte in partes:
            parte = parte.strip()
            faixa = re.split(r"\s+ao\s+|\s+a\s+", parte, flags=re.IGNORECASE)
            if len(faixa) == 2:
                ini = _com_prefixo(faixa[0], prefixo)
                fim_token = faixa[1].strip()
                a, b = _ultimo_inteiro(ini), _ultimo_inteiro(fim_token)
                if a is not None and b is not None and 0 <= b - a <= 200:
                    base, largura = _base_e_largura(ini)
                    for n in range(a, b + 1):
                        codigos.append(f"{base}{str(n).zfill(largura)}")
                    continue
            codigos.append(_com_prefixo(parte, prefixo))
    vistos, saida = set(), []
    for c in codigos:
        c = c.replace(" ", "")
        if c and c not in vistos:
            vistos.add(c)
            saida.append(c)
    return saida


def _com_prefixo(token, prefixo):
    token = token.strip()
    return token if re.match(r"[A-Za-zÀ-ÿ]", token) else f"{prefixo}{token}"


def _ultimo_inteiro(token):
    m = re.search(r"(\d+)\s*$", token or "")
    return int(m.group(1)) if m else None


def _base_e_largura(token):
    m = re.search(r"(\d+)\s*$", token)
    return token[:m.start()].replace(" ", ""), len(m.group(1))


# ---------------------------------------------------------------- leitura do desenho
def _achatar(doc, entidades, nivel=0, maximo=3):
    """Entidades com coordenadas do mundo, abrindo os blocos inseridos (carimbo, detalhes)."""
    for e in entidades:
        if e.dxftype() == "INSERT" and nivel < maximo:
            try:
                yield from _achatar(doc, e.virtual_entities(), nivel + 1, maximo)
            except Exception:
                continue
        else:
            yield e


def _textos(doc):
    """(texto, x, y, camada, altura) de todo TEXT/MTEXT do modelo, inclusive dentro de blocos."""
    saida = []
    for e in _achatar(doc, doc.modelspace()):
        t = e.dxftype()
        if t not in ("TEXT", "MTEXT"):
            continue
        tx = _texto_da_entidade(e).replace("\n", " ").replace("\t", " ")
        tx = re.sub(r"\s+", " ", tx).strip()
        if not tx:
            continue
        p = e.dxf.insert
        altura = e.dxf.height if t == "TEXT" else getattr(e.dxf, "char_height", 0.0)
        saida.append((tx, float(p.x), float(p.y), e.dxf.layer, float(altura or 0.0)))
    return saida


RAZAO_A = 2 ** 0.5   # folhas A0..A4: largura = altura x 1,4142


def _quadro_da_folha(entrada, ext):
    """O carimbo tem legendas, tarjas e margens fora do quadro da folha. O quadro é a maior polilinha do bloco com
    proporção de folha (1,15 a 1,6): é o retângulo vermelho que o projetista plota. Sem ela, vale a caixa do carimbo."""
    try:
        from ezdxf import bbox as _bbox
        melhor = None
        for v in entrada.virtual_entities():
            if v.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
                continue
            e = _bbox.extents([v], fast=True)
            if not e.has_data:
                continue
            w, h = e.extmax.x - e.extmin.x, e.extmax.y - e.extmin.y
            if h > 0 and 1.15 <= w / h <= 1.6 and (melhor is None or w * h > melhor[0]):
                melhor = (w * h, (e.extmin.x, e.extmin.y, e.extmax.x, e.extmax.y))
        if melhor:
            return melhor[1]
    except Exception:
        pass
    return ext


def _molduras(doc, ext_func):
    """Carimbos de folha no modelo: INSERT cujo bloco tem REVISÃO/DESCRIÇÃO. Cada um traz a caixa da folha
    (coordenadas do mundo) e os atributos do carimbo (PECA, DIMENSOES, NX, NF., NP., AÇO, CONCRETO...)."""
    cache = {}
    molduras = []
    for e in doc.modelspace():
        if e.dxftype() != "INSERT":
            continue
        nome = e.dxf.name
        if nome not in cache:
            try:
                blk = doc.blocks.get(nome)
                achados = {_norm(_texto_da_entidade(x)) for x in blk if x.dxftype() in ("TEXT", "MTEXT", "ATTDEF")}
                cache[nome] = sum(1 for p in PALAVRAS_CARIMBO if p in achados) >= 2
            except Exception:
                cache[nome] = False
        if not cache[nome]:
            continue
        ext = ext_func(e)
        if ext is None:
            continue
        ext = _quadro_da_folha(e, ext)
        atributos = {}
        for a in e.attribs:
            atributos[_sem_acento(a.dxf.tag).upper().strip()] = (a.dxf.text or "").strip()
        molduras.append({"bbox": ext, "atributos": atributos})
    return molduras


def _lista_de_ferros(tabela_celulas):
    """Interpreta a LISTA DE MATERIAIS a partir das células (texto, x, y) da tabela."""
    if not tabela_celulas:
        return None
    celulas = sorted(tabela_celulas, key=lambda c: (-round(c[2], 1), c[1]))
    linhas, atual, y_atual = [], [], None
    for c in celulas:
        if y_atual is None or abs(c[2] - y_atual) > 0.12 * _altura_media(celulas):
            if atual:
                linhas.append(sorted(atual, key=lambda t: t[1]))
            atual, y_atual = [c], c[2]
        else:
            atual.append(c)
    if atual:
        linhas.append(sorted(atual, key=lambda t: t[1]))

    ferros, resumo = [], {}
    for linha in linhas:
        textos = [c[0].strip() for c in linha]
        junto = _norm(" ".join(textos))
        if "resumo de aco" in junto:
            resumo["aco_kg"] = _ultimo_numero(textos)
        elif "volume de concreto" in junto:
            resumo["volume_m3"] = _ultimo_numero(textos)
        elif "taxa de aco" in junto:
            resumo["taxa_aco"] = _ultimo_numero(textos)
        else:
            nums = [_numero(t) for t in textos]
            if len(textos) >= 6 and all(n is not None for n in nums[1:6]):
                diam, q, unit, total, peso = nums[1:6]
                if q and q > 0:
                    ferros.append({"posicao": textos[0], "bitola_mm": diam, "quantidade": int(q), "comp_unit_m": unit,
                                   "comp_total_m": total, "peso_kg": peso})
    return {"ferros": ferros, **resumo}


def _ultimo_numero(textos):
    for t in reversed(textos):
        n = _numero(t)
        if n is not None:
            return n
    return None


def _altura_media(celulas):
    ys = sorted({round(c[2], 2) for c in celulas})
    difs = [b - a for a, b in zip(ys, ys[1:]) if b - a > 1e-6]
    return min(difs) if difs else 1.0


def _tabelas_da_folha(doc, bbox, textos=()):
    """Células (texto, x, y) das tabelas ACAD_TABLE cujo ponto de inserção cai dentro da folha."""
    x0, y0, x1, y1 = bbox
    resultado = []
    for e in doc.modelspace():
        if e.dxftype() != "ACAD_TABLE":
            continue
        ins = e.dxf.insert
        if not (x0 <= ins.x <= x1 and y0 <= ins.y <= y1):
            continue
        try:
            reg = doc.entitydb.get(e.dxf.block_record_handle)
            blk = doc.blocks.get(reg.dxf.name)
        except Exception:
            continue
        celulas = []
        for x in blk:
            if x.dxftype() in ("TEXT", "MTEXT"):
                p = x.dxf.insert
                tx = re.sub(r"\s+", " ", _texto_da_entidade(x).replace("\n", " ")).strip()
                if tx:
                    celulas.append((tx, float(p.x), float(p.y)))
        # Em alguns carimbos as linhas de dados são textos soltos sobre a moldura da tabela, não células dela.
        try:
            xs = [v for l in blk if l.dxftype() == "LINE" for v in (l.dxf.start.x, l.dxf.end.x)]
            ys = [v for l in blk if l.dxftype() == "LINE" for v in (l.dxf.start.y, l.dxf.end.y)]
            if xs and ys and len(celulas) <= 12:   # só o cabeçalho está no bloco: os dados são textos soltos
                tx0, tx1, ty0, ty1 = ins.x + min(xs), ins.x + max(xs), ins.y + min(ys), ins.y + max(ys)
                for tx, x, y, _camada, _h in textos:
                    if tx0 <= x <= tx1 and ty0 <= y <= ty1:
                        celulas.append((tx, x - ins.x, y - ins.y))
        except Exception:
            pass
        resultado.append(celulas)
    return resultado


def extrair_pranchas(doc, ext_func=None):
    """Lista as pranchas de detalhamento do desenho. Lista vazia = o desenho não segue o padrão (DT-Título / carimbo)."""
    if ext_func is None:
        from ezdxf import bbox as _bbox

        def ext_func(entidade):
            try:
                ext = _bbox.extents([entidade], fast=True)
            except Exception:
                return None
            return (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y) if ext.has_data else None

    textos = _textos(doc)
    titulos = [t for t in textos if _norm(t[3]).startswith(CAMADA_TITULO)]
    molduras = _molduras(doc, ext_func)

    por_moldura = {}  # índice da moldura -> dados da prancha
    for i, m in enumerate(molduras):
        dados = _dados_do_carimbo(m["atributos"])
        if dados:
            por_moldura[i] = dados

    soltas = []
    for tx, x, y, camada, h in titulos:
        m = RE_DIMENSAO.search(tx)
        if not m:
            continue
        codigos = expandir_codigos(tx[:m.start()].strip(" -–")) or _codigo_vizinho(titulos, x, y, h)
        if not codigos:
            continue
        dim = tuple(_numero(m.group(i)) for i in (1, 2, 3))
        qtd = _quantidade(tx[m.end():]) or _quantidade_vizinha(titulos, x, y, h)
        dados = {"codigos": codigos, "titulo": tx, "dim": dim, "quantidade": qtd, "ancora": (x, y)}
        i = _indice_da_moldura(molduras, x, y)
        if i is None:
            soltas.append(dados)
        elif i not in por_moldura:
            por_moldura[i] = dados
        elif not por_moldura[i].get("quantidade") and qtd:
            por_moldura[i]["quantidade"] = qtd

    pranchas = []
    for i, dados in list(por_moldura.items()) + [(None, d) for d in soltas]:
        quadro = molduras[i]["bbox"] if i is not None else None
        largura, altura, comp = dados["dim"]
        comp_m = comp / 100.0 if comp >= 100 else comp  # (40x50x1205.0) está em cm; (30X40X8,60) em metros
        prancha = {"codigos": dados["codigos"], "titulo": dados["titulo"], "secao": f"{_inteiro(largura)}x{_inteiro(altura)}",
                   "largura_cm": largura, "altura_cm": altura, "comprimento_m": round(comp_m, 3),
                   "quantidade": dados.get("quantidade") or len(dados["codigos"]), "ancora": dados["ancora"], "bbox": quadro,
                   "produto": produto_do_codigo(dados["codigos"][0]), "folha": dados.get("folha"), "titulo_folha": dados.get("titulo_folha"),
                   "aco_kg": dados.get("aco_kg"), "volume_m3": dados.get("volume_m3"), "taxa_aco": dados.get("taxa_aco"), "fck": dados.get("fck"),
                   "ferros": []}
        if i is not None and not prancha["titulo_folha"]:
            prancha["titulo_folha"] = molduras[i]["atributos"].get("NP.") or None
        if quadro:
            conteudo = _conteudo_da_folha(doc, textos, quadro)
            for k, v in conteudo.items():
                if k == "ferros" or prancha.get(k) in (None, "", []):
                    prancha[k] = v if v not in (None, "") else prancha.get(k)
        pranchas.append(prancha)
    return _sem_folhas_fantasma(pranchas)


def _sem_folhas_fantasma(pranchas):
    """O desenho pode guardar cópias vazias de uma folha (carimbo e restos de texto, sem o detalhamento). Com o mesmo
    código, título e medidas de uma folha que tem a lista de ferros, a cópia sem lista não é uma peça a mais."""
    chave = lambda p: (tuple(p["codigos"]), p["titulo"], p["secao"], p["comprimento_m"])
    completas = {chave(p) for p in pranchas if p["ferros"]}
    mantidas = [p for p in pranchas if p["ferros"] or chave(p) not in completas]
    for p in mantidas:
        p["folhas_fantasma_ignoradas"] = sum(1 for q in pranchas if q is not p and not q["ferros"] and chave(q) == chave(p)) if p["ferros"] else 0
    return mantidas


def _dados_do_carimbo(at):
    """Atributos do carimbo preenchidos pelo projetista (modelo com PECA e DIMENSOES)."""
    peca, dims = at.get("PECA", ""), at.get("DIMENSOES", "")
    m = RE_DIMENSAO.search(dims)
    codigos = expandir_codigos(peca)
    if not (m and codigos):
        return None
    dados = {"codigos": codigos, "titulo": f"{peca} {dims}".strip(), "dim": tuple(_numero(m.group(i)) for i in (1, 2, 3)),
             "ancora": None, "folha": at.get("NF.") or None, "titulo_folha": at.get("NP.") or None}
    nx = _numero(at.get("NX"))
    dados["quantidade"] = int(nx) if nx else None
    for chave, campo in (("ACO", "aco_kg"), ("CONCRETO", "volume_m3"), ("TXACO", "taxa_aco"), ("FCK", "fck")):
        v = _numero(at.get(chave))
        if v is not None and v > 0:
            dados[campo] = v
    return dados


def _indice_da_moldura(molduras, x, y):
    candidatas = [(i, m["bbox"]) for i, m in enumerate(molduras)
                  if m["bbox"][0] - 0.5 <= x <= m["bbox"][2] + 0.5 and m["bbox"][1] - 0.5 <= y <= m["bbox"][3] + 0.8]
    if not candidatas:
        return None
    return min(candidatas, key=lambda c: (c[1][2] - c[1][0]) * (c[1][3] - c[1][1]))[0]


def _inteiro(v):
    return int(v) if float(v).is_integer() else v


def _conteudo_da_folha(doc, textos, quadro):
    x0, y0, x1, y1 = quadro
    saida = {}
    for tx, x, y, camada, h in textos:
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            continue
        m = re.match(r"^FOLHA\s+(\S+)$", tx, re.IGNORECASE)
        if m:
            saida["folha"] = m.group(1)
        if re.match(r"^(DETALHAMENTO|DET\.)\s", tx, re.IGNORECASE):
            saida["titulo_folha"] = tx
    for celulas in _tabelas_da_folha(doc, quadro, textos):
        info = _lista_de_ferros(celulas)
        if info and (info.get("ferros") or info.get("aco_kg") is not None):
            saida.update({k: v for k, v in info.items() if v is not None})
            break
    return saida


def _codigo_vizinho(titulos, x, y, h):
    """Código escrito na linha de cima (formato PM.1 / (40x50x1205.0))."""
    h = h or 0.35
    melhor = None
    for tx, tx_x, tx_y, camada, th in titulos:
        if abs(tx_x - x) <= 4 * h and 0 < tx_y - y <= 3 * h and RE_CODIGO.match(tx) and not RE_DIMENSAO.search(tx):
            cods = expandir_codigos(tx)
            if cods and (melhor is None or tx_y - y < melhor[0]):
                melhor = (tx_y - y, cods)
    return melhor[1] if melhor else []


def _quantidade(trecho):
    t = (trecho or "").strip()
    if not t:
        return None
    m = RE_QTD_SOZINHA.match(t) or RE_QTD_NO_TEXTO.search(t)
    if not m:
        return None
    for g in m.groups():
        if g:
            return int(g)
    return None


def _quantidade_vizinha(titulos, x, y, h):
    h = h or 0.35
    for tx, tx_x, tx_y, camada, th in titulos:
        if 0 <= tx_x - x <= 40 * h and abs(tx_y - y) <= 0.8 * h and not RE_DIMENSAO.search(tx) and not RE_CODIGO.match(tx):
            q = _quantidade(tx)
            if q:
                return q
    return None
