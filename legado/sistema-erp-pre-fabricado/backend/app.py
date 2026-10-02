import os
import sys
import json
import datetime
import tempfile
import threading
import urllib.parse
from flask import Flask, request, jsonify, send_from_directory, send_file

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads_dwg")
VIGAS_DIR = r"C:\Users\User\Documents\VIGAS"

os.makedirs(UPLOADS_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(BASE_DIR, "cad_engine"))
sys.path.insert(0, os.path.join(BASE_DIR, "backend"))

try:
    from dwg_parser import DynamicCADParser
except ImportError:
    DynamicCADParser = None

try:
    from trueqr_engine import TrueQREngine
except ImportError:
    TrueQREngine = None

try:
    from autocad_engine import run_autocad_extraction
except ImportError:
    run_autocad_extraction = None

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

def find_file_on_disk(filename):
    if not filename: return None
    clean_name = os.path.basename(filename)
    
    # 1. Check uploads_dwg
    p = os.path.join(UPLOADS_DIR, clean_name)
    if os.path.exists(p): return p
    
    # 2. Check temp vigas_dxf
    p = os.path.join(tempfile.gettempdir(), 'vigas_dxf', clean_name)
    if os.path.exists(p): return p
    
    # 3. Check VIGAS_DIR
    p = os.path.join(VIGAS_DIR, clean_name)
    if os.path.exists(p): return p
    
    # 4. Search common user project directories
    search_dirs = [
        UPLOADS_DIR,
        os.path.join(tempfile.gettempdir(), 'vigas_dxf'),
        r"R:\ENGENHARIA\DT_2026\RBR_COM_2026",
        VIGAS_DIR,
        r"C:\Users\User\Documents",
        r"C:\Users\User\Downloads",
        r"C:\Users\User\Desktop"
    ]
    base_no_ext = os.path.splitext(clean_name)[0].lower().replace("-folha 1", "").strip()
    # CORRIGIDO 2026-09-22: a busca "fuzzy" abaixo aceitava .dwg/.dxf/.pdf
    # indistintamente, mesmo quando quem chamou queria explicitamente um
    # .pdf (ex: procurar a prancha original de uma peça) — como a ordem do
    # os.walk não é garantida, ela podia devolver o .dwg quando o pedido era
    # .pdf, e o código seguinte tentava abrir o .dwg como PDF/DXF e falhava
    # silenciosamente (era a causa real de "Prancha original não
    # encontrada" mesmo com o desenho existindo no disco). Agora a busca
    # fuzzy só aceita arquivo com a MESMA extensão pedida.
    ext_pedida = os.path.splitext(clean_name)[1].lower()

    for s_dir in search_dirs:
        if os.path.exists(s_dir):
            for root, dirs, files in os.walk(s_dir):
                if clean_name in files:
                    return os.path.join(root, clean_name)
                # Match fuzzy basename, mas só na mesma extensão pedida
                for f in files:
                    if f.lower().endswith(ext_pedida) and base_no_ext and base_no_ext in f.lower():
                        return os.path.join(root, f)
    return None

from werkzeug.exceptions import HTTPException

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    import traceback
    print(f"[FLASK ERROR EXCEPTION] {e}", flush=True)
    traceback.print_exc()
    return jsonify({"success": False, "error": str(e)}), 500

@app.route('/favicon.ico')
def favicon():
    return ('', 204)

@app.route('/')
def index():
    return send_from_directory(FRONTEND_DIR, 'index.html')

DB_FILE = os.path.join(BASE_DIR, "backend", "database.json")

from db_sqlite import SQLiteDBManager, create_backup, get_connection

def load_db():
    return SQLiteDBManager.get_all_data()

from trueqr_engine import TrueQREngine

def save_db(data):
    # Backward compatible mirror to JSON and SQLite
    try:
        SQLiteDBManager.sync_to_json_backup()
    except Exception as e:
        print(f"[DB SAVE ERROR] {e}", flush=True)

@app.route('/track')
def track_mobile():
    return send_from_directory(FRONTEND_DIR, 'operador.html')

@app.route('/operador')
@app.route('/app')
def operador_app():
    return send_from_directory(FRONTEND_DIR, 'operador.html')

@app.route('/api/status', methods=['GET'])
def system_status():
    db = SQLiteDBManager.get_all_data()
    return jsonify({
        "status": "online",
        "system": "RBR OpenPrecast ERP",
        "database": "SQLite (WAL Mode ACID)",
        "pieces_count": len(db.get("pieces", [])),
        "obras_count": len(db.get("obras", [])),
        "history_count": len(db.get("production_history", []))
    })

