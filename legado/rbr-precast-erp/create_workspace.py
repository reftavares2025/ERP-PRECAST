import frappe

def create_precast_workspace():
    ws_name = "Pre-Fabricados"
    
    if not frappe.db.exists("Workspace", ws_name):
        ws = frappe.new_doc("Workspace")
        ws.name = ws_name
        ws.title = "Pré-Fabricados & NBR 9062"
        ws.icon = "solid-cube"
        ws.indicator_color = "orange"
        ws.category = "Modules"
        ws.public = 1
        ws.module = "Manufacturing"
        ws.label = "Pré-Fabricados & NBR 9062"
        
        # Atalhos (Shortcuts)
        ws.append("shortcuts", {
            "type": "DocType",
            "link_to": "Peca Pre Moldada",
            "label": "Peças Pré-Moldadas (88)",
            "icon": "solid-layer-group",
            "color": "Orange"
        })
        ws.append("shortcuts", {
            "type": "DocType",
            "link_to": "Apontamento Rastreabilidade",
            "label": "Apontamentos de Rastreabilidade (Chão de Fábrica)",
            "icon": "solid-barcode",
            "color": "Blue"
        })
        ws.append("shortcuts", {
            "type": "DocType",
            "link_to": "Work Order",
            "label": "Ordens de Produção (ERPNext)",
            "icon": "solid-cogs",
            "color": "Green"
        })
        ws.append("shortcuts", {
            "type": "DocType",
            "link_to": "Item",
            "label": "Itens & Matérias-Primas (Aço/Cimento)",
            "icon": "solid-box",
            "color": "Purple"
        })
        
        # Links
        ws.append("links", {
            "label": "Gestão de Elementos Pré-Moldados",
            "type": "Card Break"
        })
        ws.append("links", {
            "label": "Todas as Peças Pré-Moldadas",
            "type": "Link",
            "link_type": "DocType",
            "link_to": "Peca Pre Moldada",
            "dependencies": ""
        })
        ws.append("links", {
            "label": "Histórico de Bipagem & Rastreabilidade",
            "type": "Link",
            "link_type": "DocType",
            "link_to": "Apontamento Rastreabilidade",
            "dependencies": ""
        })
        
        ws.insert(ignore_permissions=True)
        frappe.db.commit()
        print(f"✅ Workspace '{ws_name}' criado com sucesso no ERPNext!")
    else:
        print(f"Workspace '{ws_name}' já existe.")
