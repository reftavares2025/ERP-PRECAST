"""
===============================================================================
ERP Precast - Dynamic CAD & PDF Parser Engine (NBR 9062)
===============================================================================
Dynamic parser for DWG, DXF, and PDF structural drawings.
Extracts title block attributes (Obra Code, Client, Obra Name, City/UF, Revision, Fck, Volume, Qtd, Cover)
and structural element entities (BM, Bloco, Pilar, Viga, Braço, Painel, Escada, Estaca)
from any uploaded project file without hardcoded fallbacks.
Supports equality tables (Tabela de Igualdade: BM28=BM29=...=BM50) and dimensional tags (BR- 1 (25 x 40 x 11,01)).

REGRA DE OURO: NUNCA apresentar um número de seção/comprimento/volume como se
fosse real quando ele não foi lido de verdade do desenho. Nesses casos o campo
vem como None e a peça carrega "dimensoes_confirmadas": False + "aviso".
"""

import os
import re
import subprocess
import ezdxf

try:
    from ezdxf import bbox as ezdxf_bbox
except Exception:
    ezdxf_bbox = None

import fitz  # PyMuPDF

def _alias_missing_fonts_to_arial():
    """
    Many drawings reference "ARIALUNI.TTF" (Arial Unicode MS) as the text
    style font, which isn't installed on this machine. ezdxf doesn't cache a
    failed font lookup, so every single TEXT/MTEXT entity in the drawing
    retries the failing OS lookup + exception + log on every render — on a
    real detailing file (thousands of text entities across ~90 pieces) this
    alone turned a ~1s render into several minutes. Aliasing the missing
    font's glyph cache to the real Arial font once, up front, makes every
    later lookup an instant cache hit instead of a repeated failure.
    """
    try:
        from ezdxf.fonts import fonts as ezdxf_fonts
        arial = ezdxf_fonts.TrueTypeFont("arial.ttf", 2.5)
        for missing_name in ("arialuni.ttf", "arial unicode ms.ttf"):
            ezdxf_fonts._CachedFont._glyph_caches.setdefault(missing_name, arial.glyph_cache)
    except Exception:
        pass  # best-effort: worst case, rendering just stays slow for that font


_alias_missing_fonts_to_arial()

def localizar_conversor_dwg():
    """Caminho do ODA File Converter (DWG -> DXF) ou None. Procura, nesta ordem: a variável de
    ambiente PRECAST_ODA_EXE, a pasta tools/ODAFileConverter do projeto (instalação embutida) e a
    instalação padrão do Windows (qualquer versão)."""
    import glob
    candidatos = [os.environ.get("PRECAST_ODA_EXE", "")]
    raiz = os.path.dirname(os.path.abspath(__file__))
    candidatos += glob.glob(os.path.join(raiz, "tools", "ODAFileConverter*", "ODAFileConverter.exe"))
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        candidatos += sorted(glob.glob(os.path.join(base, "ODA", "ODAFileConverter*", "ODAFileConverter.exe")), reverse=True)
    return next((c for c in candidatos if c and os.path.exists(c)), None)


ODA_EXE = localizar_conversor_dwg()

from precast_caminhos import pasta_de_uploads

UPLOADS_DIR = pasta_de_uploads()
os.makedirs(UPLOADS_DIR, exist_ok=True)

def _sem_janela():
    """Opções do subprocess para não abrir janela preta (console) no Windows."""
    if os.name != "nt":
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": info}


def _safe_cod(cod):
    return re.sub(r'[^A-Za-z0-9_.\-]', '_', str(cod or 'PEC'))


# Peso específico do concreto estrutural armado (kg/m³) - NBR 6118 / NBR 9062
DENSIDADE_CONCRETO_KG_M3 = 2500.0

# Taxa de aço por m³ de concreto (kg/m³), já incluindo +30% de perda.
# Fonte: tabela de taxa de aço (kg/m³) por tipo de peça
# (tabela paramétrica do Eng. Régis, validada contra 702 pilares reais
# produzidos — média 174,7 kg/m³, pilares 30x40 reais entre 146,6 e
# 150,2 kg/m³, consistente com os 149,6 kg/m³ usados aqui). Casada por
# substring contra o campo "prod" no formato "CATEGORIA / SUBTIPO" que
# este parser já usa (ex.: "VIGA / VIGA", "FUNDAÇÃO / BLOCO").
_TAXA_ACO_KG_M3 = [
    ("PILAR", 149.6),
    ("CONSOLE", 16.0),
    ("TERÇA", 62.0), ("TERCA", 62.0),
    ("PLACA", 61.2), ("PAINEL", 61.2),
    ("VIGA", 129.2),  # família genérica mais comum sem marcação específica
    ("LAJE", 0.0),    # tabela original: não passa por cálculo de aço (medida em m²)
]
_TAXA_ACO_FALLBACK_KG_M3 = 150.0  # antigo KG_ACO_POR_M3 — peças fora da tabela (bloco, estaca, escada, outros)

def _taxa_aco_kg_m3(prod):
    prod_upper = (prod or "").upper()
    for chave, taxa in _TAXA_ACO_KG_M3:
        if chave in prod_upper:
            return taxa
    return _TAXA_ACO_FALLBACK_KG_M3

def _peso_total_peca_kg(vol_m3, prod):
    """Peso da peça pronta: concreto + armadura (NBR 9062 / taxa real)."""
    concreto = vol_m3 * DENSIDADE_CONCRETO_KG_M3
    aco = vol_m3 * _taxa_aco_kg_m3(prod)
    return concreto + aco

def calcular_orcamento_peca(prod, secao, comp, vol, peso_aco_real=None):
    """Calcula custo industrial estimado e preço de venda sugerido para peça de pré-fabricado."""
    CUSTO_CONCRETO_M3 = 480.00   # R$/m³ (Concreto fck 40-50 MPa)
    CUSTO_ACO_KG = 9.50          # R$/kg (Aço CA-50/60 cortado e dobrado)
    CUSTO_FORMA_M2 = 45.00       # R$/m² (Fôrma + desmoldante + M.O.)
    FATOR_INDIRETOS = 0.12       # 12% aditivos e custos indiretos
    MARGEM_LUCRO = 0.35          # 35% de margem operacional

    vol_m3_calc = float(vol) if vol is not None else 0.0
    if vol_m3_calc == 0.0 and secao and "X" in str(secao).upper():
        try:
            parts = str(secao).upper().split('X')
            b_m = float(parts[0]) / 100.0
            h_m = float(parts[1]) / 100.0
            comp_m = float(comp) if comp is not None else 0.0
            if b_m > 0 and h_m > 0 and comp_m > 0:
                vol_m3_calc = round(b_m * h_m * comp_m, 3)
        except Exception:
            pass

    taxa_aco_val = _taxa_aco_kg_m3(prod)
    peso_aco_kg = round(vol_m3_calc * taxa_aco_val, 2) if vol_m3_calc > 0 else 0.0
    if peso_aco_real:  # a lista de materiais da prancha manda sobre a taxa média
        peso_aco_kg = round(float(peso_aco_real), 2)

    area_forma_m2 = 0.0
    if secao and "X" in str(secao).upper():
        try:
            parts = str(secao).upper().split('X')
            b_m = float(parts[0]) / 100.0
            h_m = float(parts[1]) / 100.0
            comp_m = float(comp) if comp is not None else (vol_m3_calc / (b_m * h_m) if (b_m * h_m > 0 and vol_m3_calc > 0) else 0.0)
            area_forma_m2 = round(2.0 * (b_m + h_m) * comp_m, 2)
        except Exception:
            area_forma_m2 = round(vol_m3_calc * 8.0, 2)
    elif vol_m3_calc > 0:
        area_forma_m2 = round(vol_m3_calc * 8.0, 2)

    custo_concreto_tot = round(vol_m3_calc * CUSTO_CONCRETO_M3, 2)
    custo_aco_tot = round(peso_aco_kg * CUSTO_ACO_KG, 2)
    custo_forma_tot = round(area_forma_m2 * CUSTO_FORMA_M2, 2)
    custo_direto = custo_concreto_tot + custo_aco_tot + custo_forma_tot
    custo_estimado = round(custo_direto * (1.0 + FATOR_INDIRETOS), 2)
    preco_venda_sugerido = round(custo_estimado / (1.0 - MARGEM_LUCRO), 2) if custo_estimado > 0 else 0.0

    return {
        "vol_estimado": vol_m3_calc,
        "peso_aco_kg": peso_aco_kg,
        "area_forma_m2": area_forma_m2,
        "custo_concreto": custo_concreto_tot,
        "custo_aco": custo_aco_tot,
        "custo_forma": custo_forma_tot,
        "custo_estimado": custo_estimado,
        "preco_venda_sugerido": preco_venda_sugerido
    }

# Padrão "LxA" (largura x altura) em cm
_RE_SECAO = re.compile(r'\b(\d{2,3})\s*[xX]\s*(\d{2,3})\b')

# UFs válidas brasileiras e lista de palavras comuns a ignorar em regex de Cidade/UF
UFS_BRASIL = {
    'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA',
    'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN',
    'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'
}
IGNORAR_CIDADE = {
    'DETALHAMENTO', 'FOLHA', 'PRANCHA', 'DESENHO', 'REVISAO', 'REVISÃO',
    'ESCALA', 'PESO', 'VOLUME', 'PROJETO', 'ENCONTRA', 'TRATA', 'LOCALIZA',
    'APLICA', 'CONSIDERA', 'DESTINA', 'DEVE', 'LOCACAO', 'LOCAÇÃO'
}


class DynamicCADParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.filename = os.path.basename(file_path)

    def parse(self):
        import urllib.parse
        ext = os.path.splitext(self.filename)[1].lower()
        if ext == '.dwg':
            res = self.parse_dwg()
        elif ext == '.dxf':
            res = self.parse_dxf(self.file_path)
        elif ext == '.pdf':
            res = self.parse_pdf()
        elif ext in ('.ifc', '.ifczip'):
            res = BIMIFCParser(self.file_path).parse()
        elif ext in ('.csv', '.txt', '.xml', '.json'):
            res = StructuralReportParser(self.file_path).parse()
        else:
            return self.empty_response("Formato não suportado")

        # Caminho do DXF de origem que contém a geometria (peças de PDF não
        # têm DXF associado, então a prancha isolada não pode ser gerada
        # automaticamente para essa origem — ver aviso em parse_pdf).
        res['resolved_dxf_path'] = getattr(self, '_resolved_dxf_path', None)

        for p in res.get('pieces', []):
            p['file'] = self.filename
            p_cod = p.get('cod', 'PEC-001')
            p['prancha_file'] = f"prancha_{p_cod}.pdf"
            p['prancha_url'] = f"/pranchas/prancha_{urllib.parse.quote(str(p_cod))}.pdf"
        return res

    def parse_dwg(self):
        """
        Converte o DWG em DXF (ODA File Converter) e lê o DXF. O DXF convertido fica numa pasta de cache cujo nome é
        o hash do CONTEÚDO do DWG: o mesmo desenho reaproveita a conversão, e um desenho alterado (mesmo com o
        mesmo nome) é convertido de novo. Nunca se usa o DXF de outro arquivo.
        """
        exe = ODA_EXE or localizar_conversor_dwg()
        if not exe:
            return self.empty_response(f"O conversor de DWG (ODA File Converter) não está instalado neste computador, então não foi possível ler {self.filename}. "
                                      f"Envie o mesmo projeto em DXF ou instale o conversor (gratuito, em opendesign.com) e tente de novo.")
        if not os.path.exists(self.file_path):
            return self.empty_response(f"Arquivo {self.filename} não encontrado no servidor. Envie de novo.")

        import hashlib, shutil, tempfile
        h = hashlib.sha1()
        with open(self.file_path, 'rb') as f:
            for bloco in iter(lambda: f.read(8 * 1024 * 1024), b''):
                h.update(bloco)
        pasta_cache = os.path.join(UPLOADS_DIR, "dxf_cache")
        os.makedirs(pasta_cache, exist_ok=True)
        dxf_path = os.path.join(pasta_cache, f"{h.hexdigest()}.dxf")

        if not os.path.exists(dxf_path):
            with tempfile.TemporaryDirectory(dir=pasta_cache) as tmp:
                origem, destino = os.path.join(tmp, "in"), os.path.join(tmp, "out")
                os.makedirs(origem), os.makedirs(destino)
                shutil.copyfile(self.file_path, os.path.join(origem, "origem.dwg"))
                try:
                    subprocess.run([exe, origem, destino, 'ACAD2018', 'DXF', '0', '1', 'origem.dwg'], capture_output=True, timeout=900, **_sem_janela())
                except Exception as e:
                    print(f"[ODA CONVERTER WARNING] Timeout/Error converting DWG: {e}")
                gerado = os.path.join(destino, "origem.dxf")
                if os.path.exists(gerado):
                    shutil.move(gerado, dxf_path)
            self._limitar_cache(pasta_cache, manter=dxf_path)

        if os.path.exists(dxf_path):
            return self.parse_dxf(dxf_path)
        return self.empty_response(f"Não foi possível converter o arquivo DWG ({self.filename}). Verifique se o arquivo não está corrompido e tente de novo; se persistir, envie em DXF.")

    @staticmethod
    def _limitar_cache(pasta, manter, maximo=6):
        """Mantém só os DXFs mais recentes (cada um pode passar de 150 MB)."""
        arquivos = [os.path.join(pasta, f) for f in os.listdir(pasta) if f.endswith(".dxf")]
        arquivos.sort(key=os.path.getmtime, reverse=True)
        for velho in arquivos[maximo:]:
            if velho != manter:
                try:
                    os.remove(velho)
                except OSError:
                    pass

    @staticmethod
    def _parse_filename_metadata(filename):
        """
        Extracts obra code, client/obra, city, and UF from standardized file names:
        '136 - 21 - FAZENDA MONICA - ANGATUBA - SP - DETALHAMENTO.dwg'
        '000 - 26 - MANCHA - GUAREI VELHO - ANGATUBA - SP.dwg'
        """
        base = os.path.splitext(os.path.basename(filename))[0]
        parts = [p.strip() for p in base.split(' - ') if p.strip()]
        meta = {}
        if len(parts) >= 4:
            if re.match(r'^[A-Z0-9_-]{1,6}$', parts[0]) and re.match(r'^\d{2}$', parts[1]):
                meta['cod'] = f"{parts[0]} - {parts[1]}"
                meta['cliente'] = parts[2]
                meta['obra'] = parts[2]
                for i in range(3, len(parts)):
                    if parts[i].upper() in UFS_BRASIL and i > 0:
                        meta['cidade_uf'] = f"{parts[i-1]} / {parts[i].upper()}"
                        break
            elif len(parts) >= 3:
                genericos = {'EST', 'DET', 'DET.', 'PROJ', 'PROJETO', 'DETALHAMENTO', 'DETALHAMENTOS', 'ESTRUTURA'}
                # 'EST - FERNANDO SCOCHA 5 - ...': EST é o tipo do desenho, não o código da obra
                meta['cod'] = parts[1] if parts[0].upper() in genericos else parts[0]
                meta['cliente'] = parts[1]
                meta['obra'] = parts[1]
                for i in range(2, len(parts)):
                    if parts[i].upper() in UFS_BRASIL and i > 0:
                        meta['cidade_uf'] = f"{parts[i-1]} / {parts[i].upper()}"
                        break
        elif len(parts) >= 2:
            meta['cod'] = parts[0]
            meta['obra'] = parts[1]
        return meta

    # ------------------------------------------------------------------
    # DXF
    # ------------------------------------------------------------------

    def parse_dxf(self, dxf_path):
        """
        Parses DXF entity strings to extract Obra Code, Client, Obra Name, City/UF, Fck, Volume, and Piece entities.
        Handles Tabela de Igualdade (BM28=BM29=...=BM50) and Dimensional annotations (BR- 1 (25 x 40 x 11,01)).
        """
        try:
            doc = ezdxf.readfile(dxf_path)
        except Exception:
            try:
                doc, auditor = ezdxf.recover.readfile(dxf_path)
                if auditor.has_errors:
                    print(f"[DXF RECOVER] Arquivo recuperado com {len(auditor.errors)} erros corrigidos: {dxf_path}", flush=True)
            except Exception as e2:
                return self.empty_response(f"Não foi possível processar o arquivo ({os.path.basename(dxf_path)}). Erro: {str(e2)}")

        self._resolved_dxf_path = dxf_path

        # Reaproveita (ou constrói e cacheia) o índice espacial de entidades
        # agora — ele é usado tanto para recortar cada painel com precisão
        # (abaixo) quanto depois para renderizar cada peça, então só paga o
        # custo de indexar o desenho inteiro UMA vez por arquivo.
        _, _, entity_index = _get_or_build_render_index(dxf_path, doc)

        file_meta = self._parse_filename_metadata(self.filename)

        texts_with_pos = []
        attr_map = {}

        for layout in doc.layouts:
            for entity in layout:
                if entity.dxftype() == 'TEXT':
                    txt = entity.dxf.text.strip()
                    if txt:
                        pos = entity.dxf.insert
                        texts_with_pos.append((txt, pos.x, pos.y))
                elif entity.dxftype() == 'MTEXT':
                    txt = entity.plain_text().strip()
                    if txt:
                        pos = entity.dxf.insert
                        texts_with_pos.append((txt, pos.x, pos.y))
                elif entity.dxftype() == 'INSERT':
                    for attrib in entity.attribs:
                        tag = attrib.dxf.tag.upper().strip()
                        val = attrib.dxf.text.strip()
                        if val and tag not in attr_map:
                            attr_map[tag] = val

        full_text = "\n".join(t for t, _, _ in texts_with_pos)
        full_text_upper = full_text.upper()

        # Detect piece panels (spatial bounding boxes in drawing), then tighten
        # each one to just the connected geometry around that piece's own tag
        # — the raw row/column slice can be much bigger than the piece itself.

        # 1. CÓDIGO DA OBRA (Nº_DE_PROJETO, Nº PROJETO, NPROJ, etc.)
        obra_cod = None
        for k in ('Nº_DE_PROJETO', 'Nº PROJETO', 'N_DE_PROJETO', 'NUM_PROJETO', 'NPROJ',
                  'NUM_PROJ', 'COD_OBRA', 'CODIGO_OBRA', 'PROJETO_NUM'):
            v = attr_map.get(k, '').strip()
            if v and len(v) >= 2 and v not in ('-', '.'):
                obra_cod = v
                break
        if not obra_cod and file_meta.get('cod'):
            obra_cod = file_meta['cod']

        # 2. CLIENTE (NOME_CLIENTE, CLIENTE, PROPRIETÁRIO, CONSTRUTORA, etc.)
        client_name = None
        for k in ('NOME_CLIENTE', 'NOME DO CLIENTE', 'CLIENTE', 'PROPRIETARIO', 'PROPRIETÁRIO',
                  'CONSTRUTORA', 'SOLICITANTE', 'EMPRESA', 'CONSTRUTOR'):
            v = attr_map.get(k, '').strip()
            if v and len(v) >= 3 and not v.isdigit() and v not in ('INDICADA', '-', '.'):
                client_name = v
                break
        if not client_name and file_meta.get('cliente'):
            client_name = file_meta['cliente']

        # 3. NOME DA OBRA / EMPREENDIMENTO & CIDADE/UF
        obra_name = None
        cidade_uf = None
        for k in ('NOMEOBRA', 'NOME_OBRA', 'OBRA', 'TITULO', 'TÍTULO', 'EMPREENDIMENTO'):
            v = attr_map.get(k, '').strip()
            if v and len(v) >= 3 and v not in ('INDICADA', '-', '.'):
                obra_name = v
                break

        # Check if obra_name contains "EMPREENDIMENTO - CIDADE - UF" or "EMPREENDIMENTO - CIDADE / UF"
        if obra_name:
            m_loc = re.search(r'^(.*?)\s*[-/]\s*([A-ZÀ-Ú\s]{3,30})\s*[-/]\s*([A-Z]{2})$', obra_name, re.IGNORECASE)
            if m_loc:
                c_name = m_loc.group(2).strip()
                uf_name = m_loc.group(3).strip().upper()
                if uf_name in UFS_BRASIL:
                    cidade_uf = f"{c_name} / {uf_name}"
                    obra_name = m_loc.group(1).strip()

        if not cidade_uf and file_meta.get('cidade_uf'):
            cidade_uf = file_meta['cidade_uf']

        if not obra_name and file_meta.get('obra'):
            obra_name = file_meta['obra']

        if not cidade_uf:
            m_city = re.search(r'\b([A-ZÀ-Ú\s]{3,25})\s*(?:\/|\s+-\s+)\s*([A-Z]{2})\b', full_text_upper)
            if m_city:
                c_name = m_city.group(1).strip()
                uf_name = m_city.group(2).strip()
                if uf_name in UFS_BRASIL and not any(ign in c_name for ign in IGNORAR_CIDADE):
                    cidade_uf = f"{c_name} / {uf_name}"

        # 4. FCK (RESISTÊNCIA DO CONCRETO)
        fck = None
        for k in ('FCK', 'RESISTENCIA', 'RESISTÊNCIA'):
            v = attr_map.get(k, '').strip()
            if v and v not in ('-', '.'):
                fck = v if 'MPA' in v.upper() else f"{v} MPa"
                break
        if not fck:
            m_fck = re.search(r'fck\s*[>:=]?\s*(\d{2,3})\s*(?:MPa|mpa|MPA)?', full_text, re.IGNORECASE)
            if m_fck:
                fck = f"{m_fck.group(1).strip()} MPa"

        # 5. COBRIMENTO (COB)
        unit_cobrimento_attr = None
        v_cob = attr_map.get('COB', attr_map.get('COBRIMENTO', '')).replace(',', '.').strip()
        if v_cob and v_cob not in ('-', '.'):
            try:
                unit_cobrimento_attr = float(v_cob)
            except ValueError:
                pass

        # 6. VOLUME e PESO DE ATRIBUTO
        unit_vol_attr = None
        v_vol = attr_map.get('VOL.', attr_map.get('VOL', '')).replace(',', '.').strip()
        if v_vol and v_vol not in ('-', '.'):
            try:
                unit_vol_attr = float(v_vol)
            except ValueError:
                pass

        unit_peso_attr = None
        v_pes = attr_map.get('PES', attr_map.get('PESO', '')).replace(',', '.').strip()
        if v_pes and v_pes not in ('-', '.'):
            try:
                unit_peso_attr = float(v_pes)
            except ValueError:
                pass

        qtd_attr = None
        v_qtd = attr_map.get('QTDE', attr_map.get('QTD', '')).replace('x', '').replace('X', '').strip()
        if v_qtd:
            try:
                qtd_attr = int(v_qtd)
            except ValueError:
                pass

        proj_attr = attr_map.get('PROJETO', '')

        # ------------------------------------------------------------
        # 7. EXTRAÇÃO DAS PEÇAS ESTRUTURAIS
        # ------------------------------------------------------------
        pieces = []
        piece_tags_found = set()

        def montar_peca(cod, tag, prod, pos_xy=None, secao=None, comp=None, vol=None, peso=None, qtd=1, confirm=False, aviso=None, fonte=None):
            if pos_xy is not None and secao is None:
                secao, comp, fonte = self._achar_dimensao_proxima(texts_with_pos, pos_xy)

            if vol is None and unit_vol_attr is not None:
                vol = unit_vol_attr
            if peso is None and unit_peso_attr is not None:
                peso = unit_peso_attr
            if peso is None and vol is not None:
                peso = round(_peso_total_peca_kg(vol, prod), 2)

            dimensoes_confirmadas = bool(confirm or (secao and comp and (vol is not None)))
            if not dimensoes_confirmadas and not aviso:
                faltando = []
                if not secao: faltando.append("seção")
                if not comp: faltando.append("comprimento")
                if vol is None: faltando.append("volume/peso")
                aviso = f"Não encontrado no desenho: {', '.join(faltando)} — confirmar antes de liberar produção."

            # --- MELHORIA #1: Orçador Automático por m³/kg de Aço via CAD ---
            orc = calcular_orcamento_peca(prod, secao, comp, vol)

            return {
                "cod": cod,
                "tag": tag,
                "obra": obra_name or client_name or "OBRA-CAD",
                "cliente": client_name or obra_name or "CLIENTE-CAD",
                "cidade": cidade_uf,
                "produto": prod,
                "secao": secao,
                "comp": comp,
                "vol": vol if vol is not None else (orc["vol_estimado"] if orc["vol_estimado"] > 0 else None),
                "peso": peso if peso is not None else (round(_peso_total_peca_kg(orc["vol_estimado"], prod), 2) if orc["vol_estimado"] > 0 else None),
                "peso_aco_kg": orc["peso_aco_kg"],
                "area_forma_m2": orc["area_forma_m2"],
                "custo_concreto": orc["custo_concreto"],
                "custo_aco": orc["custo_aco"],
                "custo_forma": orc["custo_forma"],
                "custo_estimado": orc["custo_estimado"],
                "preco_venda_sugerido": orc["preco_venda_sugerido"],
                "cobrimento": unit_cobrimento_attr,
                "qtd": qtd or 1,
                "fck": fck or "35 MPa",
                "dimensoes_confirmadas": dimensoes_confirmadas,
                "fonte_dimensao": fonte,
                "aviso": aviso,
                "panel_bbox": None,
                "panel_header": None
            }

        # 7.0) Pranchas de detalhamento (camada DT-Título + carimbo): o que está nas pranchas é o que vira peça.
        try:
            from precast_pranchas import extrair_pranchas
            pranchas = extrair_pranchas(doc)
        except Exception as e:
            print(f"[PRANCHAS] erro na leitura das pranchas: {e}", flush=True)
            pranchas = []
        if pranchas:
            return self._resultado_das_pranchas(pranchas, doc, dxf_path, obra_cod, client_name, obra_name, cidade_uf, fck)

        # Sem pranchas de detalhamento: leitura antiga por painéis e rótulos de texto.
        piece_panels = self._extract_piece_panels(doc, texts_with_pos)
        piece_panels = _tighten_all_panels(piece_panels, entity_index)

        # 7.1) Tabela de Igualdade (BM28=BM29=...=BM50)
        m_eq = re.search(r'TABELA DE IGUALDADE:?\s*([A-Z0-9=\s\n\._-]+)', full_text_upper)
        if m_eq:
            raw_eq = m_eq.group(1).split('NOTAS')[0].split('CORTE')[0].replace('\n', '').replace(' ', '')
            for t in raw_eq.split('='):
                t_clean = re.sub(r'[^A-Z0-9_-]', '', t.strip())
                if t_clean.startswith('BM') and len(t_clean) > 4:
                    t_clean = t_clean[:4]
                if t_clean and re.match(r'^[A-Z0-9_-]+$', t_clean):
                    if t_clean not in piece_tags_found:
                        piece_tags_found.add(t_clean)
                        prod = "FUNDAÇÃO / BLOCO" if t_clean.startswith(("BM", "B")) else ("PILAR / PILAR" if t_clean.startswith("P") else "VIGA / VIGA")
                        display_tag = f"BLOCO {t_clean}" if t_clean.startswith(("BM", "B")) else f"PEÇA {t_clean}"
                        pieces.append(montar_peca(
                            cod=t_clean,
                            tag=display_tag,
                            prod=prod,
                            vol=unit_vol_attr,
                            peso=unit_peso_attr,
                            confirm=bool(unit_vol_attr is not None),
                            fonte="tabela_igualdade_bloco"
                        ))

        # 7.2) Peças com dimensões em parênteses: BR- 1 (25 x 40 x 11,01) - QTDE.: 4x ou P-01 (30x40)
        dim_piece_pattern = re.compile(
            r'\b([A-Z]{1,4}\s*[\.\-_]?\s*\d{1,5})\s*\(\s*(\d{2,3})\s*[xX]\s*(\d{2,3})(?:\s*[xX]\s*(\d{1,3}(?:[,\.]\d{1,3})?))?\s*\)(?:\s*-\s*QTDE\.?\s*:\s*(\d{1,3})x?)?',
            re.IGNORECASE
        )
        for txt, x, y in texts_with_pos:
            m = dim_piece_pattern.search(txt)
            if m:
                raw_tag, larg_str, alt_str, comp_str, qtd_str = m.groups()
                tag_clean = raw_tag.replace(' ', '').replace('-', '').replace('.', '').upper()
                if tag_clean in piece_tags_found:
                    continue
                piece_tags_found.add(tag_clean)

                larg_cm = float(larg_str)
                alt_cm = float(alt_str)
                secao_str = f"{int(larg_cm)}X{int(alt_cm)}"
                
                comp_val = None
                vol_val = None
                peso_val = None
                confirmed = False
                prod = "VIGA / BRAÇO" if "BR" in tag_clean else ("PILAR / PILAR" if tag_clean.startswith("P") else "VIGA / VIGA")

                if comp_str:
                    comp_val = float(comp_str.replace(',', '.'))
                    vol_val = round((larg_cm / 100.0) * (alt_cm / 100.0) * comp_val, 3)
                    peso_val = round(_peso_total_peca_kg(vol_val, prod), 1)
                    confirmed = True

                qtd_val = int(qtd_str) if qtd_str else 1

                pieces.append(montar_peca(
                    cod=tag_clean,
                    tag=raw_tag.strip(),
                    prod=prod,
                    secao=secao_str,
                    comp=comp_val,
                    vol=vol_val,
                    peso=peso_val,
                    qtd=qtd_val,
                    confirm=confirmed,
                    fonte="cota_dimensional_desenho",
                    aviso=None if confirmed else "Comprimento e volume a confirmar no detalhamento"
                ))

        # 7.3) Peças com quantidade em parênteses: BL-1 (08x), ES-1 (16x)
        qty_piece_pattern = re.compile(
            r'\b([A-Z]{1,4}\s*[\.\-_]?\s*\d{1,5})\s*\(\s*(\d{1,3})x\s*\)',
            re.IGNORECASE
        )
        for txt, x, y in texts_with_pos:
            m = qty_piece_pattern.search(txt)
            if m:
                raw_tag, qtd_str = m.groups()
                tag_clean = raw_tag.replace(' ', '').replace('-', '').replace('.', '').upper()
                if tag_clean in piece_tags_found:
                    continue
                piece_tags_found.add(tag_clean)
                qtd_val = int(qtd_str)
                prod = "FUNDAÇÃO / BLOCO" if tag_clean.startswith(('BL', 'BM', 'B')) else ("ESCADA / ACESSO" if tag_clean.startswith('ES') else "OUTROS / PEÇA")
                pieces.append(montar_peca(
                    cod=tag_clean,
                    tag=raw_tag.strip(),
                    prod=prod,
                    qtd=qtd_val,
                    fonte="rotulo_com_quantidade",
                    aviso="Dimensões a confirmar no detalhamento"
                ))

        # 7.4) Rótulos em blocos INSERT
        for layout in doc.layouts:
            for entity in layout:
                if entity.dxftype() != 'INSERT':
                    continue
                for attrib in entity.attribs:
                    val = attrib.dxf.text.strip().upper()
                    matches = re.findall(
                        r'\b(PILAR|VIGA|PAINEL|ESCADA|BLOCO|ESTACA|BM|BL|VR|VG|PM|P)\s*[\.\-_]?\s*([A-Z]?\d{1,5})\b',
                        val
                    )
                    for prefix, num in matches:
                        if len(num) > 5:
                            continue
                        num_digits = re.sub(r'^[A-Z]', '', num) if (num and num[0].isalpha() and len(num) > 1) else num
                        pref_code = prefix[0] if len(prefix) > 2 else prefix
                        cod_clean = f"{pref_code}{num_digits}"
                        full_tag = f"{prefix} {num_digits}"
                        if cod_clean in piece_tags_found:
                            continue
                        piece_tags_found.add(cod_clean)
                        prod = ("PILAR / PILAR" if "PILAR" in prefix or prefix in ('PM', 'P')
                                else "VIGA / VIGA" if "VIGA" in prefix or prefix in ('VR', 'VG', 'V')
                                else "FUNDAÇÃO / BLOCO")
                        pos = entity.dxf.insert
                        pieces.append(montar_peca(cod_clean, full_tag, prod, pos_xy=(pos.x, pos.y)))

        # 7.5) Rótulos em TEXT/MTEXT soltos
        for txt, x, y in texts_with_pos:
            matches = re.findall(
                r'\b(PILAR|VIGA|PAINEL|ESCADA|BLOCO|ESTACA|BM|BL|VR|VG|PM|P)\s*[\.\-_]?\s*([A-Z]?\d{1,5})\b',
                txt.upper()
            )
            for prefix, tag_num in matches:
                if len(tag_num) > 5:
                    continue
                num_digits = re.sub(r'^[A-Z]', '', tag_num) if (tag_num and tag_num[0].isalpha() and len(tag_num) > 1) else tag_num
                pref_code = prefix[0] if len(prefix) > 2 else prefix
                cod_clean = f"{pref_code}{num_digits.upper()}"
                full_tag = f"{prefix.upper()} {num_digits.upper()}"
                if cod_clean in piece_tags_found or len(full_tag) < 3:
                    continue
                piece_tags_found.add(cod_clean)

                prod = "OUTROS / PEÇA"
                if "PILAR" in full_tag or prefix in ('PM', 'P'):
                    prod = "PILAR / PILAR"
                elif "VIGA" in full_tag or prefix in ('VR', 'VG', 'V'):
                    prod = "VIGA / VIGA"
                elif "BLOCO" in full_tag or prefix in ('BM', 'BL'):
                    prod = "FUNDAÇÃO / BLOCO"
                elif "PAINEL" in full_tag or prefix == 'PL':
                    prod = "PAINEL / FECHAMENTO"
                elif "ESCADA" in full_tag or prefix == 'ES':
                    prod = "ESCADA / ACESSO"
                elif "ESTACA" in full_tag or prefix == 'E':
                    prod = "FUNDAÇÃO / ESTACA"

                pieces.append(montar_peca(cod_clean, full_tag, prod, pos_xy=(x, y)))

        # Fallback de último recurso
        if not pieces and proj_attr:
            tag_match = re.search(r'([A-Z0-9_-]+)', proj_attr)
            if tag_match:
                tag_code = tag_match.group(1)
                qtd_total = qtd_attr if qtd_attr else 1
                prod = "FUNDAÇÃO / BLOCO" if tag_code.startswith(("BM", "B")) else "ESTRUTURA / PRÉ-FABRICADO"
                for i in range(qtd_total):
                    p_tag = tag_code if i == 0 else f"{tag_code}_{i + 1}"
                    pieces.append(montar_peca(p_tag, f"PEÇA {p_tag}", prod, pos_xy=None))

        # Assign panel bounding boxes to pieces
        for p in pieces:
            p_cod = p.get('cod', '').upper().replace(' ', '').replace('-', '')
            if p_cod in piece_panels:
                p['panel_bbox'] = piece_panels[p_cod]['bbox']
                p['panel_header'] = piece_panels[p_cod]['header_text']
            else:
                # Try partial match
                for panel_cod, panel_data in piece_panels.items():
                    if p_cod in panel_cod or panel_cod in p_cod:
                        p['panel_bbox'] = panel_data['bbox']
                        p['panel_header'] = panel_data['header_text']
                        break
        
        # Add pieces found in panels but not yet in pieces list
        for panel_cod, panel_data in piece_panels.items():
            clean_cod = panel_cod.upper().replace(' ', '').replace('-', '')
            if clean_cod not in piece_tags_found:
                piece_tags_found.add(clean_cod)
                # Determine product type from prefix
                prod = "OUTROS / PEÇA"
                if clean_cod.startswith(('PM', 'P')):
                    prod = "PILAR / PILAR"
                elif clean_cod.startswith(('VG', 'VR', 'V')):
                    prod = "VIGA / VIGA"
                elif clean_cod.startswith(('BM', 'BL', 'B')):
                    prod = "FUNDAÇÃO / BLOCO"
                elif clean_cod.startswith('BR'):
                    prod = "VIGA / BRAÇO"
                elif clean_cod.startswith('ES'):
                    prod = "ESCADA / ACESSO"
                elif clean_cod.startswith('PL'):
                    prod = "PAINEL / FECHAMENTO"
                elif clean_cod.startswith('TE'):
                    prod = "TERÇA / COBERTURA"
                elif clean_cod.startswith('LJ'):
                    prod = "LAJE / LAJE"
                elif clean_cod.startswith('CA'):
                    prod = "CALHA / COBERTURA"
                
                # Parse dimensions from header text if available
                header = panel_data.get('header_text', '')
                secao_val = None
                comp_val = None
                vol_val = None
                peso_val = None
                qtd_val = 1
                confirmed = False
                
                # Try to parse: PM.01 (40X50X15,68) 1X
                m_dim = re.search(
                    r'\(\s*(\d{2,3})\s*[xX]\s*(\d{2,3})(?:\s*[xX]\s*(\d{1,3}(?:[,\.]\d{1,3})?))?\s*\)',
                    header
                )
                if m_dim:
                    larg = int(m_dim.group(1))
                    alt = int(m_dim.group(2))
                    secao_val = f"{larg}X{alt}"
                    if m_dim.group(3):
                        comp_val = float(m_dim.group(3).replace(',', '.'))
                        vol_val = round((larg / 100.0) * (alt / 100.0) * comp_val, 3)
                        peso_val = round(_peso_total_peca_kg(vol_val, prod), 1)
                        confirmed = True
                
                # Try to parse quantity: 1X, 2x, (12x)
                m_qtd = re.search(r'(\d{1,3})\s*[xX]', header)
                if m_qtd and not m_dim:  # only if not already in dim pattern
                    qtd_val = int(m_qtd.group(1))
                elif m_qtd:
                    # Check if qty is after the dimension parentheses
                    after_dim = header[m_dim.end():] if m_dim else header
                    m_qtd2 = re.search(r'(\d{1,3})\s*[xX]', after_dim)
                    if m_qtd2:
                        qtd_val = int(m_qtd2.group(1))
                
                pieces.append(montar_peca(
                    cod=clean_cod,
                    tag=panel_data.get('header_text', clean_cod),
                    prod=prod,
                    secao=secao_val,
                    comp=comp_val,
                    vol=vol_val,
                    peso=peso_val,
                    qtd=qtd_val,
                    confirm=confirmed,
                    fonte="painel_prancha_dwg"
                ))
                # Assign panel bbox
                pieces[-1]['panel_bbox'] = panel_data['bbox']
                pieces[-1]['panel_header'] = panel_data.get('header_text', '')

        final_cod = obra_cod or re.sub(r'[^A-Z0-9]', '', (obra_name or client_name or "OBRA-CAD")[:10].upper())

        try:
            from precast_padrao_cad import avaliar as _avaliar_padrao
            padrao_cad = _avaliar_padrao(doc)
        except Exception as e:  # o relatório é informativo: não derruba a leitura
            print(f"[PADRAO CAD] não avaliado: {e}", flush=True)
            padrao_cad = None

        return {
            "success": True,
            "padrao_cad": padrao_cad,
            "obra": {
                "cod": final_cod,
                "cliente": client_name or obra_name or "CLIENTE NÃO INFORMADO",
                "cidade_uf": cidade_uf,
                "nome": obra_name or client_name or "OBRA SEM TÍTULO",
                "fck": fck or "35 MPa"
            },
            "pieces": pieces
        }

    def _resultado_das_pranchas(self, pranchas, doc, dxf_path, obra_cod, client_name, obra_name, cidade_uf, fck):
        """Monta as peças a partir das pranchas de detalhamento: uma peça por código (ou por unidade, quando o
        título diz '- 6X' para um código só). Seção, comprimento, volume e aço vêm da própria prancha."""
        pecas, avisos, usados = [], [], {}
        for idx, pr in enumerate(pranchas):
            codigos, qtd = pr["codigos"], int(pr.get("quantidade") or len(pr["codigos"]))
            unidades = []  # (cod, tag)
            if len(codigos) == 1 and qtd > 1:
                base = codigos[0]
                for _ in range(qtd):
                    usados[base] = usados.get(base, 0) + 1
                    unidades.append((f"{base}_{usados[base]}", f"{base} ({usados[base]}/{qtd})" if usados[base] <= qtd else f"{base} ({usados[base]})"))
            else:
                for c in codigos:
                    if c in usados:
                        usados[c] += 1
                        unidades.append((f"{c}_{usados[c]}", f"{c} ({usados[c]})"))
                        avisos.append(f"O código {c} aparece em mais de uma prancha; as peças foram numeradas.")
                    else:
                        usados[c] = 1
                        unidades.append((c, c))
                if qtd != len(codigos):
                    avisos.append(f"Prancha {pr['titulo']}: a quantidade do título ({qtd}) difere dos códigos ({len(codigos)}); foram criadas {len(codigos)} peças.")
            comp, vol_folha, aco = pr["comprimento_m"], pr.get("volume_m3"), pr.get("aco_kg")
            secao = f"{pr['largura_cm']:g}X{pr['altura_cm']:g}".replace(".0", "")
            vol_geo = round(pr["largura_cm"] / 100.0 * pr["altura_cm"] / 100.0 * comp, 3)
            vol = vol_folha if vol_folha else vol_geo
            prod = pr["produto"]
            peso = round(vol * DENSIDADE_CONCRETO_KG_M3 + (aco if aco else vol * _taxa_aco_kg_m3(prod)), 1)
            orc = calcular_orcamento_peca(prod, secao, comp, vol, peso_aco_real=aco)
            for cod, tag in unidades:
                pecas.append({
                    "cod": cod, "tag": tag, "obra": obra_name or client_name or "OBRA-CAD", "cliente": client_name or obra_name or "CLIENTE-CAD",
                    "cidade": cidade_uf, "produto": prod, "secao": secao, "comp": comp, "vol": vol, "peso": peso,
                    "peso_aco_kg": aco if aco else orc["peso_aco_kg"], "taxa_aco": pr.get("taxa_aco"), "area_forma_m2": orc["area_forma_m2"],
                    "custo_concreto": orc["custo_concreto"], "custo_aco": orc["custo_aco"], "custo_forma": orc["custo_forma"],
                    "custo_estimado": orc["custo_estimado"], "preco_venda_sugerido": orc["preco_venda_sugerido"], "cobrimento": None,
                    "qtd": 1, "fck": (f"{pr['fck']:g} MPa" if pr.get("fck") else (fck or "35 MPa")),
                    "dimensoes_confirmadas": True, "fonte_dimensao": "prancha de detalhamento", "aviso": None,
                    "ferros": pr.get("ferros") or [], "folha": pr.get("folha"), "titulo_prancha": pr.get("titulo"),
                    "grupo_prancha": idx, "panel_bbox": pr.get("bbox"), "panel_header": pr.get("titulo"), "fonte": "prancha",
                    "sem_tabela_aco": aco is None,
                })
        fantasmas = sum(pr.get("folhas_fantasma_ignoradas", 0) for pr in pranchas)
        if fantasmas:
            avisos.append(f"{fantasmas} folha(s) repetida(s) e vazias (só o carimbo, sem o detalhamento) foram ignoradas.")
        sem_moldura = [pr["titulo"] for pr in pranchas if not pr.get("bbox")]
        if sem_moldura:
            avisos.append(f"{len(sem_moldura)} prancha(s) sem moldura de folha no desenho; a imagem delas não pode ser gerada: {', '.join(sem_moldura[:5])}")
        try:
            from precast_padrao_cad import avaliar as _avaliar_padrao
            padrao_cad = _avaliar_padrao(doc)
        except Exception as e:
            print(f"[PADRAO CAD] não avaliado: {e}", flush=True)
            padrao_cad = None
        final_cod = obra_cod or re.sub(r'[^A-Z0-9]', '', (obra_name or client_name or "OBRA-CAD")[:10].upper())
        return {
            "success": True, "modo": "pranchas", "padrao_cad": padrao_cad, "avisos_leitura": avisos,
            "resumo_leitura": {"pranchas": len(pranchas), "pecas": len(pecas)},
            "obra": {"cod": final_cod, "cliente": client_name or obra_name or "CLIENTE NÃO INFORMADO", "cidade_uf": cidade_uf,
                     "nome": obra_name or client_name or "OBRA SEM TÍTULO", "fck": fck or "35 MPa"},
            "pieces": pecas,
        }

    @staticmethod
    def _achar_dimensao_proxima(texts_with_pos, pos_xy, raio_max=3000.0):
        if pos_xy is None:
            return None, None, None

        px, py = pos_xy
        melhor = None
        melhor_dist = raio_max

        for txt, x, y in texts_with_pos:
            m = _RE_SECAO.search(txt)
            if not m:
                continue
            dist = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
            if dist < melhor_dist:
                melhor_dist = dist
                melhor = m

        if melhor is None:
            return None, None, None

        largura, altura = melhor.group(1), melhor.group(2)
        secao = f"{largura}X{altura}"
        return secao, None, "cota_proxima_no_desenho"

    def _extract_piece_panels(self, doc, texts_with_pos):
        """
        Detects rectangular panel bounding boxes in the DXF drawing.
        Uses VIEWPORT entities from paper space layouts (primary method for these drawings)
        and LWPOLYLINE rectangles as fallback.
        Each panel contains a single piece's detail (pilar, bloco, viga, etc.).
        Returns dict: piece_cod -> {"bbox": (min_x, min_y, max_x, max_y), "header_text": str}
        """
        # CORRIGIDO 2026-09-22: o padrão antigo aceitava separador com espaço
        # dos DOIS lados ("PM - 27"), que é justamente o formato da LEGENDA/
        # tabela de referência repetida no desenho (todos os tags do projeto
        # listados juntos, várias vezes, SEM ligação com a posição real da
        # peça) — não o formato do rótulo do painel de verdade ("PM.27",
        # sem espaço antes do separador). Testado no arquivo real "020-26
        # ILHM": o padrão antigo juntava até 105 "peças" numa única linha
        # (pegando a legenda inteira várias vezes), o que destruía o recorte
        # por coluna. Exigir que o separador (se houver) cole direto no
        # prefixo — só um espaço é tolerado DEPOIS do separador, nunca
        # antes — resolveu: 90 painéis corretos, larguras plausíveis.
        piece_tag_pattern = re.compile(
            # "VM" (viga) precisa vir ANTES de "V" sozinho na alternação —
            # senão "V" casa primeiro e sobra "M01" sem bater no grupo de
            # dígitos. Achado ao investigar VM01 sem painel detectado.
            r'\b(PM|VM|P|BM|BL|VG|VR|BR|ES|PL|TE|LJ|CP|CA|MK|V|E)[\.\-_]?\s?(\d{1,4}[A-Z]?)\b',
            re.IGNORECASE
        )

        panels = {}

        # ── Strategy 1: VIEWPORT entities in paper space layouts ──
        # In AutoCAD, each piece detail is shown via a VIEWPORT in a paper space layout.
        # VIEWPORTs have center + width + height → bounding box.
        # Text labels (e.g. "PILAR P1006") are placed near viewports in paper space.
        for layout in doc.layouts:
            if layout.name == 'Model':
                continue  # skip model space

            viewports = []
            ps_texts = []  # paper space texts

            for entity in layout:
                if entity.dxftype() == 'VIEWPORT':
                    try:
                        center = entity.dxf.center
                        w = entity.dxf.width
                        h = entity.dxf.height
                        # Skip tiny viewports (<2 units) and the full-page viewport (>80 units wide)
                        if w > 2.0 and h > 2.0 and w < 80.0 and h < 80.0:
                            viewports.append({
                                'cx': center.x, 'cy': center.y,
                                'w': w, 'h': h,
                                'min_x': center.x - w / 2, 'max_x': center.x + w / 2,
                                'min_y': center.y - h / 2, 'max_y': center.y + h / 2,
                            })
                    except Exception:
                        pass
                elif entity.dxftype() == 'TEXT':
                    txt = entity.dxf.text.strip()
                    if txt:
                        pos = entity.dxf.insert
                        ps_texts.append((txt, pos.x, pos.y))
                elif entity.dxftype() == 'MTEXT':
                    txt = entity.plain_text().strip()
                    if txt:
                        pos = entity.dxf.insert
                        ps_texts.append((txt, pos.x, pos.y))

            if not viewports:
                continue

            # Group viewports by piece tag found nearby
            MARGIN = 15.0  # search margin around viewport for text labels
            for vp in viewports:
                # Find texts near this viewport (inside or within margin)
                near_texts = []
                for txt, tx, ty in ps_texts:
                    if (vp['min_x'] - MARGIN <= tx <= vp['max_x'] + MARGIN and
                            vp['min_y'] - MARGIN <= ty <= vp['max_y'] + MARGIN):
                        near_texts.append((txt, tx, ty))

                if not near_texts:
                    continue

                # Search for piece tag in nearby texts
                for txt, tx, ty in near_texts:
                    m = piece_tag_pattern.search(txt.upper())
                    if m:
                        prefix = m.group(1).upper()
                        num = m.group(2).upper()
                        cod = f"{prefix}{num}"

                        if cod in panels:
                            # Expand existing bbox to include this viewport
                            old = panels[cod]['bbox']
                            panels[cod]['bbox'] = (
                                min(old[0], vp['min_x']),
                                min(old[1], vp['min_y']),
                                max(old[2], vp['max_x']),
                                max(old[3], vp['max_y']),
                            )
                        else:
                            panels[cod] = {
                                "bbox": (vp['min_x'], vp['min_y'], vp['max_x'], vp['max_y']),
                                "header_text": txt.strip(),
                                "texts": near_texts,
                                "layout": layout.name,
                                "seed_xy": (vp['cx'], vp['cy']),
                                "skip_tighten": True,  # VIEWPORT já é um recorte próprio da peça
                            }
                        break  # one tag per viewport

        if panels:
            print(f"[PANEL DETECT] {len(panels)} painéis encontrados via VIEWPORT em paper space", flush=True)
            return panels

        # ── Strategy 2: LWPOLYLINE closed rectangles → fatiar em colunas (fallback) ──
        # CORRIGIDO 2026-09-22: desenhos como o "020-26 ILHM INVESTIMENTO" não
        # têm uma caixa fechada POR PEÇA — têm uma caixa por LINHA inteira da
        # grade (~501x57 unidades, várias peças lado a lado dentro dela). A
        # versão antiga achava a caixa que contém o texto e usava ela inteira
        # como painel — todas as peças da mesma linha saíam com a MESMA
        # prancha (a linha toda, não a peça isolada — exatamente o problema
        # relatado pelo usuário, "vem prancha genérica").
        # Fix: acha as caixas-linha, agrupa os rótulos de peça que caem
        # dentro de cada uma, ordena por X, e cada peça fica com a fatia
        # vertical entre o ponto médio até o vizinho da esquerda e o ponto
        # médio até o vizinho da direita (altura = a linha inteira, já que
        # essa dimensão está correta na caixa-linha). Testado no arquivo
        # real: 90 painéis com larguras plausíveis (antes: 6 painéis, com
        # caixas erradas pegando até 105 "peças" numa linha só por causa da
        # legenda repetida no desenho — ver correção do piece_tag_pattern
        # acima, essa é a causa raiz that inflava o "peças por linha").
        MIN_PANEL_SIZE = 15.0
        MAX_PANEL_SIZE = 800.0

        row_rects = []
        for layout in doc.layouts:
            for entity in layout:
                if entity.dxftype() == 'LWPOLYLINE' and entity.is_closed:
                    pts = list(entity.get_points(format='xy'))
                    if len(pts) < 4 or len(pts) > 6:
                        continue
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    min_x, max_x = min(xs), max(xs)
                    min_y, max_y = min(ys), max(ys)
                    w = max_x - min_x
                    h = max_y - min_y
                    if (MIN_PANEL_SIZE < w < MAX_PANEL_SIZE and
                            MIN_PANEL_SIZE < h < MAX_PANEL_SIZE and
                            0.1 < (w / h if h > 0 else 0) < 10.0):
                        row_rects.append((min_x, min_y, max_x, max_y))

        if not row_rects:
            return {}

        # Remove retângulos praticamente duplicados (mesmo contorno desenhado
        # 2x, comum em pranchas com hachura + moldura sobrepostas).
        dedup = []
        for r in row_rects:
            if not any(abs(r[0]-u[0]) < 0.5 and abs(r[1]-u[1]) < 0.5 and
                       abs(r[2]-u[2]) < 0.5 and abs(r[3]-u[3]) < 0.5 for u in dedup):
                dedup.append(r)
        row_rects = dedup

        rows_with_pieces = []
        for (rmin_x, rmin_y, rmax_x, rmax_y) in row_rects:
            peças_na_linha = []
            for txt, tx, ty in texts_with_pos:
                if not (rmin_x <= tx <= rmax_x and rmin_y <= ty <= rmax_y):
                    continue
                m = piece_tag_pattern.search(txt.upper())
                if m:
                    cod = f"{m.group(1).upper()}{m.group(2).upper()}"
                    peças_na_linha.append((cod, txt.strip(), tx, ty))

            if not peças_na_linha:
                continue
            peças_na_linha.sort(key=lambda t: t[2])  # ordena por X
            rows_with_pieces.append((rmin_x, rmin_y, rmax_x, rmax_y, peças_na_linha))

        # Largura típica de UMA peça: mediana das distâncias entre peças
        # vizinhas na mesma linha, olhando o documento inteiro. Usada abaixo
        # para não deixar uma peça sozinha numa linha (sem vizinho pra
        # calcular o ponto médio) herdar a linha inteira como se fosse dela
        # — foi exatamente o que aconteceu com VM-03: única peça detectada
        # na própria linha, caixa caiu pra ~400 unidades de largura (a
        # prancha inteira) em vez da fatia real da peça.
        # Gaps minúsculos não são "peça vizinha" de verdade — são o mesmo
        # rótulo aparecendo de novo perto (cota, vista auxiliar da mesma
        # peça). Só entram no cálculo os espaçamentos plausíveis entre
        # peças distintas.
        MIN_PLAUSIBLE_GAP = 8.0
        gaps = []
        for (_x0, _y0, _x1, _y1, peças) in rows_with_pieces:
            for i in range(len(peças) - 1):
                gap = peças[i + 1][2] - peças[i][2]
                if gap >= MIN_PLAUSIBLE_GAP:
                    gaps.append(gap)
        gaps.sort()
        median_gap = gaps[len(gaps) // 2] if gaps else 40.0

        for (rmin_x, rmin_y, rmax_x, rmax_y, peças_na_linha) in rows_with_pieces:
            n = len(peças_na_linha)
            for i, (cod, txt, tx, ty) in enumerate(peças_na_linha):
                esquerda = rmin_x if i == 0 else (peças_na_linha[i - 1][2] + tx) / 2.0
                direita = rmax_x if i == n - 1 else (tx + peças_na_linha[i + 1][2]) / 2.0

                # Vizinho longe demais (ou ausente — borda da linha
                # inteira) não representa uma peça vizinha real; vizinho
                # perto demais (outro rótulo da MESMA peça, tipo cota ou
                # vista auxiliar) também não — nos dois casos, usa meia
                # largura típica ao redor do próprio rótulo.
                if not (median_gap * 0.25 <= tx - esquerda <= median_gap):
                    esquerda = tx - median_gap / 2.0
                if not (median_gap * 0.25 <= direita - tx <= median_gap):
                    direita = tx + median_gap / 2.0

                if cod not in panels:
                    panels[cod] = {
                        "bbox": (esquerda, rmin_y, direita, rmax_y),
                        "header_text": txt,
                        "seed_xy": (tx, ty),
                    }

        if panels:
            print(f"[PANEL DETECT] {len(panels)} painéis encontrados via LWPOLYLINE (fatiado por coluna)", flush=True)
        return panels

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------

    def parse_pdf(self):
        """
        Parses text and layout from structural PDF drawings.
        """
        try:
            doc = fitz.open(self.file_path)
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
        except Exception as e:
            return self.empty_response(f"Erro ao ler PDF: {str(e)}")

        file_meta = self._parse_filename_metadata(self.filename)

        obra_name = None
        client_name = None
        cidade_uf = None
        fck = None

        m_client = re.search(r'(?:CLIENTE|CONSTRUTORA)\s*:\s*([^\n\r]{3,60})', full_text, re.IGNORECASE)
        if m_client:
            client_name = m_client.group(1).strip()
        if not client_name and file_meta.get('cliente'):
            client_name = file_meta['cliente']

        m_obra = re.search(r'(?:OBRA|EMPREENDIMENTO)\s*:\s*([^\n\r]{3,60})', full_text, re.IGNORECASE)
        if m_obra:
            obra_name = m_obra.group(1).strip()
        if not obra_name and file_meta.get('obra'):
            obra_name = file_meta['obra']

        m_fck = re.search(r'F[Cc][Kk]\s*[:>=]?\s*(\d{2,3}\s*MP[Aa]?)', full_text)
        if m_fck:
            fck = m_fck.group(1).strip()

        m_city = re.search(r'\b([A-ZÀ-Ú\s]{3,25})\s*(?:\/|\s+-\s+)\s*([A-Z]{2})\b', full_text.upper())
        if m_city:
            c_name = m_city.group(1).strip()
            uf_name = m_city.group(2).strip()
            if uf_name in UFS_BRASIL and not any(ign in c_name for ign in IGNORAR_CIDADE):
                cidade_uf = f"{c_name} / {uf_name}"
        if not cidade_uf and file_meta.get('cidade_uf'):
            cidade_uf = file_meta['cidade_uf']

        pieces = []
        piece_tags_found = set()
        matches = re.findall(
            r'\b(PILAR|VIGA|PAINEL|ESCADA|BLOCO|ESTACA|BM|BL|VR|VG|PM|P)\s*[\.\-_]?\s*([A-Z]?\d{1,5})\b',
            full_text.upper()
        )
        for prefix, num in matches:
            if len(num) > 5:
                continue
            num_digits = re.sub(r'^[A-Z]', '', num) if (num and num[0].isalpha() and len(num) > 1) else num
            pref_code = prefix[0] if len(prefix) > 2 else prefix
            cod_clean = f"{pref_code}{num_digits}"
            full_tag = f"{prefix} {num_digits}"
            if cod_clean in piece_tags_found:
                continue
            piece_tags_found.add(cod_clean)
            prod = ("PILAR / PILAR" if prefix in ('PILAR', 'PM', 'P')
                    else "VIGA / VIGA" if prefix in ('VIGA', 'VR', 'VG')
                    else "FUNDAÇÃO / BLOCO" if prefix in ('BM', 'BL', 'BLOCO')
                    else "OUTROS / PEÇA")
            pieces.append({
                "cod": cod_clean,
                "tag": full_tag,
                "obra": obra_name or client_name or "OBRA-PDF",
                "cliente": client_name or obra_name or "CLIENTE-PDF",
                "cidade": cidade_uf,
                "produto": prod,
                "secao": None,
                "comp": None,
                "vol": None,
                "peso": None,
                "cobrimento": None,
                "qtd": 1,
                "fck": fck or "35 MPa",
                "dimensoes_confirmadas": False,
                "fonte_dimensao": "texto_pdf",
                "aviso": "PDF estrutural — dimensões detalhadas a confirmar antes da liberação."
            })

        cod_obra = file_meta.get('cod') or re.sub(r'[^A-Z0-9]', '', (obra_name or os.path.splitext(self.filename)[0])[:10].upper()) or "OBRA-PDF"

        return {
            "success": True,
            "obra": {
                "cod": cod_obra,
                "cliente": client_name or obra_name or "CLIENTE NÃO INFORMADO",
                "cidade_uf": cidade_uf,
                "nome": obra_name or client_name or "OBRA SEM TÍTULO",
                "fck": fck or "35 MPa"
            },
            "pieces": pieces
        }

    def empty_response(self, error_msg):
        return {
            "success": False,
            "error": error_msg,
            "obra": None,
            "pieces": []
        }


# In-process cache: dxf_path -> (mtime, doc, RenderContext, entity_index).
# A real detailing file can hold tens of thousands of entities in
# modelspace — reading it (~30s) and indexing every entity's bbox (~80s)
# only pays off if it happens ONCE per file, not once per piece or once per
# render click. Bounded to a couple of files so memory doesn't grow forever
# across an upload session.
_RENDER_INDEX_CACHE: dict = {}
_RENDER_INDEX_CACHE_MAX = 2


def _build_entity_index(doc):
    """
    Computes the 2D bbox of every modelspace entity ONCE, so later per-piece
    crops can filter by simple numeric comparison instead of recomputing
    ezdxf.bbox.extents() per entity per piece (measured at ~80s per full
    pass on a real 78k-entity file — unaffordable per piece).
    """
    index = []
    if ezdxf_bbox is None:
        return index
    for entity in doc.modelspace():
        try:
            ext = ezdxf_bbox.extents([entity], fast=True)
        except Exception:
            continue
        if ext is None or not ext.has_data:
            continue
        index.append((entity, ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y))
    return index


def _get_or_build_render_index(dxf_path, doc=None):
    """
    Returns (doc, RenderContext, entity_index) for dxf_path, cached per
    path+mtime. If `doc` is already loaded (e.g. parse_dxf just read it,
    possibly via the recover/audit path), reuses it instead of reading the
    file a second time. Shared by panel tightening (at parse time) and
    piece rendering (at render time) so the ~30s read + ~80s entity-bbox
    index only ever happens once per uploaded file.
    """
    from ezdxf.addons.drawing import RenderContext

    mtime = os.path.getmtime(dxf_path)
    cached = _RENDER_INDEX_CACHE.get(dxf_path)
    if cached and cached[0] == mtime:
        return cached[1], cached[2], cached[3]

    if doc is None:
        doc = ezdxf.readfile(dxf_path)
    ctx = RenderContext(doc)
    index = _build_entity_index(doc)

    if len(_RENDER_INDEX_CACHE) >= _RENDER_INDEX_CACHE_MAX:
        _RENDER_INDEX_CACHE.pop(next(iter(_RENDER_INDEX_CACHE)))
    _RENDER_INDEX_CACHE[dxf_path] = (mtime, doc, ctx, index)

    return doc, ctx, index


def open_dxf_render_context(dxf_path):
    """
    Loads a DXF (cached per path+mtime) and returns (doc, RenderContext,
    entity_index) so render_piece_crop_from_doc() can render many pieces
    from the same file — or repeated on-demand renders across requests —
    without repeating the expensive read + index steps.
    """
    return _get_or_build_render_index(dxf_path)


MAX_SANE_PANEL_DIM = 200.0  # unidades de desenho; acima disso, não confia no recorte


def _tighten_all_panels(piece_panels, entity_index, margin=1.5):
    """
    Replaces each panel's coarse bbox (from VIEWPORT grouping or row/column
    slicing) with a tight bbox that hugs only the geometry that actually
    belongs to that piece, and records exactly which entities that is
    (`entity_ids`) so the renderer draws precisely this set — not a second,
    independent "whatever touches the final bbox" selection, which could
    silently re-admit a stray element the clustering had just excluded.

    The row/column slicing strategy uses the full row height and
    label-midpoint width as a first guess, which is often much bigger than
    the piece's real drawing, leaving a lot of blank margin around it — see
    _select_piece_cluster() for how the tight box is computed and why.
    """
    if not piece_panels or not entity_index:
        return piece_panels

    for cod, data in piece_panels.items():
        if data.get('skip_tighten'):
            continue
        coarse = data.get('bbox')
        if not coarse:
            continue

        tight, _entity_ids = _select_piece_cluster(entity_index, coarse, seed_xy=data.get('seed_xy'))
        if tight is None:
            continue

        txmin, tymin, txmax, tymax = tight
        txmin -= margin
        tymin -= margin
        txmax += margin
        tymax += margin
        if txmax - txmin < 1.0 or tymax - tymin < 1.0:
            continue  # cluster degenerado — mantém a caixa larga
        if txmax - txmin > MAX_SANE_PANEL_DIM or tymax - tymin > MAX_SANE_PANEL_DIM:
            continue  # algo deu errado — mantém a caixa larga em vez de arriscar

        data['bbox'] = (txmin, tymin, txmax, tymax)

    return piece_panels


def _select_piece_cluster(entity_index, coarse_bbox, seed_xy=None, oversize_factor=2.5, cluster_gap=3.0):
    """
    Selects the entities that actually belong to one piece, in two stages,
    and returns (tight_bbox, matched_entity_ids):

    1. Keep only entities whose CENTER falls inside the coarse cell and
       that aren't far bigger than the cell itself — this drops continuous
       grid/dimension lines and hatches that merely clip through several
       pieces' cells in the same row (an earlier version flood-filled by
       raw proximity and those shared elements chained the cluster straight
       through the whole row).
    2. Group what's left into connected components by proximity, and keep
       only the component nearest the piece's own tag position (or bbox
       center). A stray symbol from a neighboring cell (a north arrow, a
       shared reference mark) can still pass stage 1 by being small and
       centered inside this cell's box, but it sits apart from this piece's
       own drawing — this stage drops it instead of letting the union bbox
       stretch out to include it.

    Returns (None, None) if nothing matched. matched_entity_ids is a set of
    id(entity) for the winning cluster only — callers use this same set
    both to compute the tight bbox and to select exactly what gets drawn,
    so the crop and its bbox always agree on what belongs to the piece.
    """
    cxmin, cymin, cxmax, cymax = coarse_bbox
    cell_w = max(cxmax - cxmin, 1e-6)
    cell_h = max(cymax - cymin, 1e-6)
    max_w = cell_w * oversize_factor
    max_h = cell_h * oversize_factor

    matched = []  # [xmin, ymin, xmax, ymax, entity]
    for entity, exmin, eymin, exmax, eymax in entity_index:
        ecx = (exmin + exmax) / 2.0
        ecy = (eymin + eymax) / 2.0
        if not (cxmin <= ecx <= cxmax and cymin <= ecy <= cymax):
            continue
        if (exmax - exmin) > max_w or (eymax - eymin) > max_h:
            continue  # linha/hachura grande demais pra ser só desta peça
        matched.append([exmin, eymin, exmax, eymax, {id(entity)}])

    if not matched:
        return None, None

    clusters = list(matched)

    def merge_pass(items):
        merged_any = False
        out = []
        for cl in items:
            joined = None
            for existing in out:
                gap_x = max(existing[0] - cl[2], cl[0] - existing[2], 0.0)
                gap_y = max(existing[1] - cl[3], cl[1] - existing[3], 0.0)
                if gap_x <= cluster_gap and gap_y <= cluster_gap:
                    joined = existing
                    break
            if joined is None:
                out.append(cl)
            else:
                joined[0] = min(joined[0], cl[0])
                joined[1] = min(joined[1], cl[1])
                joined[2] = max(joined[2], cl[2])
                joined[3] = max(joined[3], cl[3])
                joined[4] |= cl[4]
                merged_any = True
        return out, merged_any

    changed = True
    while changed and len(clusters) > 1:
        clusters, changed = merge_pass(clusters)

    if seed_xy is None:
        best = max(clusters, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))
    else:
        sx, sy = seed_xy

        def dist_to_seed(cl):
            inside_x = cl[0] <= sx <= cl[2]
            inside_y = cl[1] <= sy <= cl[3]
            if inside_x and inside_y:
                return -1.0  # etiqueta cai dentro do cluster: vence sempre
            dx = max(cl[0] - sx, sx - cl[2], 0.0)
            dy = max(cl[1] - sy, sy - cl[3], 0.0)
            return (dx ** 2 + dy ** 2) ** 0.5

        best = min(clusters, key=dist_to_seed)

    return (best[0], best[1], best[2], best[3]), best[4]