@app.route('/api/projects', methods=['GET'])
def get_projects():
    db = SQLiteDBManager.get_all_data()
    return jsonify({
        "success": True,
        "obras": db.get("obras", []),
        "pieces": db.get("pieces", []),
        "production_history": db.get("production_history", []),
        "issues": db.get("issues", []),
        "operators": db.get("operators", [])
    })

@app.route('/api/operators', methods=['GET', 'POST'])
def handle_operators():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        nome = data.get('nome', '').strip()
        cargo = data.get('cargo', 'Operador').strip()
        matricula = data.get('matricula', '').strip()
        if nome:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM operators")
            next_id = f"op-{cur.fetchone()[0] + 1}"
            cur.execute("INSERT INTO operators (id, nome, cargo, matricula) VALUES (?, ?, ?, ?)",
                        (next_id, nome, cargo, matricula or str(100 + cur.fetchone()[0] if False else 105)))
            conn.commit()
            conn.close()
            db = SQLiteDBManager.get_all_data()
            return jsonify({"success": True, "operators": db['operators']})
        return jsonify({"success": False, "error": "Nome obrigatório"}), 400
    db = SQLiteDBManager.get_all_data()
    return jsonify({"success": True, "operators": db.get('operators', [])})

@app.route('/api/history', methods=['GET'])
def get_production_history():
    db = SQLiteDBManager.get_all_data()
    cod_filter = request.args.get('cod', '').strip().upper()
    hist = db.get('production_history', [])
    if cod_filter:
        hist = [h for h in hist if h.get('cod', '').upper() == cod_filter or h.get('tag', '').upper() == cod_filter]
    return jsonify({"success": True, "history": hist, "total": len(hist)})

@app.route('/api/report-issue', methods=['POST'])
def report_issue():
    data = request.get_json(force=True, silent=True) or {}
    cod = data.get('cod', '').strip().upper()
    operator = data.get('operator', 'Operador da Fábrica')
    issue_type = data.get('issue_type', 'Não Conformidade Geral')
    severity = data.get('severity', 'Média')
    description = data.get('description', '').strip()
    action_taken = data.get('action_taken', 'Aguardando Avaliação')

    if not cod or not description:
        return jsonify({"success": False, "error": "Código da peça e descrição da ocorrência são obrigatórios."}), 400

    issue_record, matched_piece = SQLiteDBManager.record_issue(
        cod=cod,
        operator=operator,
        issue_type=issue_type,
        severity=severity,
        description=description,
        action_taken=action_taken
    )

    return jsonify({
        "success": True,
        "message": f"Ocorrência {issue_record['id']} registrada com sucesso para a peça {issue_record['cod']}.",
        "issue": issue_record,
        "piece": matched_piece
    })

@app.route('/api/obras/edit', methods=['POST'])
def edit_obra():
    data = request.get_json(force=True, silent=True) or {}
    old_cod = data.get('old_cod', '').strip()
    new_cod = data.get('new_cod', '').strip()
    cliente = data.get('cliente', '').strip()
    cidade_uf = data.get('cidade_uf', '').strip()
    nome = data.get('nome', '').strip()
    fck = data.get('fck', '').strip()

    if not old_cod:
        return jsonify({"success": False, "error": "Código da obra é obrigatório."}), 400

    ok, msg = SQLiteDBManager.update_obra(
        old_cod=old_cod,
        new_cod=new_cod or old_cod,
        cliente=cliente,
        cidade_uf=cidade_uf,
        nome=nome or cliente,
        fck=fck
    )

    if ok:
        all_data = SQLiteDBManager.get_all_data()
        return jsonify({
            "success": True,
            "message": msg,
            "all_obras": all_data['obras'],
            "all_pieces": all_data['pieces']
        })
    else:
        return jsonify({"success": False, "error": msg}), 400

@app.route('/api/obras/delete', methods=['POST', 'DELETE'])
def delete_obra_route():
    data = request.get_json(force=True, silent=True) or {}
    cod = data.get('cod', '').strip() or request.args.get('cod', '').strip()
    if not cod:
        return jsonify({"success": False, "error": "Código da obra é obrigatório."}), 400
    
    ok, msg = SQLiteDBManager.delete_obra(cod)
    if ok:
        all_data = SQLiteDBManager.get_all_data()
        return jsonify({
            "success": True,
            "message": msg,
            "all_obras": all_data['obras'],
            "all_pieces": all_data['pieces']
        })
    else:
        return jsonify({"success": False, "error": msg}), 400

