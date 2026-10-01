import os
import matplotlib.pyplot as plt
import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

dxf_path = r"D:\SISTEMA ERP PRÉ-FABRICADO\uploads_dwg\020 - 26 - ILHM INVESTIMENTO - PAULÍNIA - SP - REV-03 - DETALHAMENTO.dxf"
out_png = r"D:\erpnext-pre-fabricado\test_vm03_tight.png"
out_pdf = r"D:\erpnext-pre-fabricado\test_vm03_tight.pdf"

print("Reading DXF for tight VM-03 crop...")
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

fig, ax = plt.subplots(figsize=(10, 8), dpi=250)
fig.patch.set_facecolor('#ffffff')
ax.set_facecolor('#ffffff')
ax.set_aspect('equal')
ax.axis('off')

ctx = RenderContext(doc)
out = MatplotlibBackend(ax)
Frontend(ctx, out).draw_layout(msp, finalize=True)

# VM-03 tight bounding box: FOLHA 03
xmin, ymin, xmax, ymax = 162.0, -145.0, 195.0, -102.0
ax.set_xlim(xmin, xmax)
ax.set_ylim(ymin, ymax)

fig.savefig(out_png, format='png', dpi=250, bbox_inches='tight', pad_inches=0.05)
fig.savefig(out_pdf, format='pdf', bbox_inches='tight', pad_inches=0.05)
plt.close(fig)

print("Saved tight VM-03:")
print(" PNG:", out_png)
print(" PDF:", out_pdf)
