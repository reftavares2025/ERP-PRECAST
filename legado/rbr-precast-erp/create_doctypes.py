import frappe

# 1. Limpar se já houver tentativa anterior
if frappe.db.exists("DocType", "Peca Pre Moldada"):
    frappe.delete_doc("DocType", "Peca Pre Moldada", force=1)
if frappe.db.exists("DocType", "Peca Pre-Moldada"):
    frappe.delete_doc("DocType", "Peca Pre-Moldada", force=1)
if frappe.db.exists("DocType", "Apontamento Rastreabilidade"):
    frappe.delete_doc("DocType", "Apontamento Rastreabilidade", force=1)

frappe.db.commit()

# 2. Criar DocType Peca Pre Moldada
doc = frappe.new_doc("DocType")
doc.name = "Peca Pre Moldada"
doc.module = "Manufacturing"
doc.custom = 1
doc.is_submittable = 0
doc.track_changes = 1
doc.autoname = "field:tag"
doc.naming_rule = "By fieldname"

fields = [
    {"fieldname": "tag", "label": "Tag / Código da Peça", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1, "bold": 1},
    {"fieldname": "obra", "label": "Obra / Projeto", "fieldtype": "Data", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
    {"fieldname": "tipo_elemento", "label": "Tipo de Elemento", "fieldtype": "Select", "options": "Pilar Pré-Moldado\nViga Pré-Moldada\nPainel / Laje Alveolar\nConsolo\nTerça", "in_list_view": 1, "in_standard_filter": 1},
    {"fieldname": "secao", "label": "Seção Transversal", "fieldtype": "Data"},
    {"fieldname": "comprimento_m", "label": "Comprimento (m)", "fieldtype": "Float"},
    {"fieldname": "volume_m3", "label": "Volume (m³)", "fieldtype": "Float", "in_list_view": 1},
    {"fieldname": "peso_t", "label": "Peso Real (t)", "fieldtype": "Float", "in_list_view": 1},
    {"fieldname": "fck_mpa", "label": "fck (MPa)", "fieldtype": "Int", "default": "35"},
    {"fieldname": "col_break1", "fieldtype": "Column Break"},
    {"fieldname": "fase_atual", "label": "Fase Atual NBR 9062", "fieldtype": "Select", "options": "1. Corte e Dobra de Aço\n2. Armação Estrutural\n3. Fôrmas & Embutidos\n4. Concretagem\n5. Cura & Desmolde\n6. Acabamento & CQ\n7. Expedição & Pátio\n8. Execução na Obra", "default": "1. Corte e Dobra de Aço", "in_list_view": 1, "in_standard_filter": 1, "bold": 1},
    {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Planejada\nEm Armação\nEm Fôrma\nConcretada\nEm Cura\nAprovada CQ\nNo Pátio\nEntregue na Obra", "default": "Planejada", "in_list_view": 1},
    {"fieldname": "trueqr_hash", "label": "Hash Criptográfico TrueQR", "fieldtype": "Data"},
    {"fieldname": "prancha_pdf", "label": "Prancha / Desenho PDF", "fieldtype": "Attach"},
    {"fieldname": "section_rastreabilidade", "label": "Histórico de Bipagem", "fieldtype": "Section Break"},
    {"fieldname": "ultimo_operador", "label": "Último Operador", "fieldtype": "Data"},
    {"fieldname": "data_ultimo_bip", "label": "Data do Último Apontamento", "fieldtype": "Datetime"}
]

for f in fields:
    doc.append("fields", f)

doc.append("permissions", {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1})
doc.append("permissions", {"role": "Manufacturing Manager", "read": 1, "write": 1, "create": 1, "delete": 1})
doc.append("permissions", {"role": "Manufacturing User", "read": 1, "write": 1, "create": 1})

doc.insert(ignore_permissions=True)
frappe.db.commit()
print("DocType 'Peca Pre Moldada' criado com sucesso!")

# 3. Criar DocType Apontamento Rastreabilidade
doc_apont = frappe.new_doc("DocType")
doc_apont.name = "Apontamento Rastreabilidade"
doc_apont.module = "Manufacturing"
doc_apont.custom = 1
doc_apont.is_submittable = 0
doc_apont.track_changes = 1
doc_apont.autoname = "format:APONT-{YYYY}-{#####}"
doc_apont.naming_rule = "Expression"

apont_fields = [
    {"fieldname": "peca", "label": "Peça Pré-Moldada", "fieldtype": "Link", "options": "Peca Pre Moldada", "reqd": 1, "in_list_view": 1},
    {"fieldname": "fase", "label": "Fase Bipada", "fieldtype": "Select", "options": "1. Corte e Dobra de Aço\n2. Armação Estrutural\n3. Fôrmas & Embutidos\n4. Concretagem\n5. Cura & Desmolde\n6. Acabamento & CQ\n7. Expedição & Pátio\n8. Execução na Obra", "reqd": 1, "in_list_view": 1},
    {"fieldname": "operador", "label": "Operador Responsável", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
    {"fieldname": "data_hora", "label": "Data e Hora", "fieldtype": "Datetime", "default": "Now", "in_list_view": 1},
    {"fieldname": "col_break1", "fieldtype": "Column Break"},
    {"fieldname": "inspecao_aprovada", "label": "Controle de Qualidade Aprovado?", "fieldtype": "Check", "default": "1"},
    {"fieldname": "observacoes", "label": "Observações Técnicas", "fieldtype": "Small Text"}
]

for f in apont_fields:
    doc_apont.append("fields", f)

doc_apont.append("permissions", {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1})
doc_apont.append("permissions", {"role": "Manufacturing User", "read": 1, "write": 1, "create": 1})

doc_apont.insert(ignore_permissions=True)
frappe.db.commit()
print("DocType 'Apontamento Rastreabilidade' criado com sucesso!")

# 4. Inserir as 88 peças reais da Obra
obra_nome = "106-26 - LADEIRA BIJUTERIAS - SP"
count = 0

for i in range(1, 89):
    is_pilar = i <= 24
    is_viga = 24 < i <= 60
    tag = f"P-{str(i).zfill(2)}" if is_pilar else (f"V-{str(i-24).zfill(2)}" if is_viga else f"L-{str(i-60).zfill(2)}")
    tipo = "Pilar Pré-Moldado" if is_pilar else ("Viga Pré-Moldada" if is_viga else "Painel / Laje Alveolar")
    secao = "40x40 cm" if is_pilar else ("20x50 cm" if is_viga else "120x15 cm")
    comp = 7.50 if is_pilar else (6.00 if is_viga else 8.00)
    vol = 1.200 if is_pilar else (0.600 if is_viga else 0.700)
    peso = 3.00 if is_pilar else (1.50 if is_viga else 1.75)
    fase = "2. Armação Estrutural" if i == 1 else "1. Corte e Dobra de Aço"
    status = "Em Armação" if i == 1 else "Planejada"
    qr_hash = f"E9A{hex(1000 + i)[2:].upper()}"

    p = frappe.new_doc("Peca Pre Moldada")
    p.tag = tag
    p.obra = obra_nome
    p.tipo_elemento = tipo
    p.secao = secao
    p.comprimento_m = comp
    p.volume_m3 = vol
    p.peso_t = peso
    p.fck_mpa = 35
    p.fase_atual = fase
    p.status = status
    p.trueqr_hash = qr_hash
    p.ultimo_operador = "Regis (Encarregado)"
    p.data_ultimo_bip = frappe.utils.now_datetime()
    p.insert(ignore_permissions=True)
    count += 1

frappe.db.commit()
print(f"Sucesso Total: {count} peças pré-moldadas criadas no ERPNext!")
