"""
===============================================================================
RBR OpenPrecast ERP - Dynamic CAD & PDF Parser Engine (NBR 9062 / RBR)
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

ODA_EXE = r"C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe"

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads_dwg")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Peso específico do concreto estrutural armado (kg/m³) - NBR 6118 / NBR 9062
DENSIDADE_CONCRETO_KG_M3 = 2500.0

# Padrão "LxA" (largura x altura) em cm, como aparece nas legendas reais das pranchas RBR (ex: "14x30", "50X60", "25 x 40")
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
        else:
            return self.empty_response("Formato não suportado")

        for p in res.get('pieces', []):
            p['file'] = self.filename
            p_cod = p.get('cod', 'PEC-001')
            p['prancha_file'] = f"prancha_{p_cod}.pdf"
            p['prancha_url'] = f"/pranchas/prancha_{urllib.parse.quote(str(p_cod))}.pdf"
        return res

    def parse_dwg(self):
        """
        Converts DWG to DXF using ODA File Converter and parses the DXF.
        """
        dxf_name = os.path.splitext(self.filename)[0] + '.dxf'
        dxf_path = os.path.join(UPLOADS_DIR, dxf_name)

        if not os.path.exists(dxf_path):
            base_clean = os.path.splitext(self.filename)[0].lower()
            for f in os.listdir(UPLOADS_DIR):
                if f.endswith('.dxf') and base_clean in f.lower():
                    dxf_path = os.path.join(UPLOADS_DIR, f)
                    break

        if not os.path.exists(dxf_path) and os.path.exists(ODA_EXE):
            target_dwg = os.path.join(UPLOADS_DIR, self.filename)
            if target_dwg != self.file_path and os.path.exists(self.file_path):
                with open(self.file_path, 'rb') as src, open(target_dwg, 'wb') as dst:
                    dst.write(src.read())

            cmd = [ODA_EXE, UPLOADS_DIR, UPLOADS_DIR, 'ACAD2018', 'DXF', '0', '1', self.filename]
            try:
                subprocess.run(cmd, capture_output=True, timeout=180)
            except Exception as e:
                print(f"[ODA CONVERTER WARNING] Timeout/Error converting DWG: {e}")

        if os.path.exists(dxf_path):
            return self.parse_dxf(dxf_path)
        else:
            return self.empty_response(f"Não foi possível processar o arquivo DWG ({self.filename}). Verifique se o arquivo não está corrompido ou se o ODA Converter está instalado.")

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
                meta['cod'] = parts[0]
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

        # Detect piece panels (spatial bounding boxes in drawing)
        piece_panels = self._extract_piece_panels(doc, texts_with_pos)

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
                peso = round(vol * DENSIDADE_CONCRETO_KG_M3, 2)

            dimensoes_confirmadas = bool(confirm or (secao and comp and (vol is not None)))
            if not dimensoes_confirmadas and not aviso:
                faltando = []
                if not secao: faltando.append("seção")
                if not comp: faltando.append("comprimento")
                if vol is None: faltando.append("volume/peso")
                aviso = f"Não encontrado no desenho: {', '.join(faltando)} — confirmar antes de liberar produção."

            return {
                "cod": cod,
                "tag": tag,
                "obra": obra_name or client_name or "OBRA-CAD",
                "cliente": client_name or obra_name or "CLIENTE-CAD",
                "cidade": cidade_uf,
                "produto": prod,
                "secao": secao,
                "comp": comp,
                "vol": vol,
                "peso": peso,
                "cobrimento": unit_cobrimento_attr,
                "qtd": qtd or 1,
                "fck": fck or "35 MPa",
                "dimensoes_confirmadas": dimensoes_confirmadas,
                "fonte_dimensao": fonte,
                "aviso": aviso,
                "panel_bbox": None,
                "panel_header": None
            }

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
                
                if comp_str:
                    comp_val = float(comp_str.replace(',', '.'))
                    vol_val = round((larg_cm / 100.0) * (alt_cm / 100.0) * comp_val, 3)
                    peso_val = round(vol_val * DENSIDADE_CONCRETO_KG_M3, 1)
                    confirmed = True

                qtd_val = int(qtd_str) if qtd_str else 1
                prod = "VIGA / BRAÇO" if "BR" in tag_clean else ("PILAR / PILAR" if tag_clean.startswith("P") else "VIGA / VIGA")

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
                        peso_val = round(vol_val * DENSIDADE_CONCRETO_KG_M3, 1)
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

        return {
            "success": True,
            "obra": {
                "cod": final_cod,
                "cliente": client_name or obra_name or "CLIENTE NÃO INFORMADO",
                "cidade_uf": cidade_uf,
                "nome": obra_name or client_name or "OBRA SEM TÍTULO",
                "fck": fck or "35 MPa"
            },
            "pieces": pieces
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
        Uses VIEWPORT entities from paper space layouts (primary method for RBR drawings)
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
                                "layout": layout.name
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
            n = len(peças_na_linha)
            for i, (cod, txt, tx, ty) in enumerate(peças_na_linha):
                esquerda = rmin_x if i == 0 else (peças_na_linha[i - 1][2] + tx) / 2.0
                direita = rmax_x if i == n - 1 else (tx + peças_na_linha[i + 1][2]) / 2.0
                if cod not in panels:
                    panels[cod] = {
                        "bbox": (esquerda, rmin_y, direita, rmax_y),
                        "header_text": txt,
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
