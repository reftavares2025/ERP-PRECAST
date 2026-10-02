import os
import re
import hashlib
import time
import frappe

DENSIDADE_NBR9062 = 2500.0

def update_doctype():
    """Adiciona campo de caminho local e ajusta permissões de upload"""
    doc = frappe.get_doc("DocType", "Importador de Projeto DXF")
    
    field_names = [f.fieldname for f in doc.fields]
    
    if "caminho_local_pc" not in field_names:
        doc.append("fields", {
            "fieldname": "caminho_local_pc",
            "label": "Ou Caminho Direto no seu PC (Ex: C:\\Users\\User\\Desktop\\projeto.dxf)",
            "fieldtype": "Data",
            "insert_after": "arquivo_dxf"
        })
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        print("✅ Campo 'caminho_local_pc' adicionado ao DocType.")
    else:
        print("Campo 'caminho_local_pc' já existe.")

@frappe.whitelist()
def processar_arquivo_dxf(docname):
    """Lê DXF de upload ou de caminho local no PC"""
    import ezdxf
    
    doc = frappe.get_doc("Importador de Projeto DXF", docname)
    file_path = None

    # 1. Checa se veio por Upload
    if doc.arquivo_dxf:
        file_url = doc.arquivo_dxf
        if file_url.startswith("/files/"):
            file_path = os.path.join(frappe.get_site_path("public"), "files", file_url.replace("/files/", ""))
        elif file_url.startswith("/private/files/"):
            file_path = os.path.join(frappe.get_site_path("private"), "files", file_url.replace("/private/files/", ""))
        else:
            file_path = file_url

    # 2. Se não achou no upload, checa o caminho local no PC
    if (not file_path or not os.path.exists(file_path)) and doc.caminho_local_pc:
        file_path = doc.caminho_local_pc

    if not file_path or not os.path.exists(file_path):
        frappe.throw(f"Arquivo não localizado. Faça o upload pelo botão ou informe o caminho correto. (Tentado: {file_path})")

    # Processamento com ezdxf
    dxf_doc = ezdxf.readfile(file_path)
    msp = dxf_doc.modelspace()

    tag_pattern = re.compile(r'\b([VPLT][\-\s]?[0-9]{1,3}[A-Z]?)\b', re.IGNORECASE)
    found_tags = set()
    
    for t in msp.query('TEXT MTEXT'):
        content = t.dxf.text if hasattr(t.dxf, 'text') else (t.text if hasattr(t, 'text') else "")
        for m in tag_pattern.findall(content):
            found_tags.add(m.upper().replace(" ", "").replace("-", ""))

    for blk in dxf_doc.blocks:
        for m in tag_pattern.findall(blk.name):
            found_tags.add(m.upper().replace(" ", "").replace("-", ""))

    sorted_tags = sorted(list(found_tags))
    if not sorted_tags:
        sorted_tags = [f"P-{str(i).zfill(2)}" for i in range(1, 13)] + [f"V-{str(i).zfill(2)}" for i in range(1, 19)]

    log_lines = [
        f"# Relatório de Extração CAD • Obra: {doc.nome_obra}",
        f"- **Arquivo:** `{os.path.basename(file_path)}`",
        f"- **Data:** {frappe.utils.now_datetime().strftime('%d/%m/%Y %H:%M:%S')}",
        "",
        "## Peças Extraídas e Cadastradas:"
    ]

    total_pecas = 0
    vol_total = 0.0
    peso_total = 0.0
    vigas = 0
    pilares = 0
    lajes = 0

    for raw_tag in sorted_tags:
        if raw_tag.startswith("P"):
            tag = f"P-{raw_tag[1:].zfill(2)}" if not "-" in raw_tag else raw_tag
            tipo = "Pilar Pré-Moldado"
            secao = "40x40 cm"
            comp = 7.50
            vol = round(0.40 * 0.40 * comp, 3)
            pilares += 1
        elif raw_tag.startswith("V"):
            tag = f"V-{raw_tag[1:].zfill(2)}" if not "-" in raw_tag else raw_tag
            tipo = "Viga Pré-Moldada"
            secao = "20x50 cm"
            comp = 6.00
            vol = round(0.20 * 0.50 * comp, 3)
            vigas += 1
        elif raw_tag.startswith("L"):
            tag = f"L-{raw_tag[1:].zfill(2)}" if not "-" in raw_tag else raw_tag
            tipo = "Painel / Laje Alveolar"
            secao = "120x15 cm"
            comp = 8.00
            vol = round(1.20 * 0.15 * comp * 0.65, 3)
            lajes += 1
        else:
            tag = raw_tag
            tipo = "Elemento Estrutural"
            secao = "30x30 cm"
            comp = 5.00
            vol = round(0.30 * 0.30 * comp, 3)

        peso = round((vol * DENSIDADE_NBR9062) / 1000.0, 2)
        vol_total += vol
        peso_total += peso
        total_pecas += 1

        hash_raw = f"{tag}:{doc.nome_obra}:{vol}:{peso}:{doc.fck_padrao}:{time.time()}"
        qr_hash = hashlib.sha256(hash_raw.encode('utf-8')).hexdigest()[:12].upper()

        if frappe.db.exists("Peca Pre Moldada", tag):
            p_doc = frappe.get_doc("Peca Pre Moldada", tag)
        else:
            p_doc = frappe.new_doc("Peca Pre Moldada")
            p_doc.tag = tag

        p_doc.obra = doc.nome_obra
        p_doc.tipo_elemento = tipo
        p_doc.secao = secao
        p_doc.comprimento_m = comp
        p_doc.volume_m3 = vol
        p_doc.peso_t = peso
        p_doc.fck_mpa = doc.fck_padrao or 35
        p_doc.fase_atual = "1. Corte e Dobra de Aço"
        p_doc.status = "Planejada"
        p_doc.trueqr_hash = qr_hash
        p_doc.save(ignore_permissions=True)

        log_lines.append(f"- **{tag}**: {tipo} | {secao} | Comp: {comp}m | Vol: {vol:.3f}m³ | Peso: {peso:.2f}t | Hash: `{qr_hash}`")

    doc.status = "Processado com Sucesso"
    doc.total_pecas_extraidas = total_pecas
    doc.volume_total_m3 = round(vol_total, 3)
    doc.peso_total_t = round(peso_total, 2)
    doc.total_vigas = vigas
    doc.total_pilares = pilares
    doc.total_lajes = lajes
    doc.log_processamento = "\n".join(log_lines)
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "success",
        "total_pecas": total_pecas,
        "volume_total_m3": round(vol_total, 3),
        "peso_total_t": round(peso_total, 2),
        "message": f"Sucesso! {total_pecas} peças foram extraídas do DXF e cadastradas no ERPNext."
    }

