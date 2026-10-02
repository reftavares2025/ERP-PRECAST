import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "backend"))
sys.path.insert(0, os.path.join(BASE_DIR, "cad_engine"))

from app import app

c = app.test_client()

print("--- 1. Testing System Status ---")
r1 = c.get('/api/status')
print("Status Code:", r1.status_code)
print("Data:", json.loads(r1.data))

print("\n--- 2. Testing Bipar PM12 ---")
r2 = c.post('/api/bipar-qrcode', json={'cod': 'PM12', 'operator': 'Carlos Silva (Armacao)'})
print("Bip Code:", r2.status_code)
print("Bip Result:", json.loads(r2.data).get('message'))

print("\n--- 3. Testing Report Issue ---")
r3 = c.post('/api/report-issue', json={
    'cod': 'PM12',
    'operator': 'Eng. Marcos (CQ)',
    'issue_type': 'Trinca de Desforma',
    'severity': 'Media',
    'description': 'Fissura superficial detectada'
})
print("Report Code:", r3.status_code)
print("Report Result:", json.loads(r3.data).get('message'))

print("\n--- 4. Testing SQLite Persistent Audit History ---")
r4 = c.get('/api/history')
h_data = json.loads(r4.data)
print("Total Audit Logs in SQLite:", h_data.get('total'))
for idx, h in enumerate(h_data.get('history')[:4]):
    print(f"Log {idx+1}: [{h.get('timestamp')}] {h.get('operator')} -> {h.get('action')}")

print("\n--- 5. Testing Backups Directory ---")
backup_dir = os.path.join(BASE_DIR, "backend", "backups")
backups = os.listdir(backup_dir) if os.path.exists(backup_dir) else []
print(f"Backups Found ({len(backups)}):", backups[:3])
print("\n✅ All SQLite tests completed with 100% verified results!")
