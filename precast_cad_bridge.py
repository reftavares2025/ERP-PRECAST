import os
import re
import sys
import json
import shutil
import subprocess
import threading
import uuid
import urllib.request
import urllib.parse
import urllib.error
from flask import Response, Flask, request, jsonify, send_file

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from precast_caminhos import pasta_de_uploads

UPLOADS_DIR = pasta_de_uploads()


def _load_service_credentials():
    """
    Le a API key/secret de servico do ERPNext de um .env local (nunca
    commitado - ver .gitignore). Sem isso, as chamadas deste bridge pro
    ERPNext (que roda em processo separado, sem sessao de navegador) caiam
    como 403 Forbidden - os metodos do precast_api.py exigem usuario logado.
    """
    env_path = os.path.join(BASE_DIR, "precast_service_credentials.env")
    creds = {}
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip()
    return creds


_CREDS = _load_service_credentials()
PRECAST_API_KEY = _CREDS.get("PRECAST_API_KEY", "")
PRECAST_API_SECRET = _CREDS.get("PRECAST_API_SECRET", "")
EVOLUTION_APIKEY = _CREDS.get("EVOLUTION_APIKEY", "")
EVOLUTION_INSTANCE = _CREDS.get("EVOLUTION_INSTANCE", "precast_precast")
WHATSAPP_NUMERO = _CREDS.get("WHATSAPP_NUMERO", "")
EVOLUTION_URL = "http://localhost:8080"
PRANCHAS_BUNDLE_DIR = os.path.join(BASE_DIR, "pranchas_bundle")
os.makedirs(PRANCHAS_BUNDLE_DIR, exist_ok=True)

# Limite de peças renderizadas de forma síncrona durante o parse de um
# arquivo novo (a 1ª leitura do DXF já custa ~10-15s; cada render individual
# soma mais ~1-3s). Peças além do limite ficam marcadas como pendentes e são
# renderizadas sob demanda quando o usuário abre "Ver Prancha da Peça".
AUTO_RENDER_CAP = 15


import logging
logging.getLogger('ezdxf').setLevel(logging.CRITICAL)
logging.getLogger('matplotlib').setLevel(logging.CRITICAL)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

try:
    from dwg_parser import DynamicCADParser, render_piece_crop, open_dxf_render_context, render_piece_crop_from_doc, render_prancha_da_folha, _sem_janela
except ImportError as e:
    print(f"Warning: Could not import DynamicCADParser: {e}")
    DynamicCADParser = None
    render_prancha_da_folha = None

    def _sem_janela():
        return {}
    render_piece_crop = None
    open_dxf_render_context = None
    render_piece_crop_from_doc = None

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, PUT, DELETE'
    return response

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

SAMPLE_FILES = {
    '020-26': os.path.join(UPLOADS_DIR, "020 - 26 - ILHM INVESTIMENTO - PAULÍNIA - SP - REV-03 - DETALHAMENTO.dxf"),
    'BM28': os.path.join(UPLOADS_DIR, "BM28 A BM36 - BM42 A BM50.dxf"),
    'PO-52': os.path.join(UPLOADS_DIR, "PO-52 - 26 - SEVY - SENAI - PP.1.pdf"),
    'FAZENDA-MONICA': os.path.join(UPLOADS_DIR, "136 - 21 - FAZENDA MONICA - ANGATUBA - SP - DETALHAMENTO.dxf"),
    'VIGAS': os.path.join(UPLOADS_DIR, "V1.1.pdf")
}

try:
    _synced_cache = set(os.listdir(UPLOADS_DIR))
except Exception:
    _synced_cache = set()

def _safe_cod(cod):
    return re.sub(r'[^A-Za-z0-9_.\-]', '_', cod or 'PEC')


def _nome_prancha(obra_cod, p_cod):
    """Nome-base do arquivo da prancha. Leva o código da obra porque a mesma tag
    (P1, V1...) se repete entre projetos e uma prancha não pode sobrescrever a outra."""
    return f"{_safe_cod(obra_cod or 'OBRA')}__{_safe_cod(p_cod)}"