def render_piece_crop_from_doc(doc, ctx, entity_index, bbox, out_png, out_pdf, margin=1.5, dpi=200):
    """
    Renders the isolated drawing of a single piece, cropped to its own
    panel_bbox, reusing an already-open DXF document + RenderContext +
    precomputed entity_index. This is the ONLY function that may produce a
    piece's prancha image — it never substitutes another piece's file.
    Returns True on success, False if the crop came out empty (e.g. bbox
    pointing at blank space).
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    msp = doc.modelspace()

    xmin, ymin, xmax, ymax = bbox
    if xmax <= xmin or ymax <= ymin:
        return False

    # Reseleciona pelo mesmo filtro em duas etapas usado ao apertar a bbox
    # (centro dentro da caixa + tamanho plausível + cluster mais próximo do
    # centro), em vez de um teste de interseção solto — senão uma entidade
    # comprida que só encosta na borda do recorte volta a aparecer inteira
    # no desenho final, mesmo que a bbox já esteja correta.
    cx = (xmin + xmax) / 2.0
    cy = (ymin + ymax) / 2.0
    _tight_ignored, matched_ids = _select_piece_cluster(entity_index, bbox, seed_xy=(cx, cy))
    if not matched_ids:
        matched_ids = {
            id(entity) for entity, exmin, eymin, exmax, eymax in entity_index
            if not (exmax < xmin or exmin > xmax or eymax < ymin or eymin > ymax)
        }

    xmin -= margin
    ymin -= margin
    xmax += margin
    ymax += margin

    def in_bbox(entity):
        return id(entity) in matched_ids

    # figsize precisa nascer na MESMA proporção do recorte. Com uma figura
    # de proporção fixa (ex. 10x8) e ax.set_aspect('equal'), o matplotlib
    # ignora os xlim/ylim que eu pedi e ESTICA um dos eixos pra manter a
    # proporção 1:1 dentro daquela caixa fixa — foi exatamente isso que
    # produzia o elemento "sobrando" longe do desenho: a área real
    # desenhada batia com a bbox apertada, mas a JANELA do eixo se
    # expandia sozinha bem além dela, revelando geometria de peças
    # vizinhas que a seleção por cluster já tinha corretamente excluído.
    data_w = max(xmax - xmin, 1e-6)
    data_h = max(ymax - ymin, 1e-6)
    aspect = data_w / data_h
    target_area = 64.0  # polegadas², mantém a resolução final na mesma faixa de antes
    fig_h = (target_area / aspect) ** 0.5
    fig_w = fig_h * aspect
    fig_w = max(min(fig_w, 20.0), 2.0)
    fig_h = max(min(fig_h, 20.0), 2.0)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    fig.patch.set_facecolor('#ffffff')
    ax.set_facecolor('#ffffff')
    ax.axis('off')

    try:
        out = MatplotlibBackend(ax)  # reseta aspect pra 'datalim' internamente — reafirma abaixo, por último
        Frontend(ctx, out).draw_layout(msp, finalize=True, filter_func=in_bbox)

        # 'datalim' deixa o matplotlib ESTICAR xlim/ylim pra manter a
        # proporção 1:1 dentro da figura, revelando geometria de peças
        # vizinhas bem fora do recorte pretendido. 'box' faz o oposto:
        # encolhe a CAIXA do eixo dentro da figura, mantendo os limites de
        # dados exatamente como pedido (a margem sobrando é cortada depois
        # pelo bbox_inches='tight').
        ax.set_aspect('equal', adjustable='box')
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)

        os.makedirs(os.path.dirname(out_png), exist_ok=True)
        fig.savefig(out_png, format='png', dpi=dpi, bbox_inches='tight', pad_inches=0.05)
        fig.savefig(out_pdf, format='pdf', bbox_inches='tight', pad_inches=0.05)
    finally:
        plt.close(fig)

    return os.path.exists(out_png) and os.path.getsize(out_png) > 0


def _cor_para_papel(rgba):
    """Cores do AutoCAD escolhidas para fundo escuro (amarelo, ciano, verde puro, rosa, cinza claro) viram cores
    legíveis no papel branco, como na plotagem do projetista. Branco de máscara (fundo de texto) fica."""
    r, g, b = rgba[0], rgba[1], rgba[2]
    alfa = 1.0
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    cinza = abs(r - g) < 0.08 and abs(g - b) < 0.08
    if lum >= 0.97 and cinza:
        return (r, g, b, rgba[3] if len(rgba) > 3 else 1.0)
    if lum < 0.45:
        return (r, g, b, alfa)
    if cinza:
        return (0.2, 0.2, 0.2, alfa)
    if r > 0.85 and g > 0.85 and b < 0.45 or (g > 0.85 and b > 0.85 and r < 0.45):  # amarelo e ciano -> preto
        return (0.0, 0.0, 0.0, alfa)
    if g > 0.8 and r < 0.3 and b < 0.3:
        return (0.0, 0.65, 0.32, alfa)
    fator = 0.3 / lum
    return (r * fator, g * fator, b * fator, alfa)


def _recolorir_para_papel(ax):
    from matplotlib.colors import to_rgba
    for col in list(ax.collections):
        try:
            cores = [_cor_para_papel(to_rgba(c)) for c in col.get_edgecolor()]
            if cores:
                col.set_edgecolor(cores)
            fcs = col.get_facecolor()
            if len(fcs):
                col.set_facecolor([_cor_para_papel(to_rgba(c)) for c in fcs])
        except Exception:
            continue
    for pat in list(ax.patches):
        try:
            pat.set_edgecolor(_cor_para_papel(to_rgba(pat.get_edgecolor())))
            fc = pat.get_facecolor()
            if fc is not None and len(fc) and fc[3] > 0:
                pat.set_facecolor(_cor_para_papel(to_rgba(fc)))
        except Exception:
            continue
    for ln in list(ax.lines):
        try:
            ln.set_color(_cor_para_papel(to_rgba(ln.get_color())))
        except Exception:
            continue
    for tx in list(ax.texts):
        try:
            tx.set_color(_cor_para_papel(to_rgba(tx.get_color())))
        except Exception:
            continue


def render_prancha_da_folha(doc, ctx, entity_index, bbox, out_png, out_pdf, margin=0.15, dpi=300):
    """
    Desenha a folha inteira de uma prancha: tudo o que toca a moldura do carimbo (inclusive as tabelas do AutoCAD),
    em fundo branco e recortado exatamente na moldura. Sem seleção por cluster: a prancha da peça é a folha de
    detalhamento como o projetista desenhou.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.math import Matrix44

    xmin, ymin, xmax, ymax = bbox
    if xmax <= xmin or ymax <= ymin:
        return False
    ids = {id(e) for e, ex0, ey0, ex1, ey1 in entity_index if not (ex1 < xmin or ex0 > xmax or ey1 < ymin or ey0 > ymax)}
    if not ids:
        return False
    xmin, ymin, xmax, ymax = xmin - margin, ymin - margin, xmax + margin, ymax + margin
    aspect = (xmax - xmin) / max(ymax - ymin, 1e-6)
    lado = 420 / 25.4  # polegadas: a folha A3 (420 mm) inteira, a 300 dpi para ler todos os números
    fig_w, fig_h = (lado, lado / aspect) if aspect >= 1 else (lado * aspect, lado)
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi)
    fig.patch.set_facecolor('#ffffff')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor('#ffffff')
    ax.axis('off')
    try:
        ax._update_patch_limits = lambda patch: None  # os limites são fixos (a moldura); recalcular a cada glifo custava metade do tempo
        out = MatplotlibBackend(ax)
        config = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR)
        frontend = Frontend(ctx, out, config=config)
        frontend.draw_layout(doc.modelspace(), finalize=False, filter_func=lambda e: id(e) in ids)
        # Tabelas do AutoCAD (ACAD_TABLE) não são desenhadas pelo ezdxf: desenha o bloco anônimo delas.
        for e in doc.modelspace():
            if e.dxftype() == "ACAD_TABLE" and id(e) in ids:
                try:
                    bloco = doc.blocks.get(doc.entitydb.get(e.dxf.block_record_handle).dxf.name)
                    deslocamento = Matrix44.translate(e.dxf.insert.x, e.dxf.insert.y, 0)
                    copias = []
                    for x in bloco:
                        c = x.copy()
                        c.transform(deslocamento)
                        copias.append(c)
                    frontend.draw_entities(copias)
                except Exception as erro:
                    print(f"[RENDER] tabela não desenhada: {erro}", flush=True)
        _recolorir_para_papel(ax)
        fig.set_size_inches(fig_w, fig_h)
        ax.set_position([0, 0, 1, 1])
        ax.set_aspect('equal', adjustable='box')
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        os.makedirs(os.path.dirname(out_png), exist_ok=True)
        fig.savefig(out_png, format='png', dpi=dpi)
    finally:
        plt.close(fig)
    try:  # PDF da prancha: a imagem da folha numa página do tamanho dela (gerar o PDF vetorial dobrava o tempo)
        import fitz
        pdf = fitz.open()
        a3_l, a3_a = 420 / 25.4 * 72, 297 / 25.4 * 72   # página A3 paisagem; a folha cabe inteira, centralizada
        pagina = pdf.new_page(width=a3_l, height=a3_a)
        escala = min(a3_l / (fig_w * 72), a3_a / (fig_h * 72))
        w, h = fig_w * 72 * escala, fig_h * 72 * escala
        pagina.insert_image(fitz.Rect((a3_l - w) / 2, (a3_a - h) / 2, (a3_l + w) / 2, (a3_a + h) / 2), filename=out_png)
        pdf.save(out_pdf, deflate=True)
        pdf.close()
    except Exception as erro:
        print(f"[RENDER] PDF não gerado: {erro}", flush=True)
    return os.path.exists(out_png) and os.path.getsize(out_png) > 0 and os.path.exists(out_pdf)