@app.route('/api/pieces/edit', methods=['POST'])
def edit_piece():
    data = request.get_json(force=True, silent=True) or {}
    cod = data.get('cod', '').strip()
    if not cod:
        return jsonify({"success": False, "error": "Código da peça é obrigatório."}), 400

    ok, msg = SQLiteDBManager.update_piece(data)
    if ok:
        all_data = SQLiteDBManager.get_all_data()
        return jsonify({
            "success": True,
            "message": msg,
            "all_obras": all_data['obras'],
            "all_pieces": all_data['pieces']
        })
    else:
        return jsonify({"success": False, "error": msg}), 400

@app.route('/api/pieces/delete', methods=['POST', 'DELETE'])
def delete_piece_route():
    data = request.get_json(force=True, silent=True) or {}
    cod = data.get('cod', '').strip() or request.args.get('cod', '').strip()
    if not cod:
        return jsonify({"success": False, "error": "Código da peça é obrigatório."}), 400

    ok, msg = SQLiteDBManager.delete_piece(cod)
    if ok:
        all_data = SQLiteDBManager.get_all_data()
        return jsonify({
            "success": True,
            "message": msg,
            "all_obras": all_data['obras'],
            "all_pieces": all_data['pieces']
        })
    else:
        return jsonify({"success": False, "error": msg}), 400

@app.route('/api/clear', methods=['DELETE', 'POST'])
def clear_projects():
    db = load_db()
    # Keep history and operators, clear pieces & obras
    db['obras'] = []
    db['pieces'] = []
    save_db(db)
    return jsonify({"success": True})

@app.route('/api/qr/generate', methods=['POST', 'GET'])
def generate_qr():
    if request.method == 'GET':
        content = request.args.get('content', 'RBR_PCP:DEMO')
        fg = request.args.get('fg', '#06628a')
        bg = request.args.get('bg', '#ffffff')
        ec = request.args.get('ec', 'H')
        size = int(request.args.get('size', 350))
    else:
        data = request.get_json(force=True, silent=True) or {}
        content = data.get('content', 'RBR_PCP:DEMO')
        fg = data.get('foreground') or data.get('fg', '#06628a')
        bg = data.get('background') or data.get('bg', '#ffffff')
        ec = data.get('errorCorrection') or data.get('ec', 'H')
        size = int(data.get('size', 350))

    data_url = TrueQREngine.generate_data_url(content, {
        'foreground': fg,
        'background': bg,
        'errorCorrection': ec,
        'size': size
    })
    svg_code = TrueQREngine.generate_svg(content, {
        'foreground': fg,
        'background': bg,
        'errorCorrection': ec,
        'size': size
    })
    return jsonify({
        "success": True,
        "content": content,
        "data_url": data_url,
        "svg": svg_code
    })

@app.route('/api/qr/piece/<cod>', methods=['GET'])
def generate_piece_qr(cod):
    db = load_db()
    clean_cod = cod.strip().upper().replace(" ", "")
    matched_piece = None
    for p in db.get('pieces', []):
        if p.get('cod', '').strip().upper().replace(" ", "") == clean_cod or p.get('tag', '').strip().upper().replace(" ", "") == clean_cod:
            matched_piece = p
            break
    
    piece_data = matched_piece or {
        "cod": cod,
        "tag": f"PEÇA {cod}",
        "obra": "RBR ESTRUTURAS",
        "peso": "3500"
    }

    base_url = request.host_url.rstrip('/')
    payload = TrueQREngine.build_piece_payload(piece_data, base_url=base_url, mode="url")
    data_url = TrueQREngine.generate_data_url(payload, {
        'foreground': request.args.get('fg', '#06628a'),
        'background': request.args.get('bg', '#ffffff'),
        'errorCorrection': request.args.get('ec', 'H'),
        'size': int(request.args.get('size', 350))
    })
    return jsonify({
        "success": True,
        "cod": cod,
        "payload": payload,
        "data_url": data_url,
        "track_url": f"{base_url}/track?cod={cod}",
        "piece": matched_piece
    })

@app.route('/api/qr/label-card/<cod>', methods=['GET'])
def generate_label_card(cod):
    db = load_db()
    clean_cod = cod.strip().upper().replace(" ", "")
    matched_piece = None
    for p in db.get('pieces', []):
        if p.get('cod', '').strip().upper().replace(" ", "") == clean_cod or p.get('tag', '').strip().upper().replace(" ", "") == clean_cod:
            matched_piece = p
            break
    
    piece_data = matched_piece or {
        "cod": cod,
        "tag": f"PEÇA {cod}",
        "obra": "RBR ESTRUTURAS",
        "secao": "50X60",
        "comp": "10.0",
        "vol": "1.6",
        "peso": "4000",
        "fck": "35 MPa",
        "fase_atual": 1
    }
    
    base_url = request.host_url.rstrip('/')
    card_data_url = TrueQREngine.generate_piece_label_card(piece_data, base_url=base_url)
    return jsonify({
        "success": True,
        "cod": cod,
        "card_data_url": card_data_url,
        "piece": piece_data
    })

