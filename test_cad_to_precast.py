import sys
import os
import json

sys.path.insert(0, r"D:\SISTEMA ERP PRÉ-FABRICADO\cad_engine")
sys.path.insert(0, r"D:\SISTEMA ERP PRÉ-FABRICADO\backend")

from dwg_parser import DynamicCADParser

test_file = r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg\BM28 A BM36 - BM42 A BM50.dxf"
print(f"Testing CAD parser with: {test_file}")

parser = DynamicCADParser(test_file)
res = parser.parse()

print("Status:", res.get("success"))
print("Obra Metadata:", json.dumps(res.get("obra"), indent=2, ensure_ascii=False))
pieces = res.get("pieces", [])
print(f"Total pieces detected: {len(pieces)}")
for p in pieces[:5]:
    print(f" - Código: {p.get('cod')} | Tag: {p.get('tag')} | Seção: {p.get('secao')} | Vol: {p.get('vol')} m³ | Peso: {p.get('peso')} kg | BBox: {p.get('panel_bbox')}")