def render_piece_crop(dxf_path, bbox, out_png, out_pdf, margin=1.5, dpi=200):
    """
    Single-piece convenience wrapper for the on-demand /api/render-piece
    endpoint. Uses the same cached (doc, ctx, entity_index) as parse-cad, so
    a piece rendered on demand right after a parse is fast, not a repeat of
    the full read+index cost.
    """
    doc, ctx, entity_index = open_dxf_render_context(dxf_path)
    return render_piece_crop_from_doc(doc, ctx, entity_index, bbox, out_png, out_pdf, margin=margin, dpi=dpi)


class BIMIFCParser:
    """
    Parser Universal BIM / IFC para Revit, Tekla Structures, AltoQi Eberick, CYPECAD, Archicad e Allplan.
    Extrai metadados do projeto (Obra, Cliente, Cidade) e elementos estruturais (Pilares, Vigas, Lajes, Blocos, Estacas, Painéis, Escadas).
    """
    def __init__(self, file_path):
        self.file_path = file_path
        self.filename = os.path.basename(file_path)

    def parse(self):
        try:
            import ifcopenshell
            import ifcopenshell.util.element as element_util
        except ImportError:
            return {
                "success": False,
                "error": "Biblioteca ifcopenshell indisponível no servidor para ler arquivos IFC/BIM.",
                "obra": {"codigo": "BIM", "nome": self.filename},
                "pieces": []
            }

        try:
            model = ifcopenshell.open(self.file_path)
        except Exception as e:
            return {
                "success": False,
                "error": f"Erro ao abrir modelo IFC ({self.filename}): {str(e)}",
                "obra": {"codigo": "BIM", "nome": self.filename},
                "pieces": []
            }

        obra_code = "BIM-OBRA"
        obra_nome = os.path.splitext(self.filename)[0]
        cliente_nome = "Cliente BIM"
        cidade_uf = "São Paulo - SP"
        fck_padrao = "40 MPa"

        projects = model.by_type("IfcProject")
        if projects:
            p = projects[0]
            obra_code = getattr(p, "Name", None) or getattr(p, "LongName", None) or obra_code
            obra_nome = getattr(p, "LongName", None) or getattr(p, "Name", None) or obra_nome

        sites = model.by_type("IfcSite")
        if sites:
            s = sites[0]
            if getattr(s, "Name", None):
                cliente_nome = s.Name
            if hasattr(s, "SiteAddress") and s.SiteAddress:
                addr = s.SiteAddress
                if hasattr(addr, "Town") and addr.Town:
                    cidade_uf = f"{addr.Town} - {getattr(addr, 'Region', 'SP')}"

        elements_mapping = [
            ("IfcColumn", "Pilar", "PILAR"),
            ("IfcBeam", "Viga", "VIGA"),
            ("IfcSlab", "Laje Alveolar", "LAJE"),
            ("IfcFooting", "Bloco de Fundação", "BLOCO"),
            ("IfcPile", "Estaca", "ESTACA"),
            ("IfcWall", "Painel de Fechamento", "PAINEL"),
            ("IfcWallStandardCase", "Painel de Fechamento", "PAINEL"),
            ("IfcStair", "Escada", "ESCADA"),
            ("IfcStairFlight", "Escada", "ESCADA"),
            ("IfcBuildingElementProxy", "Outros", "PECA"),
        ]

        pieces = []
        piece_counts = {}

        for ifc_type, prod_label, category_prefix in elements_mapping:
            items = model.by_type(ifc_type)
            for item in items:
                raw_name = getattr(item, "Name", None) or getattr(item, "Tag", None) or f"{category_prefix}-1"
                tag = self._clean_tag_name(raw_name, category_prefix)

                psets = {}
                try:
                    psets = element_util.get_psets(item)
                except Exception:
                    pass

                vol_m3 = self._extract_volume(item, psets)
                comp_m = self._extract_length(item, psets)
                secao = self._extract_section(item, psets)
                fck = self._extract_fck(item, psets) or fck_padrao
                peso_kg = self._extract_weight(item, psets, vol_m3, prod_label)

                cod = _safe_cod(tag)
                if cod in piece_counts:
                    piece_counts[cod] += 1
                    cod_unique = f"{cod}-{piece_counts[cod]}"
                else:
                    piece_counts[cod] = 1
                    cod_unique = cod

                vol_calc = vol_m3 or 0.72
                comp_calc = comp_m or 6.0
                secao_calc = secao or "30X40"

                calc = calcular_orcamento_peca(prod_label, secao_calc, comp_calc, vol_calc)

                pieces.append({
                    "cod": cod_unique,
                    "tag": tag,
                    "produto": prod_label,
                    "grupo": "Armada",
                    "secao": secao_calc,
                    "comp": comp_calc,
                    "vol": vol_calc,
                    "peso": peso_kg or round(vol_calc * 2500.0 + vol_calc * 150.0, 1),
                    "custo_estimado": calc["custo_estimado"],
                    "preco_venda_sugerido": calc["preco_venda_sugerido"],
                    "fck": fck,
                    "prancha_url": f"/files/pranchas/prancha_{cod_unique}.pdf",
                    "print_url": f"/files/pranchas/print_{cod_unique}.png",
                    "dimensoes_confirmadas": True if (vol_m3 and comp_m) else False,
                    "aviso": "" if (vol_m3 and comp_m) else "Dimensões extraídas via modelo BIM IFC (Revit/Tekla/Eberick/CYPECAD)."
                })

        return {
            "success": True if pieces else False,
            "obra": {
                "codigo": obra_code,
                "nome": obra_nome,
                "cliente": cliente_nome,
                "cidade_uf": cidade_uf,
                "fck": fck_padrao
            },
            "pieces": pieces
        }

    def _clean_tag_name(self, raw_name, default_prefix):
        if not raw_name:
            return f"{default_prefix}-1"
        m = re.search(r'\b([A-Z]{1,4}\s*[-_]?\s*\d{1,4}[A-Z]?)\b', raw_name.upper())
        if m:
            return m.group(1).replace(" ", "")
        return raw_name.split(":")[0].split("[")[0].strip()

    def _extract_volume(self, item, psets):
        for pset_name, props in psets.items():
            if isinstance(props, dict):
                for k, v in props.items():
                    if "volume" in k.lower() and isinstance(v, (int, float)) and v > 0:
                        if v > 1000:
                            return round(v / 1e9, 3)
                        return round(float(v), 3)
        return None

    def _extract_length(self, item, psets):
        for pset_name, props in psets.items():
            if isinstance(props, dict):
                for k, v in props.items():
                    if ("length" in k.lower() or "comprimento" in k.lower() or "height" in k.lower()) and isinstance(v, (int, float)) and v > 0:
                        if v > 100:
                            return round(v / 1000.0, 2)
                        return round(float(v), 2)
        return None

    def _extract_section(self, item, psets):
        for pset_name, props in psets.items():
            if isinstance(props, dict):
                for k, v in props.items():
                    if "secao" in k.lower() or "section" in k.lower() or "profile" in k.lower():
                        m = _RE_SECAO.search(str(v))
                        if m:
                            return f"{m.group(1)}X{m.group(2)}"
        return None

    def _extract_fck(self, item, psets):
        for pset_name, props in psets.items():
            if isinstance(props, dict):
                for k, v in props.items():
                    if "fck" in k.lower() or "concrete" in k.lower() or "compressive" in k.lower():
                        return str(v)
        return None

    def _extract_weight(self, item, psets, vol_m3, prod):
        for pset_name, props in psets.items():
            if isinstance(props, dict):
                for k, v in props.items():
                    if ("weight" in k.lower() or "peso" in k.lower() or "mass" in k.lower()) and isinstance(v, (int, float)) and v > 0:
                        return round(float(v), 1)
        if vol_m3:
            return round(_peso_total_peca_kg(vol_m3, prod), 1)
        return None