@app.route('/api/bipar-qrcode', methods=['POST', 'GET'])
def bipar_qrcode():
    if request.method == 'GET':
        qrcode_text = request.args.get('cod', '') or request.args.get('qrcode', '')
        target_fase = request.args.get('fase')
        operator = request.args.get('operator', 'Scanner Fábrica')
    else:
        data = request.get_json(force=True, silent=True) or {}
        qrcode_text = data.get('qrcode', '') or data.get('cod', '')
        target_fase = data.get('fase')
        operator = data.get('operator', 'Scanner Fábrica')
    
    import datetime
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # If full URL is passed, extract ?cod=
    if "track?cod=" in qrcode_text:
        try:
            parsed = urllib.parse.urlparse(qrcode_text)
            q_params = urllib.parse.parse_qs(parsed.query)
            if 'cod' in q_params:
                qrcode_text = q_params['cod'][0]
        except Exception:
            pass

    cod_clean = qrcode_text.replace('RBR_PCP:', '').split('|')[0].strip().upper()
    
    updated_piece, action_desc = SQLiteDBManager.advance_piece_fase(
        cod=cod_clean,
        operator=operator,
        target_fase=target_fase
    )
    
    if updated_piece:
        all_data = SQLiteDBManager.get_all_data()
        return jsonify({
            "success": True,
            "message": f"Peça {updated_piece['cod']} ({updated_piece['tag']}) avançou para a Fase {updated_piece['fase_atual']}!",
            "action": action_desc,
            "piece": updated_piece,
            "all_obras": all_data['obras'],
            "all_pieces": all_data['pieces']
        })
    else:
        return jsonify({"success": False, "error": f"Peça '{cod_clean}' não localizada no sistema."}), 404

# CORRIGIDO 2026-09-22: convert_dxf_to_pdf recarregava o DXF inteiro (ezdxf.
# readfile, ~40s pro arquivo de 188MB da ILHM) E renderizava TODAS as 78 mil
# entidades no matplotlib de novo (draw_layout) A CADA CHAMADA — mesmo pra só
# trocar o recorte (crop_bbox) de uma peça diferente do MESMO arquivo. Isso
# fazia pedir a prancha de 2 peças seguidas do mesmo projeto grande dar
# timeout. Cache: guarda o (fig, ax) já carregado e renderizado por arquivo
# — a peça seguinte do mesmo arquivo só troca o xlim/ylim e salva de novo,
# sem reler nem re-renderizar nada. Limitado a 2 arquivos em cache (LRU
# simples) pra não estourar memória com desenhos gigantes.
_dxf_render_cache = {}
_dxf_render_cache_order = []
_dxf_render_lock = threading.Lock()
_DXF_RENDER_CACHE_MAX = 2

def _obter_render_cacheado(dxf_path):
    """Retorna (fig, ax) já renderizado pro dxf_path, usando cache quando
    possível. NÃO fecha a figura — quem chama decide quando descartar
    (fica em cache até ser despejado pelo limite ou o processo reiniciar)."""
    mtime = os.path.getmtime(dxf_path)
    cached = _dxf_render_cache.get(dxf_path)
    if cached and cached[2] == mtime:
        if dxf_path in _dxf_render_cache_order:
            _dxf_render_cache_order.remove(dxf_path)
        _dxf_render_cache_order.append(dxf_path)
        return cached[0], cached[1]

    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    print(f"[DXF RENDER CACHE] carregando/renderizando do zero: {os.path.basename(dxf_path)}", flush=True)
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    fig = plt.figure(figsize=(16, 9), dpi=200)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.axis('off')

    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp, finalize=True)

    # Guarda os extents totais (pra quando crop_bbox=None) já calculados,
    # evita reabrir o doc/bbox.extents de novo.
    from ezdxf import bbox as ezdxf_bbox_mod
    extents = ezdxf_bbox_mod.extents(msp)

    # Despeja o mais antigo se estourar o limite (fecha a figura de verdade
    # pra liberar memória do matplotlib).
    if dxf_path not in _dxf_render_cache and len(_dxf_render_cache_order) >= _DXF_RENDER_CACHE_MAX:
        old_path = _dxf_render_cache_order.pop(0)
        old_fig = _dxf_render_cache.pop(old_path, (None,))[0]
        if old_fig:
            try:
                plt.close(old_fig)
            except Exception:
                pass

    _dxf_render_cache[dxf_path] = (fig, ax, mtime, extents)
    _dxf_render_cache_order.append(dxf_path)
    return fig, ax


