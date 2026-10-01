import ezdxf

doc = ezdxf.readfile(r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg\020 - 26 - ILHM INVESTIMENTO - PAULÍNIA - SP - REV-03 - DETALHAMENTO.dxf")
msp = doc.modelspace()

# Center of VM-03 is (177.15, -122.71)
cx, cy = 177.15, -122.71
R = 50.0 # search within 50 units

entities_near = []
min_x, max_x = cx, cx
min_y, max_y = cy, cy

for e in msp:
    try:
        if e.dxftype() in ('LINE', 'LWPOLYLINE', 'TEXT', 'MTEXT', 'ARC', 'CIRCLE', 'DIMENSION'):
            # check if entity is close to (cx, cy)
            pos = None
            if e.dxftype() in ('TEXT', 'MTEXT'):
                pos = e.dxf.insert
            elif e.dxftype() == 'LINE':
                pos = e.dxf.start
            elif e.dxftype() == 'LWPOLYLINE':
                pts = list(e.get_points(format='xy'))
                if pts: pos = type('P', (), {'x': pts[0][0], 'y': pts[0][1]})()
            
            if pos and abs(pos.x - cx) < R and abs(pos.y - cy) < R:
                entities_near.append(e)
                min_x = min(min_x, pos.x)
                max_x = max(max_x, pos.x)
                min_y = min(min_y, pos.y)
                max_y = max(max_y, pos.y)
    except Exception:
        pass

print(f"VM-03: Found {len(entities_near)} entities near ({cx}, {cy})")
print(f"Calculated BBox around piece: ({min_x:.2f}, {min_y:.2f}, {max_x:.2f}, {max_y:.2f})")
print(f"Width: {max_x - min_x:.2f}, Height: {max_y - min_y:.2f}")

# Let's inspect some texts near VM-03
texts = [e.dxf.text if e.dxftype() == 'TEXT' else e.plain_text() for e in entities_near if e.dxftype() in ('TEXT', 'MTEXT')]
print("Texts near VM-03:", texts[:10])
