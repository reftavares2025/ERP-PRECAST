import frappe

def import_all():
    print("Iniciando inserção das 88 peças no ERPNext...")
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

        if not frappe.db.exists("Peca Pre Moldada", tag):
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
    print(f"✅ Sucesso Absoluto! {count} peças cadastradas com sucesso no ERPNext!")
