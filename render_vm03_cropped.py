import os
import sys
import matplotlib.pyplot as plt
import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

dxf_path = r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg\020 - 26 - ILHM INVESTIMENTO - PAULÍNIA - SP - REV-03 - DETALHAMENTO.dxf"
out_png = r"D:\erpnext-pre-fabricado\test_vm03_isolated.png"
out_pdf = r"D:\erpnext-pre-fabricado\test_vm03_isolated.pdf"

print("Reading DXF for VM-03 crop...")
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

fig, ax = plt.subplots(figsize=(14, 10), dpi=200)
fig.patch.set_facecolor('#ffffff')
ax.set_facecolor('#ffffff')
ax.set_aspect('equal')
ax.axis('off')

ctx = RenderContext(doc)
out = MatplotlibBackend(ax)
Frontend(ctx, out).draw_layout(msp, finalize=True)

# VM-03 bounding box: (127.58, -172.16, 226.93, -73.41)
xmin, ymin, xmax, ymax = 125.0, -175.0, 230.0, -70.0
ax.set_xlim(xmin, xmax)
ax.set_ylim(ymin, ymax)

fig.savefig(out_png, format='png', dpi=200, bbox_inches='tight', pad_inches=0.1)
fig.savefig(out_pdf, format='pdf', bbox_inches='tight', pad_inches=0.1)
plt.close(fig)

print("Saved isolated VM-03:")
print(" PNG:", out_png, f"({os.path.getsize(out_png):,} bytes)")
print(" PDF:", out_pdf, f"({os.path.getsize(out_pdf):,} bytes)")
