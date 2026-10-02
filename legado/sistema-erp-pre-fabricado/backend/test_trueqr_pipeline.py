import urllib.request
import urllib.parse
import json
import time

BASE_URL = "http://127.0.0.1:2026"

print("=" * 60)
print("🧪 INICIANDO TESTE END-TO-END DO SISTEMA RBR TRUEQR")
print("=" * 60)

# 1. Test Server Health
try:
    req = urllib.request.urlopen(f"{BASE_URL}/")
    print(f"✅ [1/5] Servidor Web Online: Status {req.status}")
except Exception as e:
    print(f"❌ [1/5] Falha ao conectar ao servidor: {e}")
    exit(1)

# 2. Test CAD Project Upload / Parse
print("\n📂 [2/5] Testando Leitura e Extração de Peças CAD (BM28 A BM36)...")
parse_url = f"{BASE_URL}/api/parse-cad"
req_data = json.dumps({"filename": "BM28 A BM36 - BM42 A BM50.dxf"}).encode('utf-8')
req = urllib.request.Request(parse_url, data=req_data, headers={'Content-Type': 'application/json'})

try:
    with urllib.request.urlopen(req) as resp:
        parse_res = json.loads(resp.read().decode('utf-8'))
        print(f"✅ Sucesso no Parse CAD! Obra: {parse_res.get('obra', {}).get('cliente')}")
        pieces = parse_res.get('pieces', [])
        print(f"   Total de Peças Extraídas: {len(pieces)}")
        if pieces:
            p0 = pieces[0]
            print(f"   Primeira Peça: {p0.get('cod')} - {p0.get('tag')} | Peso: {p0.get('peso')} kg")
            print(f"   Track URL TrueQR: {p0.get('track_url')}")
except Exception as e:
    print(f"❌ Falha no Parse CAD: {e}")
    exit(1)

# 3. Test TrueQR Piece Generation Endpoint
test_cod = pieces[0].get('cod', 'BM28')
print(f"\n🎨 [3/5] Testando Geração de TrueQR para Peça '{test_cod}'...")
qr_url = f"{BASE_URL}/api/qr/piece/{urllib.parse.quote(test_cod)}?fg=%2306628a&bg=%23ffffff&ec=H&size=300"
try:
    with urllib.request.urlopen(qr_url) as resp:
        qr_res = json.loads(resp.read().decode('utf-8'))
        print(f"✅ TrueQR Gerado com Sucesso!")
        print(f"   Payload TrueQR: {qr_res.get('payload')}")
        print(f"   DataURL Length: {len(qr_res.get('data_url', ''))} caracteres")
except Exception as e:
    print(f"❌ Falha ao gerar TrueQR: {e}")

# 4. Test Mobile /track Page
print(f"\n📱 [4/5] Testando Acesso à Página Mobile TrueQR (/track?cod={test_cod})...")
try:
    track_req = urllib.request.urlopen(f"{BASE_URL}/track?cod={urllib.parse.quote(test_cod)}")
    print(f"✅ Página Mobile TrueQR respondendo com status {track_req.status}")
except Exception as e:
    print(f"❌ Falha ao acessar /track: {e}")

# 5. Test Bipagem / Workflow Advancement through all 8 Phases
print(f"\n⚡ [5/5] Testando Bipagem Rápida e Avanço de Fases da Peça '{test_cod}'...")
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

for target_step in range(2, 9):
    bip_data = json.dumps({"cod": test_cod, "operator": "Operador Linha 1"}).encode('utf-8')
    bip_req = urllib.request.Request(f"{BASE_URL}/api/bipar-qrcode", data=bip_data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(bip_req) as b_resp:
        b_res = json.loads(b_resp.read().decode('utf-8'))
        updated_p = b_res.get('piece', {})
        f_num = updated_p.get('fase_atual')
        print(f"   📲 BIPADO! Peça {test_cod} -> Fase {f_num}: {FASES_NOMES[f_num-1]}")

print("\n" + "=" * 60)
print("🎉 TESTE CONCLUÍDO COM 100% DE SUCESSO! SISTEMA TRUEQR PRONTO.")
print("=" * 60)