def convert_dxf_to_pdf(dxf_path, pdf_path, crop_bbox=None, png_path=None):
    """
    Renderiza o DXF em PDF (e opcionalmente PNG 200 DPI). Se crop_bbox
    (min_x, min_y, max_x, max_y) for passado, recorta SÓ essa região —
    é assim que uma peça específica sai isolada (painel dela no desenho),
    em vez da prancha inteira com todas as peças juntas. Sem crop_bbox,
    mantém o comportamento antigo (folha inteira) como fallback.
    """
    if crop_bbox is None and os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
        return True
    try:
        with _dxf_render_lock:
            fig, ax = _obter_render_cacheado(dxf_path)
            _, _, _, extents = _dxf_render_cache[dxf_path]

            if crop_bbox:
                xmin, ymin, xmax, ymax = crop_bbox
                dx = xmax - xmin
                dy = ymax - ymin
                margem_x = dx * 0.08 if dx > 0 else 1.0
                margem_y = dy * 0.08 if dy > 0 else 1.0
                ax.set_xlim(xmin - margem_x, xmax + margem_x)
                ax.set_ylim(ymin - margem_y, ymax + margem_y)
            elif extents.has_data:
                xmin, ymin, _ = extents.extmin
                xmax, ymax, _ = extents.extmax
                dx = xmax - xmin
                dy = ymax - ymin
                if dx > 0 and dy > 0:
                    ax.set_xlim(xmin - dx * 0.03, xmax + dx * 0.03)
                    ax.set_ylim(ymin - dy * 0.03, ymax + dy * 0.03)

            fig.savefig(pdf_path, format='pdf', bbox_inches='tight', pad_inches=0.05)
            if png_path:
                fig.savefig(png_path, format='png', dpi=200, bbox_inches='tight', pad_inches=0.05)

        return True
    except Exception as e:
        print(f"[DXF2PDF CONVERT ERROR] {e}", flush=True)
        return False