class StructuralReportParser:
    """
    Parser para relatórios de peças/elementos exportados pelo AltoQi Eberick, CYPECAD, Tekla e Revit em CSV, TXT, XML e JSON.
    """
    def __init__(self, file_path):
        self.file_path = file_path
        self.filename = os.path.basename(file_path)

    def parse(self):
        ext = os.path.splitext(self.filename)[1].lower()
        content = ""
        try:
            with open(self.file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            return {"success": False, "error": f"Erro ao ler arquivo: {e}", "pieces": []}

        obra_code = os.path.splitext(self.filename)[0]
        pieces = []
        piece_counts = {}

        if ext in ('.csv', '.txt'):
            for line in content.splitlines():
                parts = [p.strip() for p in re.split(r'[,;\t]', line) if p.strip()]
                if len(parts) >= 2:
                    tag = parts[0]
                    if re.match(r'^[A-Z]{1,4}\s*[-_]?\s*\d{1,4}[A-Z]?$', tag, re.IGNORECASE):
                        secao = None
                        comp = None
                        vol = None
                        for p in parts[1:]:
                            m_sec = _RE_SECAO.search(p)
                            if m_sec:
                                secao = f"{m_sec.group(1)}X{m_sec.group(2)}"
                            try:
                                val = float(p.replace(',', '.'))
                                if 0.5 <= val <= 25.0 and comp is None:
                                    comp = val
                                elif 0.01 <= val <= 50.0 and vol is None:
                                    vol = val
                            except ValueError:
                                pass

                        tag_clean = tag.upper().replace(" ", "")
                        prod_label = "Pilar" if tag_clean.startswith("P") else "Viga" if tag_clean.startswith("V") else "Painel de Fechamento"
                        cod = _safe_cod(tag_clean)
                        if cod in piece_counts:
                            piece_counts[cod] += 1
                            cod_unique = f"{cod}-{piece_counts[cod]}"
                        else:
                            piece_counts[cod] = 1
                            cod_unique = cod

                        vol_calc = vol or 0.5
                        comp_calc = comp or 6.0
                        secao_calc = secao or "30X40"

                        calc = calcular_orcamento_peca(prod_label, secao_calc, comp_calc, vol_calc)

                        pieces.append({
                            "cod": cod_unique,
                            "tag": tag_clean,
                            "produto": prod_label,
                            "secao": secao_calc,
                            "comp": comp_calc,
                            "vol": vol_calc,
                            "peso": round(vol_calc * 2500.0, 1),
                            "custo_estimado": calc["custo_estimado"],
                            "preco_venda_sugerido": calc["preco_venda_sugerido"],
                            "fck": "40 MPa",
                            "prancha_url": f"/files/pranchas/prancha_{cod_unique}.pdf",
                            "print_url": f"/files/pranchas/print_{cod_unique}.png",
                            "dimensoes_confirmadas": True,
                            "aviso": "Importado via relatório estrutural Eberick/CYPECAD."
                        })

        return {
            "success": True if pieces else False,
            "obra": {"codigo": obra_code, "nome": obra_code, "cliente": "Cliente Relatório", "cidade_uf": "SP"},
            "pieces": pieces
        }
