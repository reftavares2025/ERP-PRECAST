import ezdxf

def inspect_file(path, target_tags):
    print("=" * 60)
    print("Inspecting:", path)
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    print("Modelspace entity count:", len(msp))
    
    found = []
    for e in msp.query('TEXT MTEXT'):
        txt = e.dxf.text if e.dxftype() == 'TEXT' else e.plain_text()
        t_upper = txt.upper()
        for tag in target_tags:
            if tag in t_upper:
                pos = e.dxf.insert
                print(f"Found '{txt.strip()}' at ({pos.x:.2f}, {pos.y:.2f})")
                found.append((pos.x, pos.y, txt))
                break

    # Check layouts (paper space) as well
    for layout in doc.layouts:
        if layout.name != 'Model':
            vps = [e for e in layout if e.dxftype() == 'VIEWPORT']
            txts = [e for e in layout if e.dxftype() in ('TEXT', 'MTEXT')]
            print(f"Layout '{layout.name}': {len(vps)} viewports, {len(txts)} texts")
            for t in txts:
                t_str = t.dxf.text if t.dxftype() == 'TEXT' else t.plain_text()
                for tag in target_tags:
                    if tag in t_str.upper():
                        print(f"  In layout '{layout.name}': '{t_str.strip()}' at ({t.dxf.insert.x:.2f}, {t.dxf.insert.y:.2f})")

if __name__ == '__main__':
    inspect_file(r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg\BM28 A BM36 - BM42 A BM50.dxf", ["BM28", "TABELA", "BLOCO"])
    inspect_file(r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg\020 - 26 - ILHM INVESTIMENTO - PAULÍNIA - SP - REV-03 - DETALHAMENTO.dxf", ["VM-03", "VM03", "PM10", "PM.10", "PM 10"])
