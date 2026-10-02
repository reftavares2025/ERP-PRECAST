"""
RBR OpenPrecast ERP - TrueQR & NBR 9062 Engine
Motor de Criptografia, Rastreabilidade e Etiquetas ZPL para Pré-Fabricados
"""

import hashlib
import json
import time
from datetime import datetime

# 8 Fases Oficiais de Rastreabilidade NBR 9062
TRACKING_STAGES = [
    {"id": 1, "key": "corte_dobra", "name": "1. Corte e Dobra de Aço", "short": "AÇO", "icon": "✂️"},
    {"id": 2, "key": "armacao", "name": "2. Armação Estrutural", "short": "ARM", "icon": "⛓️"},
    {"id": 3, "key": "formas_embutidos", "name": "3. Fôrmas & Embutidos", "short": "FRM", "icon": "📐"},
    {"id": 4, "key": "concretagem", "name": "4. Concretagem", "short": "CNC", "icon": "🏗️"},
    {"id": 5, "key": "cura_desmolde", "name": "5. Cura & Desmolde", "short": "CUR", "icon": "⏳"},
    {"id": 6, "key": "cq_acabamento", "name": "6. Acabamento & CQ", "short": "CQ", "icon": "🔬"},
    {"id": 7, "key": "expedicao_patio", "name": "7. Expedição & Pátio", "short": "PAT", "icon": "🚚"},
    {"id": 8, "key": "execucao_obra", "name": "8. Execução na Obra", "short": "OBR", "icon": "🏢"}
]

# Densidade Padrão do Concreto Armado segundo NBR 9062 / NBR 6118 (kg/m³)
DENSIDADE_CONCRETO_ARMADO = 2500.0  # 2.5 t/m³

class TrueQREngine:
    SECRET_SALT = "RBR_PRECAST_NBR9062_SECURE_SALT_2026"

    @classmethod
    def generate_payload(cls, piece_tag: str, project_id: str, volume_m3: float, weight_t: float, fck_mpa: int = 35) -> dict:
        """Gera payload criptografado com hash anti-adulteração"""
        timestamp = int(time.time())
        raw_string = f"{piece_tag}:{project_id}:{volume_m3:.3f}:{weight_t:.2f}:{fck_mpa}:{timestamp}:{cls.SECRET_SALT}"
        token_hash = hashlib.sha256(raw_string.encode('utf-8')).hexdigest()[:16].upper()

        return {
            "version": "TrueQR-v2.0",
            "tag": piece_tag,
            "project": project_id,
            "volume_m3": round(volume_m3, 3),
            "weight_t": round(weight_t, 2),
            "fck": fck_mpa,
            "ts": timestamp,
            "hash": token_hash,
            "standard": "NBR 9062:2017"
        }

    @classmethod
    def generate_qr_string(cls, payload: dict) -> str:
        """Compacta os dados para leitura ultrarrápida em leitores e câmeras"""
        return f"TRUEQR|{payload['tag']}|{payload['project']}|{payload['volume_m3']}|{payload['weight_t']}|{payload['fck']}|{payload['hash']}"

    @classmethod
    def parse_qr_string(cls, qr_string: str) -> dict:
        """Decodifica a string bipada pelo operador"""
        if qr_string.startswith("TRUEQR|"):
            parts = qr_string.split("|")
            if len(parts) >= 7:
                return {
                    "valid": True,
                    "tag": parts[1],
                    "project": parts[2],
                    "volume_m3": float(parts[3]),
                    "weight_t": float(parts[4]),
                    "fck": int(parts[5]),
                    "hash": parts[6]
                }
        # Tenta JSON caso seja payload expandido
        try:
            data = json.loads(qr_string)
            if "tag" in data and "project" in data:
                data["valid"] = True
                return data
        except Exception:
            pass

        return {"valid": False, "raw": qr_string}

    @classmethod
    def generate_zpl(cls, piece_data: dict, current_stage: int = 1) -> str:
        """
        Gera código ZPL (Zebra Programming Language) para impressão térmica
        com QR Code 2D e matriz de 8 checkboxes das fases NBR 9062.
        """
        tag = piece_data.get("tag", "PECA-01")
        project = piece_data.get("project", "OBRA-PADRAO")
        vol = piece_data.get("volume_m3", 0.0)
        weight = piece_data.get("weight_t", 0.0)
        fck = piece_data.get("fck", 35)
        qr_data = cls.generate_qr_string(cls.generate_payload(tag, project, vol, weight, fck))

        # Checkboxes das 8 Fases
        boxes_zpl = []
        for stage in TRACKING_STAGES:
            s_id = stage["id"]
            short = stage["short"]
            marked = "[X]" if s_id <= current_stage else "[ ]"
            y_offset = 280 + ((s_id - 1) % 4) * 45
            x_offset = 50 if s_id <= 4 else 450
            boxes_zpl.append(f"^FO{x_offset},{y_offset}^A0N,28,28^FD{marked} {stage['name']}^FS")

        stages_block = "\n".join(boxes_zpl)

        zpl = f"""
^XA
^PW800
^LL600
^PON
^FO30,30^GB740,540,4^FS

^FO60,50^A0N,38,38^FDRBR OPENPRECAST - RASTREABILIDADE NBR 9062^FS
^FO60,95^GB680,2,2^FS

^FO60,115^A0N,45,45^FDPECA: {tag}^FS
^FO60,165^A0N,28,28^FDOBRA: {project}^FS
^FO60,200^A0N,24,24^FDVOL: {vol:.3f} m3  |  PESO: {weight:.2f} t  |  fck: {fck} MPa^FS

^FO540,110^BQN,2,6^FDQA,{qr_data}^FS

^FO60,255^GB680,2,2^FS
{stages_block}

^FO60,490^GB680,2,2^FS
^FO60,510^A0N,20,20^FDHash: {qr_data.split('|')[-1]} | Emitido: {datetime.now().strftime('%d/%m/%Y %H:%M')}^FS
^XZ
"""
        return zpl.strip()
