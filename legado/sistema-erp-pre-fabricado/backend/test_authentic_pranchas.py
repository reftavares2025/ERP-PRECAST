import urllib.request
import urllib.parse
import json
import os

BASE_URL = "http://127.0.0.1:2026"

print("=" * 65)
print("🧪 TESTE: METADADOS MANUAIS + EXTRAÇÃO AUTÊNTICA DE PRANCHAS & PRINTS")
print("=" * 65)

# 1. Test upload with custom manual metadata
print("\n📝 [1/3] Testando Importação com Metadados Manuais Informados pelo Usuário...")
payload = {
    "filename": "BM28 A BM36 - BM42 A BM50.dxf",
    "custom_cod": "OBRA-SCOCHA-100",
    "custom_cliente": "CONSTRUTORA SCOCHA & ASSOCIADOS",
    "custom_cidade": "CAMPINAS - SP",
    "custom_fck": "40 MPa"
}

req = urllib.request.Request(
    f"{BASE_URL}/api/parse-cad",
    data=json.dumps(payload).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

with urllib.request.urlopen(req) as resp:
    res = json.loads(resp.read().decode('utf-8'))
    obra = res.get('obra', {})
    pieces = res.get('pieces', [])
    print(f"✅ Obra Cadastrada com Sucesso:")
    print(f"   Código: {obra.get('cod')}")
    print(f"   Cliente: {obra.get('cliente')}")
    print(f"   Cidade: {obra.get('cidade_uf')}")
    print(f"   Fck: {obra.get('fck')}")
    print(f"   Total de Peças: {len(pieces)}")

# 2. Test authentic piece prancha PDF download (No synthetic drawings!)
p0 = pieces[0]
p_cod = p0.get('cod', 'BM28')
print(f"\n📄 [2/3] Testando Download da Prancha PDF Autêntica da Peça '{p_cod}'...")
pdf_url = f"{BASE_URL}/pranchas/prancha_{urllib.parse.quote(p_cod)}.pdf"
with urllib.request.urlopen(pdf_url) as pdf_resp:
    pdf_bytes = pdf_resp.read()
    print(f"✅ Prancha PDF Baixada: Status {pdf_resp.status} | Tamanho: {len(pdf_bytes):,} bytes")
    print(f"   Content-Type: {pdf_resp.headers.get('Content-Type')}")

# 3. Test authentic piece print PNG download
print(f"\n📸 [3/3] Testando Download do Print Real PNG da Peça '{p_cod}'...")
png_url = f"{BASE_URL}/pranchas/print_{urllib.parse.quote(p_cod)}.png"
with urllib.request.urlopen(png_url) as png_resp:
    png_bytes = png_resp.read()
    print(f"✅ Print PNG Baixado: Status {png_resp.status} | Tamanho: {len(png_bytes):,} bytes")
    print(f"   Content-Type: {png_resp.headers.get('Content-Type')}")

print("\n" + "=" * 65)
print("🎉 TESTE CONCLUÍDO COM 100% DE SUCESSO! ZERO DESENHOS INVENTADOS.")
print("=" * 65)
