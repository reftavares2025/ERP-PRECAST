"""
RBR OpenPrecast ERP - Web Server & ERPNext API Bridge
Servidor local ultrarrápido para a Estação do Operador + Sincronizador ERPNext
"""

import os
import sys
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

BASE_DIR = r"C:\RBR_PRECAST_ERP"
sys.path.insert(0, os.path.join(BASE_DIR, "trueqr_engine"))
sys.path.insert(0, os.path.join(BASE_DIR, "cad_engine"))

try:
    from engine import TrueQREngine, TRACKING_STAGES
except ImportError:
    TrueQREngine = None
    TRACKING_STAGES = []

PORT = 5050
STATIC_DIR = os.path.join(BASE_DIR, "operator_station")

class PrecastHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        
        # API de Status do Sistema
        if parsed.path == "/api/status":
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            payload = {
                "status": "online",
                "erpnext_url": "http://localhost:8088",
                "stages": TRACKING_STAGES,
                "project": "106-26 - LADEIRA BIJUTERIAS",
                "total_pieces": 88,
                "volume_m3": 34.50,
                "weight_t": 86.30
            }
            self.wfile.write(json.dumps(payload).encode('utf-8'))
            return
            
        return super().do_GET()

def run_server():
    server = HTTPServer(('0.0.0.0', PORT), PrecastHandler)
    print(f"🚀 RBR OpenPrecast Operator Station rodando em: http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    run_server()
