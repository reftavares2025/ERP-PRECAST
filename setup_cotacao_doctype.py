import frappe


def run():
    if not frappe.db.exists('DocType', 'Cotacao Insumo'):
        frappe.get_doc({
            "doctype": "DocType", "name": "Cotacao Insumo", "module": "Custom", "custom": 1,
            "naming_rule": "Autoincrement",
            "sort_field": "data", "sort_order": "DESC",
            "fields": [
                {"fieldname": "data", "label": "Data", "fieldtype": "Date", "reqd": 1, "in_list_view": 1},
                {"fieldname": "insumo", "label": "Insumo", "fieldtype": "Select", "reqd": 1, "in_list_view": 1,
                 "options": "Dólar (USD)\nAço CA-50\nAço CA-60\nCimento CP-II\nCimento CP-V\nAreia\nBrita/Pedra\nCordoalha\nTerra\nOutro"},
                {"fieldname": "insumo_outro", "label": "Nome do Insumo (se Outro)", "fieldtype": "Data"},
                {"fieldname": "valor", "label": "Valor", "fieldtype": "Float", "reqd": 1, "in_list_view": 1, "precision": "4"},
                {"fieldname": "unidade", "label": "Unidade", "fieldtype": "Select", "in_list_view": 1,
                 "options": "USD\nkg\nsaca 50kg\nton\nm³\nunidade"},
                {"fieldname": "fonte", "label": "Fonte", "fieldtype": "Select", "options": "Manual\nAutomático",
                 "default": "Manual", "in_list_view": 1},
                {"fieldname": "observacao", "label": "Observação", "fieldtype": "Small Text"},
                {"fieldname": "lancado_por", "label": "Lançado por", "fieldtype": "Data", "read_only": 1},
            ],
            "permissions": [
                {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            ]
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        print("DocType 'Cotacao Insumo' criado.")
    else:
        print("DocType já existia.")
