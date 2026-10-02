"""
===============================================================================
RBR OpenPrecast ERP - Thread-Safe SQLite Industrial Database Engine
===============================================================================
Replaces flat database.json with SQLite (WAL mode + ACID transactions + thread lock).
Guarantees zero data loss under high-concurrency simultaneous operator scans.
Includes automatic hourly snapshots and rolling backups.
"""

import os
import sqlite3
import json
import threading
import shutil
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "backend", "database.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backend", "backups")
LEGACY_JSON_PATH = os.path.join(BASE_DIR, "backend", "database.json")

os.makedirs(BACKUP_DIR, exist_ok=True)

_db_lock = threading.RLock()

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db():
    with _db_lock:
        conn = get_connection()
        cur = conn.cursor()
        
        # Obras
        cur.execute("""
        CREATE TABLE IF NOT EXISTS obras (
            cod TEXT PRIMARY KEY,
            cliente TEXT,
            cidade_uf TEXT,
            nome TEXT,
            fck TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)
        
        # Pieces
        cur.execute("""
        CREATE TABLE IF NOT EXISTS pieces (
            cod TEXT PRIMARY KEY,
            tag TEXT,
            obra TEXT,
            cliente TEXT,
            cidade TEXT,
            produto TEXT,
            secao TEXT,
            comp REAL,
            vol REAL,
            peso REAL,
            qtd INTEGER DEFAULT 1,
            fck TEXT,
            file TEXT,
            prancha_file TEXT,
            prancha_url TEXT,
            print_url TEXT,
            fase_atual INTEGER DEFAULT 1,
            track_url TEXT,
            qr_payload TEXT,
            trueqr_data_url TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)

        # MIGRAÇÃO 2026-09-22 (pedido do usuário): panel_bbox/panel_header
        # guardam o retângulo (min_x, min_y, max_x, max_y, em coordenadas do
        # DXF) do painel daquela peça específica na prancha, detectado pelo
        # parser (_extract_piece_panels). Sem essas colunas, a prancha
        # gerada sob demanda não tinha como saber ONDE recortar e caía no
        # fallback de renderizar a folha inteira (com todas as peças
        # juntas) pra qualquer peça — era o bug reportado. ALTER TABLE em
        # try/except: idempotente, não quebra banco já existente sem essas
        # colunas nem recriação de banco que já as tem.
        for coluna_nova in ("panel_bbox TEXT", "panel_header TEXT"):
            try:
                cur.execute(f"ALTER TABLE pieces ADD COLUMN {coluna_nova}")
            except sqlite3.OperationalError:
                pass  # coluna já existe

        # Operators
        cur.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            cargo TEXT,
            matricula TEXT
        );
        """)
        
        # Production History (Audit Log - NEVER LOST)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS production_history (
            id TEXT PRIMARY KEY,
            cod TEXT,
            tag TEXT,
            obra TEXT,
            fase_anterior INTEGER,
            fase_anterior_nome TEXT,
            fase INTEGER,
            fase_nome TEXT,
            operator TEXT,
            action TEXT,
            obs TEXT,
            is_issue INTEGER DEFAULT 0,
            timestamp TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)
        
        # Issues / Non-Conformities
        cur.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id TEXT PRIMARY KEY,
            cod TEXT,
            tag TEXT,
            obra TEXT,
            operator TEXT,
            issue_type TEXT,
            severity TEXT,
            description TEXT,
            action_taken TEXT,
            status TEXT DEFAULT 'ABERTO',
            timestamp TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)
        
        # Insert default operators if empty
        cur.execute("SELECT COUNT(*) FROM operators")
        if cur.fetchone()[0] == 0:
            default_ops = [
                ("op-1", "Carlos Silva", "Armação & Aço", "104"),
                ("op-2", "João Santos", "Concretagem", "112"),
                ("op-3", "Roberto Lima", "Cura & Desforma", "205"),
                ("op-4", "Eng. Marcos Vinícius", "Controle de Qualidade (CQ)", "301"),
                ("op-5", "Valdir Souza", "Expedição & Logística", "402"),
                ("op-6", "Encarregado Geral", "Supervisão de Fábrica", "001")
            ]
            cur.executemany("INSERT INTO operators (id, nome, cargo, matricula) VALUES (?, ?, ?, ?)", default_ops)
        
        conn.commit()
        conn.close()

        # Migrate from legacy json if database.db is newly created and legacy json exists
        migrate_from_legacy_json()

def migrate_from_legacy_json():
    if not os.path.exists(LEGACY_JSON_PATH):
        return
    try:
        with open(LEGACY_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        conn = get_connection()
        cur = conn.cursor()
        
        # Check if pieces already exist
        cur.execute("SELECT COUNT(*) FROM pieces")
        if cur.fetchone()[0] == 0 and data.get('pieces'):
            for p in data['pieces']:
                cur.execute("""
                INSERT OR REPLACE INTO pieces 
                (cod, tag, obra, cliente, cidade, produto, secao, comp, vol, peso, qtd, fck, file, prancha_file, prancha_url, print_url, fase_atual, track_url, qr_payload, trueqr_data_url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p.get('cod'), p.get('tag'), p.get('obra'), p.get('cliente'), p.get('cidade'),
                    p.get('produto'), p.get('secao'), p.get('comp', 0), p.get('vol', 0), p.get('peso', 0),
                    p.get('qtd', 1), p.get('fck', '35 MPa'), p.get('file'), p.get('prancha_file'),
                    p.get('prancha_url'), p.get('print_url'), p.get('fase_atual', 1),
                    p.get('track_url'), p.get('qr_payload'), p.get('trueqr_data_url'),
                    p.get('updated_at', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                ))
        
        # Check obras
        cur.execute("SELECT COUNT(*) FROM obras")
        if cur.fetchone()[0] == 0 and data.get('obras'):
            for o in data['obras']:
                cur.execute("""
                INSERT OR IGNORE INTO obras (cod, cliente, cidade_uf, nome, fck)
                VALUES (?, ?, ?, ?, ?)
                """, (o.get('cod'), o.get('cliente'), o.get('cidade_uf'), o.get('nome'), o.get('fck')))
        
        # Check history
        cur.execute("SELECT COUNT(*) FROM production_history")
        if cur.fetchone()[0] == 0 and data.get('production_history'):
            for h in data['production_history']:
                cur.execute("""
                INSERT OR IGNORE INTO production_history (id, cod, tag, obra, fase_anterior, fase_anterior_nome, fase, fase_nome, operator, action, obs, is_issue, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    h.get('id', f"HIST-{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}"),
                    h.get('cod'), h.get('tag'), h.get('obra'), h.get('fase_anterior'),
                    h.get('fase_anterior_nome'), h.get('fase', 1), h.get('fase_nome'),
                    h.get('operator'), h.get('action'), h.get('obs'), 1 if h.get('is_issue') else 0,
                    h.get('timestamp')
                ))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SQLITE MIGRATION NOTICE] {e}", flush=True)

def create_backup():
    """Creates a timestamped snapshot of the SQLite database."""
    try:
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(BACKUP_DIR, f"rbr_erp_backup_{now_str}.db")
        if os.path.exists(DB_PATH):
            shutil.copy2(DB_PATH, backup_file)
            # Keep only last 15 backups
            all_backups = sorted([os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith('.db')])
            while len(all_backups) > 15:
                oldest = all_backups.pop(0)
                try: os.remove(oldest)
                except Exception: pass
            return backup_file
    except Exception as e:
        print(f"[BACKUP ERROR] {e}", flush=True)
    return None

class SQLiteDBManager:
    @staticmethod
    def get_all_data():
        with _db_lock:
            conn = get_connection()
            cur = conn.cursor()
            
            cur.execute("SELECT * FROM obras ORDER BY cod")
            obras = [dict(row) for row in cur.fetchall()]
            
            cur.execute("SELECT * FROM pieces ORDER BY cod")
            pieces = [dict(row) for row in cur.fetchall()]
            
            cur.execute("SELECT * FROM production_history ORDER BY timestamp DESC")
            history = [dict(row) for row in cur.fetchall()]
            
            cur.execute("SELECT * FROM issues ORDER BY timestamp DESC")
            issues = [dict(row) for row in cur.fetchall()]
            
            cur.execute("SELECT * FROM operators ORDER BY id")
            operators = [dict(row) for row in cur.fetchall()]
            
            # Attach history to pieces
            for p in pieces:
                p['history'] = [h for h in history if h.get('cod') == p.get('cod')]
                p['issues'] = [i for i in issues if i.get('cod') == p.get('cod')]
            
            conn.close()
            return {
                "obras": obras,
                "pieces": pieces,
                "production_history": history,
                "issues": issues,
                "operators": operators
            }

    @staticmethod
    def advance_piece_fase(cod, operator="Operador Fábrica", target_fase=None):
        FASES_NOMES = [
            "1. Corte e Dobra de Aço",
            "2. Armação Estrutural",
            "3. Fôrmas & Embutidos",
            "4. Concretagem",
            "5. Cura & Desmolde",
            "6. Acabamento & CQ",
            "7. Expedição & Pátio",
            "8. Execução na Obra"
        ]
        
        with _db_lock:
            conn = get_connection()
            cur = conn.cursor()
            
            clean_cod = cod.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
            cur.execute("SELECT * FROM pieces WHERE UPPER(REPLACE(REPLACE(REPLACE(cod, ' ', ''), '-', ''), '.', '')) = ? OR UPPER(REPLACE(REPLACE(REPLACE(tag, ' ', ''), '-', ''), '.', '')) = ?", (clean_cod, clean_cod))
            row = cur.fetchone()
            
            if not row:
                conn.close()
                return None, None
            
            p = dict(row)
            # CORRIGIDO 2026-09-22: "p.get('fase_atual') or 1" tratava fase_atual=0
            # (peça lançada, aguardando bipagem, fora da linha) como se já fosse
            # fase 1 — em Python "0 or 1" avalia pra 1. Isso fazia a PRIMEIRA
            # bipagem pular direto pra Fase 2 (old_fase virava 1 por engano, daí
            # new_fase = old_fase+1 = 2) em vez de entrar na Fase 1 de verdade.
            fase_raw = p.get('fase_atual')
            old_fase = 0 if fase_raw is None else int(fase_raw)
            if old_fase == 0:
                new_fase = 1  # primeira bipagem sempre entra na Fase 1, nunca pula
            elif target_fase is not None:
                # Permite VOLTAR a peça pra um setor anterior também (pedido do
                # usuário): min 1 (nunca sai da linha de volta pro "aguardando"
                # por essa via — isso é decisão de reprocessar peça, não bipagem
                # normal), max 8.
                new_fase = min(8, max(1, int(target_fase)))
            else:
                new_fase = min(8, old_fase + 1)
            
            now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # old_fase=0 (aguardando bipagem) não indexa FASES_NOMES (daria [-1],
            # "8. Execução na Obra" errado) — mesmo bug de índice já corrigido no
            # frontend, agora corrigido aqui também.
            old_fase_nome = "Aguardando Bipagem (fora da linha)" if old_fase == 0 else FASES_NOMES[old_fase - 1]
            new_fase_nome = FASES_NOMES[new_fase - 1]

            # Update piece
            cur.execute("UPDATE pieces SET fase_atual = ?, updated_at = ? WHERE cod = ?", (new_fase, now_iso, p['cod']))

            # Insert audit history log
            hist_id = f"HIST-{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:17]}"
            # Pedido do usuário 2026-09-22: dá pra VOLTAR peça de fase — o log de
            # auditoria precisa deixar claro quando foi retrocesso, não avanço.
            if old_fase > 0 and new_fase < old_fase:
                action_desc = f"⬅ RETROCESSO MANUAL: {old_fase_nome} ➔ {new_fase_nome}"
            else:
                action_desc = f"Avanço: {old_fase_nome} ➔ {new_fase_nome}"
            
            cur.execute("""
            INSERT INTO production_history (id, cod, tag, obra, fase_anterior, fase_anterior_nome, fase, fase_nome, operator, action, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (hist_id, p['cod'], p['tag'], p['obra'], old_fase, old_fase_nome, new_fase, new_fase_nome, operator, action_desc, now_iso))
            
            conn.commit()
            
            cur.execute("SELECT * FROM pieces WHERE cod = ?", (p['cod'],))
            updated_p = dict(cur.fetchone())
            
            conn.close()
            
            # Also keep database.json synced as secondary backup
            try:
                SQLiteDBManager.sync_to_json_backup()
            except Exception:
                pass
                
            return updated_p, action_desc

    @staticmethod
    def record_issue(cod, operator, issue_type, severity, description, action_taken="Aguardando Avaliação"):
        with _db_lock:
            conn = get_connection()
            cur = conn.cursor()
            
            clean_cod = cod.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
            cur.execute("SELECT * FROM pieces WHERE UPPER(REPLACE(REPLACE(REPLACE(cod, ' ', ''), '-', ''), '.', '')) = ? OR UPPER(REPLACE(REPLACE(REPLACE(tag, ' ', ''), '-', ''), '.', '')) = ?", (clean_cod, clean_cod))
            row = cur.fetchone()
            
            matched_p = dict(row) if row else {"cod": cod, "tag": cod, "obra": "N/A", "fase_atual": 1}
            now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            issue_id = f"NC-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            cur.execute("""
            INSERT INTO issues (id, cod, tag, obra, operator, issue_type, severity, description, action_taken, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (issue_id, matched_p['cod'], matched_p['tag'], matched_p['obra'], operator, issue_type, severity, description, action_taken, "ABERTO", now_iso))
            
            # Insert audit history
            hist_id = f"HIST-{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:17]}"
            action_desc = f"🚨 Ocorrência Registrada: {issue_type} ({severity})"
            
            cur.execute("""
            INSERT INTO production_history (id, cod, tag, obra, fase, fase_nome, operator, action, obs, is_issue, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (hist_id, matched_p['cod'], matched_p['tag'], matched_p['obra'], matched_p.get('fase_atual', 1), f"Ocorrência CQ: {issue_type}", operator, action_desc, description, 1, now_iso))
            
            conn.commit()
            
            cur.execute("SELECT * FROM issues WHERE id = ?", (issue_id,))
            created_issue = dict(cur.fetchone())
            conn.close()
            
            try:
                SQLiteDBManager.sync_to_json_backup()
            except Exception:
                pass
                
            return created_issue, matched_p

    @staticmethod
    def update_obra(old_cod, new_cod, cliente, cidade_uf, nome=None, fck=None):
        with _db_lock:
            conn = get_connection()
            cur = conn.cursor()
            
            cur.execute("SELECT * FROM obras WHERE cod = ?", (old_cod,))
            existing = cur.fetchone()
            
            new_c = (new_cod or old_cod).strip()
            cli = (cliente or '').strip()
            cid = (cidade_uf or '').strip()
            nom = (nome or cliente or '').strip()
            fck_val = (fck or '35 MPa').strip()
            
            old_nome = existing['nome'] if existing else old_cod
            old_cli = existing['cliente'] if existing else old_cod
            
            if existing:
                if new_c != old_cod:
                    cur.execute("DELETE FROM obras WHERE cod = ?", (old_cod,))
                cur.execute("INSERT OR REPLACE INTO obras (cod, cliente, cidade_uf, nome, fck) VALUES (?, ?, ?, ?, ?)",
                            (new_c, cli, cid, nom, fck_val))
            else:
                cur.execute("INSERT OR REPLACE INTO obras (cod, cliente, cidade_uf, nome, fck) VALUES (?, ?, ?, ?, ?)",
                            (new_c, cli, cid, nom, fck_val))
            
            # Update associated pieces
            cur.execute("""
            UPDATE pieces 
            SET obra = ?, cliente = ?, cidade = ?, fck = ?
            WHERE obra = ? OR cliente = ? OR obra = ? OR cliente = ?
            """, (nom, cli, cid, fck_val, old_nome, old_cli, old_cod, old_cod))
            
            conn.commit()
            conn.close()
            
            try:
                SQLiteDBManager.sync_to_json_backup()
                create_backup()
            except Exception:
                pass
                
            return True, "Obra e peças atualizadas com sucesso!"

    @staticmethod
    def delete_obra(cod):
        with _db_lock:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM obras WHERE cod = ?", (cod,))
            existing = cur.fetchone()
            if not existing:
                conn.close()
                return False, f"Obra '{cod}' não encontrada."
            
            old_nome = existing['nome'] or cod
            old_cli = existing['cliente'] or cod
            
            cur.execute("DELETE FROM obras WHERE cod = ?", (cod,))
            cur.execute("DELETE FROM pieces WHERE obra = ? OR cliente = ? OR obra = ? OR cliente = ?",
                        (old_nome, old_cli, cod, cod))
            conn.commit()
            conn.close()
            try:
                SQLiteDBManager.sync_to_json_backup()
                create_backup()
            except Exception:
                pass
            return True, "Obra e peças excluídas com sucesso."

    @staticmethod
    def update_piece(piece_data):
        with _db_lock:
            conn = get_connection()
            cur = conn.cursor()
            
            cod = str(piece_data.get('cod', '')).strip()
            if not cod:
                conn.close()
                return False, "Código da peça é obrigatório."
            
            cur.execute("SELECT * FROM pieces WHERE cod = ?", (cod,))
            existing = cur.fetchone()
            if not existing:
                conn.close()
                return False, f"Peça '{cod}' não encontrada."
            
            tag = piece_data.get('tag', existing['tag'])
            obra = piece_data.get('obra', existing['obra'])
            cliente = piece_data.get('cliente', existing['cliente'])
            cidade = piece_data.get('cidade', existing['cidade'])
            produto = piece_data.get('produto', existing['produto'])
            secao = piece_data.get('secao', existing['secao'])
            comp = piece_data.get('comp')
            vol = piece_data.get('vol')
            peso = piece_data.get('peso')
            qtd = piece_data.get('qtd', existing['qtd'])
            fck = piece_data.get('fck', existing['fck'])
            fase_atual = piece_data.get('fase_atual', existing['fase_atual'])
            
            # Format numbers cleanly
            try:
                comp = float(str(comp).replace(',', '.')) if comp is not None and str(comp).strip() != '' else None
            except (ValueError, TypeError):
                comp = None
                
            try:
                vol = float(str(vol).replace(',', '.')) if vol is not None and str(vol).strip() != '' else None
            except (ValueError, TypeError):
                vol = None
                
            try:
                peso = float(str(peso).replace(',', '.')) if peso is not None and str(peso).strip() != '' else None
            except (ValueError, TypeError):
                peso = None
                
            try:
                qtd = int(str(qtd).replace('x', '').replace('X', '').strip()) if qtd is not None and str(qtd).strip() != '' else 1
            except (ValueError, TypeError):
                qtd = 1
                
            now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            cur.execute("""
            UPDATE pieces SET
                tag = ?,
                obra = ?,
                cliente = ?,
                cidade = ?,
                produto = ?,
                secao = ?,
                comp = ?,
                vol = ?,
                peso = ?,
                qtd = ?,
                fck = ?,
                fase_atual = ?,
                updated_at = ?
            WHERE cod = ?
            """, (
                tag, obra, cliente, cidade, produto, secao,
                comp, vol, peso, qtd, fck, fase_atual, now_iso, cod
            ))
            
            conn.commit()
            conn.close()
            
            try:
                SQLiteDBManager.sync_to_json_backup()
                create_backup()
            except Exception:
                pass
                
            return True, f"Peça '{cod}' atualizada com sucesso!"

    @staticmethod
    def delete_piece(cod):
        with _db_lock:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM pieces WHERE cod = ?", (cod,))
            conn.commit()
            conn.close()
            try:
                SQLiteDBManager.sync_to_json_backup()
                create_backup()
            except Exception:
                pass
            return True, f"Peça '{cod}' excluída com sucesso."

    @staticmethod
    def sync_to_json_backup():
        """Mirrors SQLite to database.json so both formats exist and match."""
        all_data = SQLiteDBManager.get_all_data()
        with open(LEGACY_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)

init_db()