def _find_existing_crop(obra_cod, p_cod):
    candidates = [_nome_prancha(obra_cod, p_cod)]
    found_png = None
    found_pdf = None
    for c in candidates:
        test_png = os.path.join(UPLOADS_DIR, f"print_{c}.png")
        test_pdf = os.path.join(UPLOADS_DIR, f"prancha_{c}.pdf")
        if not found_png and os.path.exists(test_png):
            found_png = f"print_{c}.png"
        if not found_pdf and os.path.exists(test_pdf):
            found_pdf = f"prancha_{c}.pdf"
    return found_png, found_pdf


def sync_file_to_docker(file_path):
    """Copia o arquivo para o servidor web. Sempre copia: a prancha de uma peça pode ser regerada com o mesmo nome."""
    if not os.path.exists(file_path):
        return
    fname = os.path.basename(file_path)
    target = f"/home/frappe/frappe-bench/sites/frontend/public/files/pranchas/{fname}"
    try:
        subprocess.run(['docker', 'cp', file_path, f"erpnext-pre-fabricado-backend-1:{target}"], capture_output=True, timeout=30, **_sem_janela())
    except Exception as e:
        print(f"Error syncing {fname} to docker: {e}")


def sync_lote_para_docker(arquivos):
    """Copia vários arquivos para o servidor web numa só chamada (uma cópia por arquivo levava minutos)."""
    import shutil, tempfile
    arquivos = [a for a in arquivos if os.path.exists(a)]
    if not arquivos:
        return
    with tempfile.TemporaryDirectory() as tmp:
        for a in arquivos:
            shutil.copyfile(a, os.path.join(tmp, os.path.basename(a)))
        destino = "/home/frappe/frappe-bench/sites/frontend/public/files/pranchas/"
        try:
            subprocess.run(['docker', 'cp', tmp + os.sep + '.', f"erpnext-pre-fabricado-backend-1:{destino}"], capture_output=True, timeout=600, **_sem_janela())
        except Exception as e:
            print(f"Error syncing lote: {e}")


def _limpar_pranchas_da_obra(obra_cod):
    """Apaga as imagens e PDFs de prancha da obra (aqui no motor). Retorna quantos arquivos saíram."""
    base = _safe_cod(obra_cod or 'OBRA')
    removidos = 0
    for f in os.listdir(UPLOADS_DIR):
        if f.startswith((f"print_{base}__", f"prancha_{base}__")):
            try:
                os.remove(os.path.join(UPLOADS_DIR, f))
                removidos += 1
            except OSError:
                pass
    return removidos


import threading as _threading
_RENDER_LOCK = _threading.Lock()  # o matplotlib não é seguro para desenhar de duas leituras ao mesmo tempo
_PRANCHAS_STATUS = {}  # código da obra -> {"total", "feitas", "concluido"}


def _gerar_pranchas_das_folhas(job_id, obra, pieces, render_doc, render_ctx, render_index):
    """Modo pranchas: define o arquivo de cada peça, devolve a leitura já e desenha as folhas em segundo plano.
    Cada folha é desenhada UMA vez, do zero; peças iguais (ex. PM.01=02=03) recebem cópias do mesmo desenho."""
    import threading
    _limpar_pranchas_da_obra(obra.get('cod'))
    for p in pieces:
        safe = _nome_prancha(obra.get('cod'), p.get('cod'))
        p['print_url'] = f"/files/pranchas/print_{safe}.png"
        p['prancha_url'] = f"/files/pranchas/prancha_{safe}.pdf"
    chave = obra.get('cod')
    grupos = {p.get('grupo_prancha') for p in pieces}
    _PRANCHAS_STATUS[chave] = {"total": len(grupos), "feitas": 0, "concluido": False, "falhas": []}
    threading.Thread(target=_desenhar_pranchas, args=(chave, obra, [dict(p) for p in pieces], render_doc, render_ctx, render_index), daemon=True).start()


