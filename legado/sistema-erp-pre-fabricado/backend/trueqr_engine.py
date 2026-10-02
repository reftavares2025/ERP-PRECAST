import io
import os
import base64
import qrcode
from qrcode.image.svg import SvgPathImage
from PIL import Image, ImageDraw, ImageFont

class TrueQREngine:
    """
    TrueQR Integration Engine for RBR OpenPrecast ERP.
    Implements TrueQR format builders, custom color palettes, error correction,
    and industrial tracking payloads.
    """

    DEFAULT_OPTIONS = {
        'foreground': '#06628a', # RBR Navy Blue
        'background': '#ffffff',
        'errorCorrection': 'H',  # High error correction for industrial factory floor
        'size': 350,
        'margin': 2,
        'box_size': 10
    }

    CORRECTION_MAP = {
        'L': qrcode.constants.ERROR_CORRECT_L,
        'M': qrcode.constants.ERROR_CORRECT_M,
        'Q': qrcode.constants.ERROR_CORRECT_Q,
        'H': qrcode.constants.ERROR_CORRECT_H,
    }

    @classmethod
    def build_piece_payload(cls, piece, base_url="http://localhost:2026", mode="url"):
        """
        Builds payload for precast element tracking.
        - mode='url': standard web URL for smartphone camera scanning.
        - mode='industrial': compact text format for industrial 2D barcode gun.
        """
        cod = str(piece.get('cod', '')).strip()
        tag = str(piece.get('tag', '')).strip()
        obra = str(piece.get('obra', '') or piece.get('cliente', '')).strip()
        peso = str(piece.get('peso', '')).strip()
        
        if mode == "url":
            return f"{base_url.rstrip('/')}/track?cod={cod}"
        else:
            return f"RBR_PCP:{cod}|TAG:{tag}|OBRA:{obra[:20]}|PESO:{peso}KG"

    @classmethod
    def generate_data_url(cls, content, options=None):
        """
        Generates a PNG DataURL string formatted according to TrueQR options.
        """
        opts = {**cls.DEFAULT_OPTIONS, **(options or {})}
        err_level = cls.CORRECTION_MAP.get(opts.get('errorCorrection', 'H').upper(), qrcode.constants.ERROR_CORRECT_H)
        
        qr = qrcode.QRCode(
            version=None,
            error_correction=err_level,
            box_size=opts.get('box_size', 10),
            border=opts.get('margin', 2),
        )
        qr.add_data(content)
        qr.make(fit=True)

        fg_color = opts.get('foreground', '#06628a')
        bg_color = opts.get('background', '#ffffff')

        img = qr.make_image(fill_color=fg_color, back_color=bg_color).convert('RGBA')
        
        # Resize if explicit size is requested
        target_size = opts.get('size', 350)
        if target_size and (img.width != target_size or img.height != target_size):
            img = img.resize((target_size, target_size), Image.Resampling.NEAREST)

        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return f"data:image/png;base64,{encoded}"

    @classmethod
    def generate_svg(cls, content, options=None):
        """
        Generates a crisp SVG string for high-res vector rendering.
        """
        opts = {**cls.DEFAULT_OPTIONS, **(options or {})}
        err_level = cls.CORRECTION_MAP.get(opts.get('errorCorrection', 'H').upper(), qrcode.constants.ERROR_CORRECT_H)
        
        qr = qrcode.QRCode(
            version=None,
            error_correction=err_level,
            box_size=opts.get('box_size', 10),
            border=opts.get('margin', 2),
            image_factory=SvgPathImage
        )
        qr.add_data(content)
        qr.make(fit=True)

        svg_img = qr.make_image()
        buffer = io.BytesIO()
        svg_img.save(buffer)
        return buffer.getvalue().decode('utf-8')

    @classmethod
    def generate_piece_label_card(cls, piece, base_url="http://localhost:2026", output_path=None):
        """
        Generates a complete production tracking label card (PNG) with TrueQR Code,
        RBR branding, piece dimensions, and phase checklist.
        """
        cod = str(piece.get('cod', 'PEC-001'))
        tag = str(piece.get('tag', f"PEÇA {cod}"))
        obra = str(piece.get('obra') or piece.get('cliente') or 'RBR ENGENHARIA')
        produto = str(piece.get('produto', 'ELEMENTO PRÉ-FABRICADO'))
        secao = str(piece.get('secao', '50X60'))
        comp = str(piece.get('comp', '0'))
        vol = str(piece.get('vol', '0'))
        peso = str(piece.get('peso', '0'))
        fck = str(piece.get('fck', '35 MPa'))
        fase_atual = int(piece.get('fase_atual', 1))

        fases_nomes = [
            "1. CORTE E DOBRA",
            "2. ARMAÇÃO",
            "3. FORMAS / EMBUTIDOS",
            "4. CONCRETAGEM",
            "5. CURA / DESMOLDE",
            "6. ACABAMENTO & CQ",
            "7. EXPEDIÇÃO",
            "8. EXECUÇÃO NA OBRA"
        ]

        # Generate TrueQR Code
        qr_content = cls.build_piece_payload(piece, base_url=base_url, mode="url")
        qr_data_url = cls.generate_data_url(qr_content, {
            'foreground': '#044866',
            'background': '#ffffff',
            'errorCorrection': 'H',
            'size': 240,
            'margin': 1
        })
        
        # Decode base64 image
        header, b64_str = qr_data_url.split(',', 1)
        qr_bytes = base64.b64decode(b64_str)
        qr_pil = Image.open(io.BytesIO(qr_bytes)).convert('RGBA')

        # Card Canvas (800x480)
        img_w, img_h = 800, 480
        card = Image.new("RGB", (img_w, img_h), "#ffffff")
        draw = ImageDraw.Draw(card)

        # Border
        draw.rectangle([8, 8, img_w - 8, img_h - 8], outline="#06628a", width=4)
        
        # Header Box
        draw.rectangle([12, 12, img_w - 12, 65], fill="#06628a")
        draw.text((25, 20), "RBR PRÉ-FABRICADOS DE CONCRETO", fill="#ffffff")
        draw.text((25, 42), "SISTEMA DE RASTREABILIDADE TOTAL • TRUEQR ENGINE", fill="#f19725")
        draw.text((580, 26), f"PCP: {cod}", fill="#ffffff")

        # Piece Info
        draw.text((25, 80), f"OBRA: {obra[:45]}", fill="#1e293b")
        draw.text((25, 110), f"PEÇA: {tag}", fill="#b91c1c")
        draw.text((450, 110), f"PRODUTO: {produto[:25]}", fill="#06628a")

        draw.line([(25, 140), (520, 140)], fill="#cbd5e1", width=2)

        draw.text((25, 155), f"SEÇÃO: {secao}", fill="#1e293b")
        draw.text((250, 155), f"COMPRIMENTO: {comp} m", fill="#1e293b")
        draw.text((25, 185), f"VOLUME: {vol} m³", fill="#1e293b")
        draw.text((250, 185), f"PESO REAL: {peso} kg", fill="#15803d")
        draw.text((25, 215), f"TRAÇO / Fck: {fck}", fill="#1e293b")
        draw.text((250, 215), f"COBRIMENTO: 25 mm (CA-50)", fill="#1e293b")

        # Checklist Phases
        draw.rectangle([25, 255, 520, 430], outline="#cbd5e1", fill="#f8fafc", width=1)
        draw.text((35, 265), "FASES DE PRODUÇÃO (BIPAGEM TRUEQR):", fill="#06628a")

        y_offset = 295
        col1_x = 35
        col2_x = 280
        for i, fname in enumerate(fases_nomes):
            is_done = (i + 1) <= fase_atual
            mark = "[X]" if is_done else "[ ]"
            color = "#15803d" if is_done else "#64748b"
            curr_x = col1_x if i < 4 else col2_x
            curr_y = y_offset + ((i % 4) * 30)
            draw.text((curr_x, curr_y), f"{mark} {fname}", fill=color)

        # Paste TrueQR
        card.paste(qr_pil, (540, 145), qr_pil)
        draw.text((550, 395), "ESCANEIE PARA BIPAR", fill="#06628a")
        draw.text((550, 415), f"URL: /track?cod={cod}", fill="#64748b")

        # Footer
        draw.line([(25, 445), (img_w - 25, 445)], fill="#06628a", width=2)
        draw.text((25, 455), "ABNT NBR 9062 • RASTREABILIDADE INDUSTRIAL INTEGRADA TRUEQR", fill="#64748b")

        if output_path:
            card.save(output_path)
            return output_path

        buf = io.BytesIO()
        card.save(buf, format='PNG')
        encoded = base64.b64encode(buf.getvalue()).decode('utf-8')
        return f"data:image/png;base64,{encoded}"
