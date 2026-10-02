import frappe

def update_file_uploader_script():
    cs_name = "Importador DXF Auto Process"
    
    js_code = """
frappe.ui.form.on('Importador de Projeto DXF', {
    refresh: function(frm) {
        // Botão para abrir o seletor de arquivos do computador
        frm.add_custom_button(__('📁 Buscar Arquivo no Computador (Até 500MB)'), function() {
            new frappe.ui.FileUploader({
                doctype: frm.doctype,
                docname: frm.docname,
                allow_multiple: false,
                restrictions: {
                    allowed_file_types: ['.dxf', '.dwg', '.pdf', '*'],
                    max_number_of_files: 1
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
                            message: __('O arquivo <b>' + file_doc.file_name + '</b> foi carregado com sucesso.<br><br>Clique em <b>⚡ Processar DXF & Extrair Peças</b> para processar a prancha.'),
                            indicator: 'green'
                        });
                    });
                }
            });
        }).addClass('btn-primary');

        // Botão de Processamento quando há arquivo
        if ((frm.doc.arquivo_dxf || frm.doc.caminho_local_pc) && frm.doc.status !== 'Processado com Sucesso') {
            frm.add_custom_button(__('⚡ Processar DXF & Extrair Peças'), function() {
                frappe.show_alert({message: __('Processando pranchas CAD pesadas...'), indicator: 'orange'});
                frappe.call({
                    method: 'erpnext.cad_importer_engine.processar_arquivo_dxf',
                    args: { docname: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Extraindo geometria e calculando NBR 9062 no ERPNext...'),
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
    print("✅ Client Script atualizado para suporte a arquivos pesados até 500MB!")

if __name__ == "__main__":
    pass
