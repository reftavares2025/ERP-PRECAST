"""
===============================================================================
RBR OpenPrecast ERP - AutoCAD Automation Engine (accoreconsole & AutoLISP)
===============================================================================
Executes headless AutoCAD accoreconsole to run RBR_EXTRAIR_PRANCHA.lsp
generating authentic isolated DWG (WBLOCK), PDF (DWG To PDF.pc3 monochrome),
and 200 DPI PNG prints for each launched piece.
"""

import os
import subprocess
import fitz

ACCORECONSOLE_PATH = r"C:\Program Files\Autodesk\AutoCAD 2022\accoreconsole.exe"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAD_ENGINE_DIR = os.path.join(BASE_DIR, "cad_engine")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads_dwg")
LSP_PATH = os.path.join(CAD_ENGINE_DIR, "RBR_EXTRAIR_PRANCHA.lsp")

def run_autocad_extraction(dwg_path, piece_cod, coords=None):
    """
    Executes AutoCAD accoreconsole with AutoLISP RBR_EXTRAIR_PRANCHA
    to plot authentic PDF and export WBLOCK DWG.
    """
    clean_cod = str(piece_cod).strip().upper()
    dwg_out = os.path.join(UPLOADS_DIR, f"{clean_cod}_PRANCHA.dwg")
    pdf_out = os.path.join(UPLOADS_DIR, f"prancha_{clean_cod}.pdf")
    png_out = os.path.join(UPLOADS_DIR, f"print_{clean_cod}.png")

    if not os.path.exists(dwg_path):
        return None, None, None

    if not os.path.exists(ACCORECONSOLE_PATH):
        print(f"[AUTOCAD ENGINE NOTICE] accoreconsole not found at {ACCORECONSOLE_PATH}")
        return None, None, None

    # Calculate bounding window (default modelspace extents or coords)
    x1, y1, x2, y2 = -100000.0, -100000.0, 100000.0, 100000.0
    if coords and len(coords) == 4:
        x1, y1, x2, y2 = coords

    # Create temporary script (.scr)
    scr_content = f"""(load "{LSP_PATH.replace(chr(92), '/')}")
(RBR_EXTRAIR_AUTO "{clean_cod}" {x1} {y1} {x2} {y2} "{dwg_out.replace(chr(92), '/')}" "{pdf_out.replace(chr(92), '/')}")
_QUIT
"""
    scr_path = os.path.join(UPLOADS_DIR, f"_extract_{clean_cod}.scr")
    with open(scr_path, 'w', encoding='utf-8') as f:
        f.write(scr_content)

    cmd = [
        ACCORECONSOLE_PATH,
        "/i", dwg_path,
        "/s", scr_path,
        "/l", "pt-BR"
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        print(f"[AUTOCAD AUTO-EXTRACT {clean_cod}] Return code: {proc.returncode}")
        
        # Clean up scr
        try: os.remove(scr_path)
        except: pass

        # Generate PNG print if PDF was produced
        if os.path.exists(pdf_out) and os.path.getsize(pdf_out) > 500:
            try:
                doc = fitz.open(pdf_out)
                if len(doc) > 0:
                    pix = doc[0].get_pixmap(dpi=200)
                    pix.save(png_out)
                doc.close()
            except Exception as e:
                print(f"[PNG RENDER ERROR] {e}")

        return dwg_out if os.path.exists(dwg_out) else None, pdf_out if os.path.exists(pdf_out) else None, png_out if os.path.exists(png_out) else None

    except Exception as e:
        print(f"[AUTOCAD ACCONTROLLER EXCEPTION] {e}")
        try: os.remove(scr_path)
        except: pass
        return None, None, None