def extract_authentic_piece_drawing(piece):
    """
    Extracts the exact authentic prancha page and renders a high-res PNG print
    for the specified piece directly from the original uploaded DWG/DXF/PDF.
    Zero synthetic or fake geometry is created.
    """
    cod = str(piece.get('cod', 'PEC-001')).strip()
    tag = str(piece.get('tag', '')).strip()
    orig_file = piece.get('file', '')

    pdf_target_name = f"prancha_{cod}.pdf"
    png_target_name = f"print_{cod}.png"
    dwg_target_name = f"{cod}_PRANCHA.dwg"
    pdf_target_path = os.path.join(UPLOADS_DIR, pdf_target_name)
    png_target_path = os.path.join(UPLOADS_DIR, png_target_name)
    dwg_target_path = os.path.join(UPLOADS_DIR, dwg_target_name)

    # 0. PRIORIDADE MÁXIMA: se a peça tem panel_bbox (painel/viewport
    # detectado pelo parser na hora do upload — ver _extract_piece_panels em
    # dwg_parser.py), recorta SÓ esse retângulo do DXF original. Isso é o
    # que resolve "gerou a prancha inteira em vez de só a peça" — sem isso,
    # o código caía direto no fallback de renderizar a folha toda (com
    # todas as peças juntas) pra qualquer peça que pedisse a prancha.
    panel_bbox = piece.get('panel_bbox')
    if isinstance(panel_bbox, str):
        try:
            panel_bbox = json.loads(panel_bbox)
        except (ValueError, TypeError):
            panel_bbox = None
    if panel_bbox and orig_file:
        base_no_ext = os.path.splitext(os.path.basename(orig_file))[0]
        dxf_fonte = find_file_on_disk(base_no_ext + ".dxf")
        if not dxf_fonte and orig_file.lower().endswith('.dxf'):
            dxf_fonte = find_file_on_disk(orig_file)
        if dxf_fonte and os.path.exists(dxf_fonte):
            try:
                ok = convert_dxf_to_pdf(dxf_fonte, pdf_target_path, crop_bbox=tuple(panel_bbox), png_path=png_target_path)
                if ok and os.path.exists(pdf_target_path):
                    return pdf_target_path, (png_target_path if os.path.exists(png_target_path) else None)
            except Exception as e:
                print(f"[PANEL CROP ERROR] cod={cod}: {e}", flush=True)

    # 1. Try AutoCAD accoreconsole + AutoLISP RBR_EXTRAIR_PRANCHA if DWG
    if orig_file and orig_file.lower().endswith('.dwg') and run_autocad_extraction:
        dwg_disk = find_file_on_disk(orig_file)
        if dwg_disk and os.path.exists(dwg_disk):
            try:
                a_dwg, a_pdf, a_png = run_autocad_extraction(dwg_disk, cod)
                if a_pdf and os.path.exists(a_pdf):
                    return a_pdf, a_png
            except Exception as e:
                print(f"[AUTOCAD LSP RUN NOTICE] {e}")

    # 2. If both already exist and valid size, return
    if os.path.exists(pdf_target_path) and os.path.getsize(pdf_target_path) > 1000 and os.path.exists(png_target_path) and os.path.getsize(png_target_path) > 1000:
        return pdf_target_path, png_target_path

    # Look for matching original PDF or converted PDF
    found_pdf = None
    if orig_file:
        base_no_ext = os.path.splitext(os.path.basename(orig_file))[0]
        candidate = find_file_on_disk(base_no_ext + ".pdf")
        if candidate and os.path.exists(candidate) and os.path.getsize(candidate) > 0:
            found_pdf = candidate
        else:
            # Check if DXF/DWG exists to convert authentically
            candidate_dxf = find_file_on_disk(base_no_ext + ".dxf")
            if not candidate_dxf and orig_file.lower().endswith(('.dxf', '.dwg')):
                candidate_dxf = find_file_on_disk(orig_file)
            if candidate_dxf and os.path.exists(candidate_dxf):
                conv_pdf = os.path.join(UPLOADS_DIR, base_no_ext + ".pdf")
                if convert_dxf_to_pdf(candidate_dxf, conv_pdf):
                    found_pdf = conv_pdf

    if not found_pdf:
        for f in os.listdir(UPLOADS_DIR):
            if f.endswith('.pdf') and not f.startswith(('prancha_', 'print_', 'test_')):
                found_pdf = os.path.join(UPLOADS_DIR, f)
                break

    if found_pdf and os.path.exists(found_pdf):
        try:
            import fitz
            doc = fitz.open(found_pdf)
            total_pages = len(doc)
            target_page_idx = 0

            if total_pages > 1:
                clean_tag = tag.upper().replace(" ", "").replace("-", "")
                clean_cod = cod.upper().replace(" ", "").replace("-", "")
                for idx, page in enumerate(doc):
                    txt = page.get_text().upper().replace(" ", "").replace("-", "")
                    if clean_tag in txt or clean_cod in txt:
                        target_page_idx = idx
                        break

            # 1. Save authentic single-page vector PDF
            out_doc = fitz.open()
            out_doc.insert_pdf(doc, from_page=target_page_idx, to_page=target_page_idx)
            out_doc.save(pdf_target_path)
            out_doc.close()

            # 2. Render authentic 200 DPI PNG print
            pix = doc[target_page_idx].get_pixmap(dpi=200)
            pix.save(png_target_path)
            doc.close()

            return pdf_target_path, png_target_path
        except Exception as e:
            print(f"[EXTRACT AUTHENTIC DRAWING ERROR] {e}", flush=True)

    return None, None

@app.route('/pranchas/<path:filename>')
def serve_prancha(filename):
    clean_filename = urllib.parse.unquote(filename)
    clean_base = os.path.splitext(os.path.basename(clean_filename))[0]
    clean_ext = os.path.splitext(clean_filename)[1].lower()

    # 1. If explicit PNG print or PDF or DWG exists on disk
    found_path = find_file_on_disk(clean_filename)
    if found_path and os.path.exists(found_path) and os.path.isfile(found_path):
        if clean_ext == '.pdf':
            return send_file(found_path, mimetype='application/pdf', as_attachment=False)
        elif clean_ext in ('.png', '.jpg', '.jpeg'):
            return send_file(found_path, mimetype='image/png', as_attachment=False)
        elif clean_ext in ('.dwg', '.dxf'):
            return send_file(found_path, mimetype='application/acad', as_attachment=True)

    # 2. Look up matching piece
    cod_target = clean_base.replace('prancha_', '').replace('print_', '').replace('_PRANCHA', '').strip()
    db = load_db()
    matched_piece = None
    for p in db.get('pieces', []):
        p_cod = p.get('cod', '').upper().replace(" ", "")
        p_tag = p.get('tag', '').upper().replace(" ", "")
        c_upper = cod_target.upper().replace(" ", "")
        if c_upper and (c_upper == p_cod or c_upper == p_tag or clean_filename == p.get('prancha_file') or clean_filename == p.get('file')):
            matched_piece = p
            break

    if matched_piece:
        pdf_path, png_path = extract_authentic_piece_drawing(matched_piece)
        if clean_ext in ('.png', '.jpg', '.jpeg') and png_path and os.path.exists(png_path):
            return send_file(png_path, mimetype='image/png', as_attachment=False)
        if clean_ext in ('.dwg', '.dxf'):
            dwg_p = os.path.join(UPLOADS_DIR, f"{matched_piece.get('cod')}_PRANCHA.dwg")
            if os.path.exists(dwg_p):
                return send_file(dwg_p, mimetype='application/acad', as_attachment=True)
        if pdf_path and os.path.exists(pdf_path):
            return send_file(pdf_path, mimetype='application/pdf', as_attachment=False)

    return "Prancha original não encontrada", 404

