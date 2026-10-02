import frappe

def create_print_format():
    """Cria o formato de impressão da Etiqueta Térmica NBR 9062 no ERPNext"""
    pf_name = "Etiqueta Termica NBR 9062"
    
    html_template = """
<div style="width: 100mm; min-height: 75mm; border: 3px solid #000; border-radius: 8px; padding: 10px; font-family: 'Segoe UI', Arial, sans-serif; box-sizing: border-box; background: #fff; color: #000;">
    <!-- Cabeçalho -->
    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #000; padding-bottom: 6px; margin-bottom: 8px;">
        <div>
            <div style="font-size: 14px; font-weight: 900; letter-spacing: -0.5px;">RBR OPENPRECAST • INDUSTRIAL</div>
            <div style="font-size: 10px; font-weight: bold; color: #444;">RASTREABILIDADE NBR 9062 • TrueQR™</div>
        </div>
        <div style="text-align: right;">
            <span style="border: 1.5px solid #000; padding: 2px 6px; font-weight: bold; font-size: 11px; border-radius: 4px;">fck: {{ doc.fck_mpa or 35 }} MPa</span>
        </div>
    </div>

    <!-- Identificação da Peça & QR Code -->
    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
        <div style="flex: 1;">
            <div style="font-size: 26px; font-weight: 900; line-height: 1.1; color: #000;">{{ doc.tag }}</div>
            <div style="font-size: 12px; font-weight: bold; color: #333; margin-top: 2px;">{{ doc.tipo_elemento }}</div>
            <div style="font-size: 10px; color: #555; margin-top: 2px;"><b>Obra:</b> {{ doc.obra }}</div>
            <div style="font-size: 11px; margin-top: 4px;">
                <b>Vol:</b> {{ doc.volume_m3 or 0.0 }} m³ &nbsp;|&nbsp; <b>Peso:</b> {{ doc.peso_t or 0.0 }} t &nbsp;|&nbsp; <b>Seção:</b> {{ doc.secao or '-' }}
            </div>
        </div>
        <div style="text-align: center; margin-left: 10px;">
            <img src="https://api.qrserver.com/v1/create-qr-code/?size=95x95&data=TRUEQR|{{ doc.tag }}|{{ doc.obra }}|{{ doc.volume_m3 }}|{{ doc.peso_t }}|{{ doc.trueqr_hash }}" style="width: 80px; height: 80px; border: 1px solid #ccc; padding: 2px;" />
            <div style="font-size: 8px; font-family: monospace; font-weight: bold; margin-top: 2px;">{{ doc.trueqr_hash or 'TRUEQR-HASH' }}</div>
        </div>
    </div>

    <!-- Matriz das 8 Fases de Produção NBR 9062 -->
    <div style="border-top: 2px solid #000; padding-top: 6px;">
        <div style="font-size: 10px; font-weight: 900; text-transform: uppercase; margin-bottom: 4px; text-align: center; letter-spacing: 0.5px;">
            CONTROLE DE ETAPAS DE PRODUÇÃO (NBR 9062)
        </div>
        
        <table style="width: 100%; font-size: 9.5px; border-collapse: collapse;">
            <tr>
                <td style="width: 50%; padding: 2px 0;">
                    <span style="display: inline-block; width: 12px; height: 12px; border: 1.5px solid #000; text-align: center; line-height: 11px; font-weight: bold; margin-right: 4px; font-size: 10px;">
                        {% if doc.fase_atual and '1' in doc.fase_atual %}X{% endif %}
                    </span> 1. Corte & Dobra de Aço
                </td>
                <td style="width: 50%; padding: 2px 0;">
                    <span style="display: inline-block; width: 12px; height: 12px; border: 1.5px solid #000; text-align: center; line-height: 11px; font-weight: bold; margin-right: 4px; font-size: 10px;">
                        {% if doc.fase_atual and ('5' in doc.fase_atual or '6' in doc.fase_atual or '7' in doc.fase_atual or '8' in doc.fase_atual) %}X{% endif %}
                    </span> 5. Cura & Desmolde
                </td>
            </tr>
            <tr>
                <td style="padding: 2px 0;">
                    <span style="display: inline-block; width: 12px; height: 12px; border: 1.5px solid #000; text-align: center; line-height: 11px; font-weight: bold; margin-right: 4px; font-size: 10px;">
                        {% if doc.fase_atual and ('2' in doc.fase_atual or '3' in doc.fase_atual or '4' in doc.fase_atual or '5' in doc.fase_atual or '6' in doc.fase_atual or '7' in doc.fase_atual or '8' in doc.fase_atual) %}X{% endif %}
                    </span> 2. Armação Estrutural
                </td>
                <td style="padding: 2px 0;">
                    <span style="display: inline-block; width: 12px; height: 12px; border: 1.5px solid #000; text-align: center; line-height: 11px; font-weight: bold; margin-right: 4px; font-size: 10px;">
                        {% if doc.fase_atual and ('6' in doc.fase_atual or '7' in doc.fase_atual or '8' in doc.fase_atual) %}X{% endif %}
                    </span> 6. Acabamento & CQ
                </td>
            </tr>
            <tr>
                <td style="padding: 2px 0;">
                    <span style="display: inline-block; width: 12px; height: 12px; border: 1.5px solid #000; text-align: center; line-height: 11px; font-weight: bold; margin-right: 4px; font-size: 10px;">
                        {% if doc.fase_atual and ('3' in doc.fase_atual or '4' in doc.fase_atual or '5' in doc.fase_atual or '6' in doc.fase_atual or '7' in doc.fase_atual or '8' in doc.fase_atual) %}X{% endif %}
                    </span> 3. Fôrmas & Embutidos
                </td>
                <td style="padding: 2px 0;">
                    <span style="display: inline-block; width: 12px; height: 12px; border: 1.5px solid #000; text-align: center; line-height: 11px; font-weight: bold; margin-right: 4px; font-size: 10px;">
                        {% if doc.fase_atual and ('7' in doc.fase_atual or '8' in doc.fase_atual) %}X{% endif %}
                    </span> 7. Expedição & Pátio
                </td>
            </tr>
            <tr>
                <td style="padding: 2px 0;">
                    <span style="display: inline-block; width: 12px; height: 12px; border: 1.5px solid #000; text-align: center; line-height: 11px; font-weight: bold; margin-right: 4px; font-size: 10px;">
                        {% if doc.fase_atual and ('4' in doc.fase_atual or '5' in doc.fase_atual or '6' in doc.fase_atual or '7' in doc.fase_atual or '8' in doc.fase_atual) %}X{% endif %}
                    </span> 4. Concretagem
                </td>
                <td style="padding: 2px 0;">
                    <span style="display: inline-block; width: 12px; height: 12px; border: 1.5px solid #000; text-align: center; line-height: 11px; font-weight: bold; margin-right: 4px; font-size: 10px;">
                        {% if doc.fase_atual and '8' in doc.fase_atual %}X{% endif %}
                    </span> 8. Execução na Obra
                </td>
            </tr>
        </table>
    </div>

    <!-- Rodapé -->
    <div style="border-top: 1px dashed #666; margin-top: 6px; padding-top: 4px; display: flex; justify-content: space-between; font-size: 8px; color: #666;">
        <span>Status Atual: <b>{{ doc.fase_atual }}</b></span>
        <span>Último Bip: {{ doc.ultimo_operador or 'Fábrica' }}</span>
    </div>
</div>
"""

    if frappe.db.exists("Print Format", pf_name):
        pf = frappe.get_doc("Print Format", pf_name)
        pf.html = html_template
        pf.doc_type = "Peca Pre Moldada"
        pf.custom_format = 1
        pf.print_format_type = "Jinja"
        pf.save(ignore_permissions=True)
        print("Print Format 'Etiqueta Termica NBR 9062' atualizado.")
    else:
        pf = frappe.new_doc("Print Format")
        pf.name = pf_name
        pf.doc_type = "Peca Pre Moldada"
        pf.module = "Manufacturing"
        pf.custom_format = 1
        pf.print_format_type = "Jinja"
        pf.html = html_template
        pf.standard = "No"
        pf.insert(ignore_permissions=True)
        print("✅ Print Format 'Etiqueta Termica NBR 9062' criado com sucesso!")

    frappe.db.commit()

if __name__ == "__main__":
    pass