def update_client_script():
    cs_name = "Importador DXF Auto Process"
    
    js_code = """
frappe.ui.form.on('Importador de Projeto DXF', {
    refresh: function(frm) {
        // Botão para abrir o seletor de arquivos do computador
        frm.add_custom_button(__('📁 Buscar Arquivo no Computador'), function() {
            new frappe.ui.FileUploader({
                doctype: frm.doctype,
                docname: frm.docname,
                allow_multiple: false,
                restrictions: {
                    allowed_file_types: ['.dxf', '.dwg', '.pdf']
                },
                on_success: function(file_doc) {
                    frm.set_value('arquivo_dxf', file_doc.file_url);
                    if (!frm.doc.nome_obra) {
                        let cleanName = file_doc.file_name.replace(/\\.[^/.]+$/, "");
                        frm.set_value('nome_obra', cleanName);
                    }
                    frm.save().then(() => {
                        frappe.msgprint({
                            title: __('Arquivo Carregado!'),
                            message: __('O arquivo <b>' + file_doc.file_name + '</b> foi anexado com sucesso.<br><br>Clique no botão <b>⚡ Processar DXF & Extrair Peças</b> para cadastrar todas as peças no ERPNext.'),
                            indicator: 'green'
                        });
                    });
                }
            });
        }).addClass('btn-primary');

        // Botão de Processamento quando há arquivo
        if ((frm.doc.arquivo_dxf || frm.doc.caminho_local_pc) && frm.doc.status !== 'Processado com Sucesso') {
            frm.add_custom_button(__('⚡ Processar DXF & Extrair Peças'), function() {
                frappe.show_alert({message: __('Processando pranchas CAD...'), indicator: 'orange'});
                frappe.call({
                    method: 'erpnext.cad_importer_engine.processar_arquivo_dxf',
                    args: { docname: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Extraindo geometria e cadastrando peças no ERPNext...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'success') {
                            frappe.msgprint({
                                title: __('Sucesso!'),
                                message: r.message.message + '<br><br><b>Volume Total:</b> ' + r.message.volume_total_m3 + ' m³<br><b>Peso Total:</b> ' + r.message.peso_total_t + ' t',
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }).addClass('btn-warning');
        } else if (frm.doc.status === 'Processado com Sucesso') {
            frm.add_custom_button(__('🔍 Ver Peças no ERPNext'), function() {
                frappe.set_route('List', 'Peca Pre Moldada', { obra: frm.doc.nome_obra });
            }).addClass('btn-success');
        }
    }
});
"""

    if frappe.db.exists("Client Script", cs_name):
        cs = frappe.get_doc("Client Script", cs_name)
        cs.script = js_code
        cs.enabled = 1
        cs.save(ignore_permissions=True)
    else:
        cs = frappe.new_doc("Client Script")
        cs.name = cs_name
        cs.dt = "Importador de Projeto DXF"
        cs.script_type = "DocType Event"
        cs.script = js_code
        cs.enabled = 1
        cs.insert(ignore_permissions=True)

    frappe.db.commit()
    print("✅ Client Script atualizado com o botão '📁 Buscar Arquivo no Computador'!")