def _desenhar_pranchas(chave, obra, pieces, render_doc, render_ctx, render_index):
    import shutil
    status = _PRANCHAS_STATUS[chave]
    feitos, pendentes_sync = {}, []
    try:
        for p in pieces:
            g = p.get('grupo_prancha')
            safe = _nome_prancha(obra.get('cod'), p.get('cod'))
            png, pdf = os.path.join(UPLOADS_DIR, f"print_{safe}.png"), os.path.join(UPLOADS_DIR, f"prancha_{safe}.pdf")
            if g not in feitos:
                ok = False
                if p.get('panel_bbox') and render_doc is not None and render_prancha_da_folha is not None:
                    try:
                        with _RENDER_LOCK:
                            ok = render_prancha_da_folha(render_doc, render_ctx, render_index, p['panel_bbox'], png, pdf)
                    except Exception as e:
                        print(f"[RENDER ERROR] {p.get('cod')}: {e}", flush=True)
                feitos[g] = (png, pdf) if ok else None
                status["feitas"] += 1
                if not ok:
                    status["falhas"].append(p.get('cod'))
            elif feitos[g]:
                shutil.copyfile(feitos[g][0], png)
                shutil.copyfile(feitos[g][1], pdf)
            if feitos[g]:
                pendentes_sync.extend([png, pdf])
            if len(pendentes_sync) >= 24:
                sync_lote_para_docker(pendentes_sync)
                pendentes_sync = []
    finally:
        sync_lote_para_docker(pendentes_sync)
        status["concluido"] = True


@app.route('/api/pranchas-status', methods=['GET'])
def pranchas_status():
    cod = request.args.get('obra', '')
    return jsonify(_PRANCHAS_STATUS.get(cod, {"total": 0, "feitas": 0, "concluido": True, "falhas": []}))


def _conversor_dwg():
    try:
        from dwg_parser import localizar_conversor_dwg
        return localizar_conversor_dwg()
    except Exception:
        return None


@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({
        "status": "online",
        "service": "ERP Precast CAD & AI Extraction Bridge",
        "cad_parser": DynamicCADParser is not None,
        "conversor_dwg": {"instalado": bool(_conversor_dwg()), "caminho": _conversor_dwg()},
        "sample_projects": list(SAMPLE_FILES.keys())
    })