@app.route('/api/parse-cad', methods=['POST'])
def parse_cad():
    try:
        saved_filename = None
        saved_path = None
        
        # 1. Check file upload in multipart/form-data
        if request.files and 'file' in request.files:
            uploaded_file = request.files['file']
            if uploaded_file and uploaded_file.filename:
                saved_filename = os.path.basename(uploaded_file.filename)
                saved_path = os.path.join(UPLOADS_DIR, saved_filename)
                try:
                    uploaded_file.save(saved_path)
                except Exception as e:
                    print(f"[FILE SAVE NOTICE] {e}", flush=True)

        # 2. Check X-Filename header
        if not saved_path:
            header_filename = request.headers.get('X-Filename', '')
            if header_filename:
                saved_filename = os.path.basename(urllib.parse.unquote(header_filename))

        # 3. Check JSON body
        data = {}
        if not saved_filename:
            data = request.get_json(force=True, silent=True) or {}
            req_fname = data.get('filename', '')
            if req_fname:
                saved_filename = os.path.basename(req_fname)

        # Check manual/custom metadata overrides provided by user
        custom_cod = request.form.get('custom_cod') or data.get('custom_cod', '')
        custom_cliente = request.form.get('custom_cliente') or data.get('custom_cliente', '')
        custom_cidade = request.form.get('custom_cidade') or data.get('custom_cidade', '')
        custom_fck = request.form.get('custom_fck') or data.get('custom_fck', '')

        # Resolve actual file path on disk
        if saved_filename:
            saved_path = find_file_on_disk(saved_filename)

        if saved_path and os.path.exists(saved_path):
            if DynamicCADParser:
                parser = DynamicCADParser(saved_path)
                res = parser.parse()
                if res.get('success'):
                    db = load_db()
                    obra = res.get('obra') or {}
                    new_pieces = res.get('pieces', [])

                    # Apply manual overrides if provided by user
                    if custom_cod:
                        obra['cod'] = custom_cod.strip()
                    if custom_cliente:
                        obra['cliente'] = custom_cliente.strip()
                        obra['nome'] = custom_cliente.strip()
                    if custom_cidade:
                        obra['cidade_uf'] = custom_cidade.strip()
                    if custom_fck:
                        obra['fck'] = custom_fck.strip()

                    # Add/Update Obra in DB
                    if obra:
                        existing_idx = next((i for i, o in enumerate(db['obras']) if o.get('cod') == obra.get('cod')), -1)
                        if existing_idx >= 0:
                            db['obras'][existing_idx] = obra
                        else:
                            db['obras'].append(obra)

                    base_url = request.host_url.rstrip('/')
                    # Add/Update Pieces in DB
                    for p in new_pieces:
                        if custom_cliente:
                            p['cliente'] = custom_cliente.strip()
                            p['obra'] = custom_cliente.strip()
                        if custom_cidade:
                            p['cidade'] = custom_cidade.strip()
                        if custom_fck:
                            p['fck'] = custom_fck.strip()

                        # CORRIGIDO 2026-09-22 (pedido do usuário): peça lançada NÃO entra
                        # direto na linha de produção. fase_atual=0 = "aguardando bipagem" —
                        # só vira Fase 1 quando o operador bipar o QR Code de verdade.
                        if 'fase_atual' not in p:
                            p['fase_atual'] = 0
                        if 'history' not in p:
                            p['history'] = []
                        
                        # Generate TrueQR payload and tracking URL
                        p['track_url'] = f"{base_url}/track?cod={p.get('cod')}"
                        p['prancha_url'] = f"/pranchas/prancha_{urllib.parse.quote(str(p.get('cod')))}.pdf"
                        p['print_url'] = f"/pranchas/print_{urllib.parse.quote(str(p.get('cod')))}.png"

                        if TrueQREngine:
                            p['qr_payload'] = TrueQREngine.build_piece_payload(p, base_url=base_url, mode="url")
                            p['trueqr_data_url'] = TrueQREngine.generate_data_url(p['qr_payload'], {
                                'foreground': '#06628a',
                                'background': '#ffffff',
                                'errorCorrection': 'H',
                                'size': 300
                            })
                        else:
                            p['qr_payload'] = f"RBR_PCP:{p.get('cod')}"
                            p['trueqr_data_url'] = ""

                        # CORRIGIDO 2026-09-22: NÃO gera a prancha/print aqui mais.
                        # extract_authentic_piece_drawing(p) fazia o render de 200 DPI
                        # (fitz.get_pixmap numa página PDF gigante, o desenho inteiro
                        # renderizado em vetor) UMA VEZ POR PEÇA, de forma síncrona,
                        # dentro do mesmo request HTTP do upload. Num projeto com 86
                        # peças (caso real: "020 - 26 - ILHM INVESTIMENTO"), isso
                        # significava 86 renders pesados em sequência antes do upload
                        # sequer responder — era a causa real do "fica lendo e não
                        # entrega" reportado pelo usuário, não a leitura do DXF em si
                        # (essa sozinha leva ~45s pra esse arquivo de 188MB).
                        # A prancha/print continuam "vinculados ao lançamento" — a URL
                        # (prancha_url/print_url, linhas acima) já é gravada na peça
                        # imediatamente. O ARQUIVO em si nasce sob demanda, na primeira
                        # vez que alguém clica "Ver Prancha" — a rota /pranchas/<arquivo>
                        # já chama extract_authentic_piece_drawing(matched_piece) nesse
                        # momento (ver serve_prancha, poucas linhas acima), e a partir
                        # daí fica em cache no disco pras próximas vezes.
                        pass

                    # Persist Obra & Pieces in SQLite with ACID transaction
                    conn = get_connection()
                    cur = conn.cursor()
                    if obra and obra.get('cod'):
                        cur.execute("INSERT OR REPLACE INTO obras (cod, cliente, cidade_uf, nome, fck) VALUES (?, ?, ?, ?, ?)",
                                    (obra.get('cod'), obra.get('cliente'), obra.get('cidade_uf'), obra.get('nome'), obra.get('fck')))
                    
                    for p in new_pieces:
                        # panel_bbox vem do parser como lista [min_x,min_y,max_x,max_y]
                        # (coordenadas do DXF) — serializa pra JSON pra caber na coluna
                        # TEXT; é lido/desserializado de volta em extract_authentic_piece_drawing.
                        panel_bbox_json = json.dumps(p.get('panel_bbox')) if p.get('panel_bbox') else None
                        cur.execute("""
                        INSERT OR REPLACE INTO pieces
                        (cod, tag, obra, cliente, cidade, produto, secao, comp, vol, peso, qtd, fck, file, prancha_file, prancha_url, print_url, fase_atual, track_url, qr_payload, trueqr_data_url, panel_bbox, panel_header, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            p.get('cod'), p.get('tag'), p.get('obra'), p.get('cliente'), p.get('cidade'),
                            p.get('produto'), p.get('secao'), p.get('comp', 0), p.get('vol', 0), p.get('peso', 0),
                            p.get('qtd', 1), p.get('fck', '35 MPa'), p.get('file'), p.get('prancha_file'),
                            p.get('prancha_url'), p.get('print_url'), p.get('fase_atual', 0),
                            p.get('track_url'), p.get('qr_payload'), p.get('trueqr_data_url'),
                            panel_bbox_json, p.get('panel_header'),
                            p.get('updated_at', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        ))
                    
                    conn.commit()
                    conn.close()
                    
                    SQLiteDBManager.sync_to_json_backup()
                    create_backup()
                    
                    all_data = SQLiteDBManager.get_all_data()
                    c_name = obra.get('cliente') if obra else 'N/A'
                    print(f"[PARSE & STORED SUCCESS] File: {os.path.basename(saved_path)} -> Cliente: {c_name} ({len(new_pieces)} peças)", flush=True)
                    return jsonify({
                        "success": True,
                        "obra": obra,
                        "pieces": new_pieces,
                        "all_obras": all_data['obras'],
                        "all_pieces": all_data['pieces']
                    })
                else:
                    return jsonify(res)
            else:
                return jsonify({"success": False, "error": "DynamicCADParser engine não disponível."}), 500
        else:
            return jsonify({
                "success": False,
                "error": f"Arquivo '{saved_filename or 'desconhecido'}' não localizado no servidor.",
                "obra": None,
                "pieces": []
            }), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Erro interno no parse: {str(e)}"}), 500

if __name__ == '__main__':
    port = 2026
    print(f"🚀 Flask Server RBR OpenPrecast ERP rodando na porta {port}...", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
