import frappe


def _ensure_doctype(name, fields, naming_rule="Autoincrement", permissions=None):
    if frappe.db.exists("DocType", name):
        print(f"DocType '{name}' ja existia.")
        return
    frappe.get_doc({
        "doctype": "DocType", "name": name, "module": "Custom", "custom": 1,
        "naming_rule": naming_rule,
        "fields": fields,
        "permissions": permissions or [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
    }).insert(ignore_permissions=True)
    print(f"DocType '{name}' criado.")


def _ensure_field(doctype, fieldname, field_def):
    dt = frappe.get_doc("DocType", doctype)
    existentes = {f.fieldname for f in dt.fields}
    if fieldname in existentes:
        print(f"Campo '{fieldname}' ja existe em {doctype}.")
        return
    dt.append("fields", field_def)
    dt.save(ignore_permissions=True)
    frappe.clear_cache(doctype=doctype)
    print(f"Campo '{fieldname}' adicionado em {doctype}.")


def run():
    # Melhoria 9: historico de fase por peca - auditoria + base do OEE de pista
    _ensure_doctype("Fase Historico", [
        {"fieldname": "codigo_peca", "label": "Peça", "fieldtype": "Data", "in_list_view": 1, "reqd": 1},
        {"fieldname": "forma_pista", "label": "Forma/Pista", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "fase_anterior", "label": "Fase Anterior", "fieldtype": "Int"},
        {"fieldname": "fase_nova", "label": "Fase Nova", "fieldtype": "Int", "in_list_view": 1},
        {"fieldname": "data_hora", "label": "Data/Hora", "fieldtype": "Datetime", "in_list_view": 1},
        {"fieldname": "usuario", "label": "Usuário", "fieldtype": "Data"},
    ])

    # Melhoria 7: nao-conformidade com laudo fotografico, bloqueia expedicao
    _ensure_doctype("Nao Conformidade", [
        {"fieldname": "codigo_peca", "label": "Peça", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "descricao", "label": "Descrição do Defeito", "fieldtype": "Small Text", "reqd": 1},
        {"fieldname": "foto", "label": "Foto/Laudo Fotográfico", "fieldtype": "Attach Image"},
        {"fieldname": "status", "label": "Status", "fieldtype": "Select",
         "options": "Aberta\nEm Reparo\nAprovada", "default": "Aberta", "in_list_view": 1},
        {"fieldname": "receita_reparo", "label": "Receita de Reparo (Engenharia)", "fieldtype": "Small Text"},
        {"fieldname": "aberto_por", "label": "Aberto por", "fieldtype": "Data"},
        {"fieldname": "data_abertura", "label": "Data de Abertura", "fieldtype": "Datetime", "in_list_view": 1},
        {"fieldname": "data_aprovacao", "label": "Data de Aprovação", "fieldtype": "Datetime"},
    ])

    # Melhoria 8: ciclo de vida de formas/pistas (giros de concretagem)
    _ensure_doctype("Forma Pista", [
        {"fieldname": "codigo", "label": "Código da Forma/Pista", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1},
        {"fieldname": "tipo", "label": "Tipo de Forma", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Livre\nEm Uso\nManutenção", "default": "Livre", "in_list_view": 1},
        {"fieldname": "giros_realizados", "label": "Giros Realizados", "fieldtype": "Int", "default": 0, "in_list_view": 1},
        {"fieldname": "giros_limite_manutencao", "label": "Giros até Manutenção Preventiva", "fieldtype": "Int", "default": 50},
    ], naming_rule="By fieldname")
    _ensure_field("Forma Pista", "giros_realizados", {
        "fieldname": "giros_realizados", "label": "Giros Realizados", "fieldtype": "Int", "default": 0, "in_list_view": 1,
    })
    _ensure_field("Forma Pista", "giros_limite_manutencao", {
        "fieldname": "giros_limite_manutencao", "label": "Giros até Manutenção Preventiva", "fieldtype": "Int", "default": 50,
    })

    # Melhoria 4: marca a peca como ja faturada por montagem (nao duplicar fatura)
    _ensure_field("Peca Pre-Moldada", "faturado_montagem", {
        "fieldname": "faturado_montagem", "label": "Faturado (Montagem)", "fieldtype": "Check", "default": 0,
    })

    # Melhoria 19: canhoto eletronico de entrega (assinatura na tela)
    _ensure_field("Romaneio", "assinatura_recebedor", {
        "fieldname": "assinatura_recebedor", "label": "Assinatura do Recebedor", "fieldtype": "Attach Image",
    })
    _ensure_field("Romaneio", "recebedor_nome", {
        "fieldname": "recebedor_nome", "label": "Nome de Quem Recebeu", "fieldtype": "Data",
    })
    _ensure_field("Romaneio", "data_entrega", {
        "fieldname": "data_entrega", "label": "Data/Hora da Entrega", "fieldtype": "Datetime",
    })

    # Amplia opcoes de status do Romaneio pra incluir "Entregue"
    dt = frappe.get_doc("DocType", "Romaneio")
    for f in dt.fields:
        if f.fieldname == "status":
            opcoes = set((f.options or "").split("\n"))
            opcoes.update({"Montando", "Despachado", "Entregue"})
            f.options = "\n".join(sorted(opcoes, key=lambda x: {"Montando": 0, "Despachado": 1, "Entregue": 2}.get(x, 9)))
    dt.save(ignore_permissions=True)
    frappe.clear_cache(doctype="Romaneio")

    frappe.db.commit()
    print("Migracao das 20 melhorias (doctypes/campos) concluida.")