def _evolution_get(path):
    req = urllib.request.Request(
        f"{EVOLUTION_URL}{path}",
        headers={"apikey": EVOLUTION_APIKEY},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


@app.route('/api/whatsapp-qrcode', methods=['GET'])
def whatsapp_qrcode():
    """
    Proxy pro Evolution API - nunca expoe a apikey no navegador. Devolve o
    QR atual (expira em ~20-60s) e o status da conexao, pra pagina
    /whatsapp fazer polling e atualizar sozinha.
    """
    try:
        status_data = _evolution_get(f"/instance/connectionState/{EVOLUTION_INSTANCE}")
        conn_state = (status_data.get("instance") or {}).get("state", "close")
        if conn_state == "open":
            return jsonify({"success": True, "connected": True})

        qr_data = _evolution_get(f"/instance/connect/{EVOLUTION_INSTANCE}")
        return jsonify({
            "success": True,
            "connected": False,
            "base64": qr_data.get("base64"),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/whatsapp', methods=['GET'])
def whatsapp_pairing_page():
    numero_fmt = WHATSAPP_NUMERO or "não configurado"
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Conectar WhatsApp — ERP Precast</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; background:#07172c; color:#fff; display:flex;
         flex-direction:column; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:24px; text-align:center; }}
  h1 {{ font-size:20px; margin-bottom:4px; }}
  p.sub {{ color:#8ba2c0; font-size:14px; margin-bottom:24px; }}
  .box {{ background:#fff; padding:20px; border-radius:12px; width:280px; height:280px; display:flex; align-items:center; justify-content:center; }}
  .box img {{ max-width:100%; max-height:100%; }}
  .status {{ margin-top:20px; font-size:14px; color:#94a3b8; }}
  .status.ok {{ color:#22c55e; font-weight:700; font-size:18px; }}
  .steps {{ margin-top:24px; text-align:left; color:#8ba2c0; font-size:13px; max-width:320px; line-height:1.6; }}
</style>
</head>
<body>
  <h1>Conectar WhatsApp — número {numero_fmt}</h1>
  <p class="sub">Escaneie com o WhatsApp que vai enviar os avisos de contato</p>
  <div class="box" id="qrBox"><span style="color:#999;">Carregando QR...</span></div>
  <div class="status" id="statusMsg">Aguardando leitura...</div>
  <div class="steps">
    No celular: WhatsApp → ⋮ Mais opções → Aparelhos conectados → Conectar um aparelho → aponte a câmera aqui.<br><br>
    O QR expira em cerca de 30s — esta página renova sozinha.
  </div>
  <script>
    async function tick() {{
      try {{
        const r = await fetch('/api/whatsapp-qrcode');
        const d = await r.json();
        if (!d.success) {{ document.getElementById('statusMsg').textContent = 'Erro: ' + d.error; return; }}
        if (d.connected) {{
          document.getElementById('qrBox').innerHTML = '✅';
          document.getElementById('statusMsg').textContent = 'Conectado com sucesso!';
          document.getElementById('statusMsg').className = 'status ok';
          return;
        }}
        if (d.base64) {{
          document.getElementById('qrBox').innerHTML = `<img src="${{d.base64}}">`;
        }}
        setTimeout(tick, 15000);
      }} catch (e) {{
        document.getElementById('statusMsg').textContent = 'Erro de conexão, tentando de novo...';
        setTimeout(tick, 5000);
      }}
    }}
    tick();
  </script>
</body>
</html>"""
    return html

# Progresso de leitura/parse rodando em segundo plano, consultado pelo
# front-end via polling em /api/parse-status/<job_id> - assim a barra mostra
# percentual real em vez de um spinner indeterminado.
PARSE_JOBS = {}
_PARSE_JOBS_LOCK = threading.Lock()


def _set_job(job_id, **fields):
    with _PARSE_JOBS_LOCK:
        job = PARSE_JOBS.setdefault(job_id, {})
        job.update(fields)


def _registrar_erro(contexto):
    """O motor roda sem janela (pythonw): o erro vai para logs/motor_cad.log."""
    import traceback, datetime
    pasta = os.path.join(BASE_DIR, "logs")
    os.makedirs(pasta, exist_ok=True)
    with open(os.path.join(pasta, "motor_cad.log"), "a", encoding="utf-8") as f:
        f.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} — {contexto}\n{traceback.format_exc()}")
    if "WinError 433" in traceback.format_exc():
        _reiniciar_motor()


def _reiniciar_motor():
    """Depois de um WinError 433 (disco de rede desconectado) o processo fica com o erro preso e só
    um processo novo lê os desenhos de novo. Reinicia o motor em 2 segundos."""
    def _trocar():
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Timer(2.0, _trocar).start()


def _motivo_sem_pecas(target_path):
    nome = os.path.basename(target_path)
    if target_path.lower().endswith('.pdf'):
        try:
            import fitz
            with fitz.open(target_path) as doc:
                caracteres = sum(len(pg.get_text().strip()) for pg in doc)
            if caracteres == 0:
                return (f"Nenhuma peça identificada em '{nome}': este PDF não tem texto pesquisável "
                        f"(o texto foi convertido em curvas ao plotar). Envie o DXF ou o DWG do mesmo projeto.")
        except Exception:
            pass
        return (f"Nenhuma peça identificada em '{nome}'. O PDF precisa trazer o selo de cada peça "
                f"(tag, seção e comprimento). Se for um detalhamento de armadura, envie o DXF ou o DWG.")
    return f"Nenhuma peça identificada em '{nome}'. Confira se o desenho tem o selo das peças (tag, seção, comprimento)."


def _run_parse_job(job_id, target_path):
    try:
        # Desenhos trazem caminhos relativos (ex.: GEBASE.ctb). Se o diretório atual do processo
        # estiver num disco de rede desconectado, a leitura falha com WinError 433.
        os.chdir(BASE_DIR)
        is_dwg = target_path.lower().endswith('.dwg')
        _set_job(job_id, stage='Convertendo DWG para DXF...' if is_dwg else 'Lendo arquivo...', percent=10)

        parser = DynamicCADParser(target_path)
        res = parser.parse()

        if not res.get('success'):
            _set_job(job_id, done=True, error=res.get('error', 'Falha ao ler o arquivo CAD.'))
            return

        obra = res.get('obra', {})
        pieces = res.get('pieces', [])
        resolved_dxf_path = res.get('resolved_dxf_path')
        from precast_caminhos import revisao_do_arquivo
        obra['arquivo'] = os.path.basename(target_path)
        obra['revisao'] = revisao_do_arquivo(target_path)

        # Modelos BIM e relatórios (IFC, CSV...) não trazem selo de obra: o
        # código da obra vira o nome do arquivo, para as peças poderem ser gravadas.
        if not (obra.get('cod') or '').strip():
            obra['cod'] = _safe_cod(os.path.splitext(os.path.basename(target_path))[0]).upper()
            obra.setdefault('nome', obra['cod'])

        if not pieces:
            _set_job(job_id, done=True, error=_motivo_sem_pecas(target_path))
            return

        _set_job(job_id, stage=f'{len(pieces)} peças encontradas — preparando pranchas...', percent=55)

        render_doc = None
        render_ctx = None
        render_index = None
        if resolved_dxf_path and open_dxf_render_context and any(p.get('panel_bbox') for p in pieces):
            try:
                render_doc, render_ctx, render_index = open_dxf_render_context(resolved_dxf_path)
            except Exception as e:
                print(f"[RENDER ERROR] Não foi possível abrir {resolved_dxf_path}: {e}")

        if res.get('modo') == 'pranchas':
            _gerar_pranchas_das_folhas(job_id, obra, pieces, render_doc, render_ctx, render_index)
            _set_job(job_id, done=True, percent=100, stage='Concluído', result={
                "success": True, "filename": os.path.basename(target_path), "obra": obra, "pieces": pieces, "total_pieces": len(pieces),
                "modo": "pranchas", "pranchas_em_segundo_plano": True, "resumo_leitura": res.get("resumo_leitura"), "avisos_leitura": res.get("avisos_leitura"),
                "padrao_cad": res.get("padrao_cad"), "resolved_dxf_path": resolved_dxf_path,
            })
            return

        rendered_count = 0
        total = max(len(pieces), 1)
        for idx, p in enumerate(pieces):
            p_cod = p.get('cod', '')
            safe_cod = _nome_prancha(obra.get('cod'), p_cod)

            found_png, found_pdf = _find_existing_crop(obra.get('cod'), p_cod)

            if not found_png and render_doc is not None and p.get('panel_bbox'):
                if rendered_count < AUTO_RENDER_CAP:
                    out_png = os.path.join(UPLOADS_DIR, f"print_{safe_cod}.png")
                    out_pdf = os.path.join(UPLOADS_DIR, f"prancha_{safe_cod}.pdf")
                    try:
                        ok = render_piece_crop_from_doc(render_doc, render_ctx, render_index, p['panel_bbox'], out_png, out_pdf)
                    except Exception as e:
                        print(f"[RENDER ERROR] {p_cod}: {e}")
                        ok = False
                    if ok:
                        found_png = os.path.basename(out_png)
                        found_pdf = os.path.basename(out_pdf)
                    rendered_count += 1
                else:
                    p['prancha_pendente'] = True

            if found_png and not found_pdf:
                candidate_pdf = "prancha_" + found_png[len("print_"):-4] + ".pdf"
                if os.path.exists(os.path.join(UPLOADS_DIR, candidate_pdf)):
                    found_pdf = candidate_pdf

            if found_png:
                sync_file_to_docker(os.path.join(UPLOADS_DIR, found_png))
                p['print_url'] = f"/files/pranchas/{found_png}"
                if found_pdf:
                    sync_file_to_docker(os.path.join(UPLOADS_DIR, found_pdf))
                    p['prancha_url'] = f"/files/pranchas/{found_pdf}"
                else:
                    p['prancha_url'] = None
            else:
                p['prancha_url'] = None
                p['print_url'] = None
                if not p.get('panel_bbox'):
                    p['aviso'] = (p.get('aviso') or '') + \
                        " Prancha isolada não disponível para esta origem (sem geometria detectada)."
                elif p.get('prancha_pendente'):
                    p['aviso'] = (p.get('aviso') or '') + \
                        " Prancha ainda não gerada — abra 'Ver Prancha da Peça' para renderizar agora."

            _set_job(
                job_id,
                stage=f'Gerando prancha da peça {idx + 1}/{len(pieces)} ({p_cod})...',
                percent=55 + int(40 * (idx + 1) / total),
            )

        _set_job(
            job_id,
            done=True,
            percent=100,
            stage='Concluído',
            result={
                "success": True,
                "filename": os.path.basename(target_path),
                "obra": obra,
                "pieces": pieces,
                "total_pieces": len(pieces),
                "padrao_cad": res.get("padrao_cad"),
                "resolved_dxf_path": resolved_dxf_path,
            },
        )

    except Exception as e:
        _registrar_erro(f"leitura de {os.path.basename(target_path)}")
        if "WinError 433" in str(e):
            _set_job(job_id, done=True, error="O motor CAD perdeu o acesso a um disco de rede (R:) e está reiniciando sozinho. "
                                              "Aguarde uns 10 segundos e envie o arquivo de novo.")
        else:
            _set_job(job_id, done=True, error=str(e))


@app.route('/api/limpar-obra', methods=['POST'])
def limpar_obra():
    """Chamado depois que a obra é excluída no sistema: apaga aqui as pranchas geradas dela."""
    dados = request.get_json(silent=True) or {}
    cod = (dados.get('codigo_obra') or '').strip()
    if not cod:
        return jsonify({"success": False, "error": "Informe o código da obra."}), 400
    return jsonify({"success": True, "arquivos_removidos": _limpar_pranchas_da_obra(cod)})


@app.route('/api/padrao-cad', methods=['GET'])
def padrao_cad():
    import precast_padrao_cad
    return jsonify(precast_padrao_cad.padrao())


@app.route('/api/padrao-cad.scr', methods=['GET'])
def padrao_cad_script():
    import precast_padrao_cad
    return Response(precast_padrao_cad.script_autocad().encode('cp1252', 'replace'), mimetype='text/plain',
                    headers={'Content-Disposition': 'attachment; filename=padrao_camadas.scr'})


@app.route('/api/parse-cad', methods=['POST'])
def parse_cad():
    try:
        target_path = None

        # 1. Check multipart file upload
        if 'file' in request.files:
            f = request.files['file']
            if f and f.filename:
                target_path = os.path.join(UPLOADS_DIR, os.path.basename(f.filename))
                f.save(target_path)

        # 2. Check sample_id or filename in JSON or Form
        data = request.get_json(silent=True) or {}
        sample_id = request.form.get('sample_id') or data.get('sample_id')
        filename = request.form.get('filename') or data.get('filename')
        job_id = request.form.get('job_id') or data.get('job_id') or uuid.uuid4().hex

        if not target_path and sample_id and sample_id in SAMPLE_FILES:
            target_path = SAMPLE_FILES[sample_id]
        elif not target_path and filename:
            candidate = os.path.join(UPLOADS_DIR, os.path.basename(filename))
            if os.path.exists(candidate):
                target_path = candidate

        if not target_path or not os.path.exists(target_path):
            return jsonify({
                "success": False,
                "error": "Nenhum arquivo CAD válido recebido ou selecionado."
            }), 400

        _set_job(job_id, done=False, percent=2, stage='Arquivo recebido, iniciando leitura...', error=None, result=None)
        threading.Thread(target=_run_parse_job, args=(job_id, target_path), daemon=True).start()

        return jsonify({"success": True, "job_id": job_id})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/parse-status/<job_id>', methods=['GET'])
def parse_status(job_id):
    with _PARSE_JOBS_LOCK:
        job = PARSE_JOBS.get(job_id)
    if not job:
        return jsonify({"success": False, "error": "job_id desconhecido"}), 404
    return jsonify({
        "success": True,
        "done": job.get('done', False),
        "percent": job.get('percent', 0),
        "stage": job.get('stage', ''),
        "error": job.get('error'),
        "result": job.get('result'),
    })

@app.route('/api/render-piece', methods=['POST'])
def render_piece():
    """
    Renders (or re-renders) the isolated prancha of a single piece on demand.
    Used by the front-end when a piece's crop wasn't generated during the
    initial parse (AUTO_RENDER_CAP reached) or has no crop yet.
    """
    try:
        if render_piece_crop is None:
            return jsonify({"success": False, "error": "Renderizador indisponível no servidor."}), 500

        data = request.get_json(force=True)
        dxf_path = data.get('resolved_dxf_path')
        cod = data.get('cod')
        bbox = data.get('panel_bbox')

        if not dxf_path or not os.path.exists(dxf_path):
            return jsonify({"success": False, "error": "Arquivo DXF de origem não encontrado. Reimporte o projeto."}), 400
        if not cod or not bbox or len(bbox) != 4:
            return jsonify({"success": False, "error": "Peça sem geometria própria (panel_bbox) — não é possível isolar a prancha."}), 400

        safe_cod = _nome_prancha(data.get('obra'), cod)
        out_png = os.path.join(UPLOADS_DIR, f"print_{safe_cod}.png")
        out_pdf = os.path.join(UPLOADS_DIR, f"prancha_{safe_cod}.pdf")

        ok = render_piece_crop(dxf_path, bbox, out_png, out_pdf)
        if not ok:
            return jsonify({"success": False, "error": "Não foi possível isolar a prancha desta peça (região vazia no desenho)."}), 500

        sync_file_to_docker(out_png)
        sync_file_to_docker(out_pdf)

        return jsonify({
            "success": True,
            "print_url": f"/files/pranchas/{os.path.basename(out_png)}",
            "prancha_url": f"/files/pranchas/{os.path.basename(out_pdf)}"
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/integrate-to-erpnext', methods=['POST'])
def integrate_to_erpnext():
    try:
        payload = request.get_json(force=True)
        obra_data = payload.get('obra')
        pieces_data = payload.get('pieces')

        # Call Frappe API inside Docker container
        frappe_url = "http://localhost:8088/api/method/frappe.precast_api.integrate_parsed_project"
        req_data = json.dumps({
            "obra_data": obra_data,
            "pieces_data": pieces_data,
            "modo": payload.get('modo') or 'acrescentar',
        }).encode('utf-8')

        headers = {'Content-Type': 'application/json'}
        if PRECAST_API_KEY and PRECAST_API_SECRET:
            headers['Authorization'] = f'token {PRECAST_API_KEY}:{PRECAST_API_SECRET}'

        req = urllib.request.Request(frappe_url, data=req_data, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                frappe_res = json.loads(resp.read().decode('utf-8'))
                return jsonify(frappe_res.get('message', frappe_res))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            if e.code == 403:
                return jsonify({"success": False, "error": "Sem permissão pra gravar no ERPNext (credencial de serviço ausente ou inválida em precast_service_credentials.env)."}), 403
            return jsonify({"success": False, "error": f"ERPNext retornou erro {e.code}: {body[:300]}"}), e.code

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = 2026
    print(f"🚀 ERP Precast CAD & AI Bridge rodando em http://localhost:{port}...", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
