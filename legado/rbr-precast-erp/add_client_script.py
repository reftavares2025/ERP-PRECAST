import frappe

def add_client_script():
    cs_name = "Importador DXF Auto Process"
    
    js_code = """
frappe.ui.form.on('Importador de Projeto DXF', {
    refresh: function(frm) {
        if (frm.doc.arquivo_dxf && frm.doc.status !== 'Processado com Sucesso') {
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
            }).addClass('btn-primary');
        } else if (frm.doc.status === 'Processado com Sucesso') {
            frm.add_custom_button(__('🔍 Ver Peças no ERPNext'), function() {
                frappe.set_route('List', 'Peca Pre Moldada', { obra: frm.doc.nome_obra });
            }).addClass('btn-success');
        }
    }
});
"""

    if not frappe.db.exists("Client Script", cs_name):
        cs = frappe.new_doc("Client Script")
        cs.name = cs_name
        cs.dt = "Importador de Projeto DXF"
        cs.script_type = "DocType Event"
        cs.script = js_code
        cs.enabled = 1
        cs.insert(ignore_permissions=True)
        print("✅ Client Script para botão do Importador DXF criado com sucesso!")
    else:
        cs = frappe.get_doc("Client Script", cs_name)
        cs.script = js_code
        cs.enabled = 1
        cs.save(ignore_permissions=True)
        print("Client Script atualizado.")

    # Adicionar o atalho no Workspace
    ws = frappe.get_doc("Workspace", "Pre-Fabricados")
    has_shortcut = any(s.label == "Importar Projeto DXF" for s in ws.shortcuts)
    if not has_shortcut:
        ws.append("shortcuts", {
            "type": "DocType",
            "link_to": "Importador de Projeto DXF",
            "label": "Importar Projeto DXF (Auto CAD Parser)",
            "icon": "solid-file-code",
            "color": "Red"
        })
        ws.save(ignore_permissions=True)
        print("✅ Atalho adicionado ao Workspace 'Pré-Fabricados'!")

    frappe.db.commit()
