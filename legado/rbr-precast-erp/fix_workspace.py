import frappe

def fix_workspace():
    ws_list = frappe.db.get_list("Workspace", pluck="name")
    print("Workspaces existentes:", ws_list)
    
    ws_name = "Pré-Fabricados & NBR 9062" if "Pré-Fabricados & NBR 9062" in ws_list else ("Pre-Fabricados" if "Pre-Fabricados" in ws_list else None)
    
    if not ws_name:
        ws = frappe.new_doc("Workspace")
        ws.name = "Pré-Fabricados & NBR 9062"
        ws.title = "Pré-Fabricados & NBR 9062"
        ws.icon = "solid-cube"
        ws.indicator_color = "orange"
        ws.category = "Modules"
        ws.public = 1
        ws.module = "Manufacturing"
        ws.label = "Pré-Fabricados & NBR 9062"
        ws.insert(ignore_permissions=True)
        ws_name = ws.name
    
    ws = frappe.get_doc("Workspace", ws_name)
    ws.shortcuts = []
    
    ws.append("shortcuts", {
        "type": "DocType",
        "link_to": "Importador de Projeto DXF",
        "label": "⚡ Importar Projeto DXF (Auto CAD Parser)",
        "icon": "solid-file-code",
        "color": "Red"
    })
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
        "label": "Ordens de Produção",
        "icon": "solid-cogs",
        "color": "Green"
    })
    
    ws.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"✅ Workspace '{ws_name}' atualizado com todos os atalhos e o Importador DXF!")
