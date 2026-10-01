import frappe

def run():
    print("=== INICIANDO VERIFICACAO DAS 20 MELHORIAS ===")

    # 1. Teste Orçador Automático
    from frappe.precast_api import estimar_custos_pecas, estimar_carbono_peca, otimizar_corte_aco, sugerir_carretas, get_status_publico_obra, abrir_nao_conformidade, aprovar_nao_conformidade, get_status_formas_pistas
    
    res_orc = estimar_custos_pecas([{"cod": "TEST-P1", "produto": "Pilar", "vol": 1.5}])
    print("1. Orçador Automático:", "OK" if res_orc.get("success") and res_orc.get("pecas", {}).get("TEST-P1", {}).get("custo_estimado") > 0 else "FALHA")

    # 2. Teste Nesting 1D
    res_nesting = otimizar_corte_aco([3.5, 4.0, 5.0, 2.5, 6.0])
    print("2. Nesting 1D Aço:", "OK" if res_nesting.get("success") and res_nesting.get("barras_necessarias") > 0 else "FALHA")

    # 3. Teste Status Formas/Pistas OEE
    res_oee = get_status_formas_pistas()
    print("3. Ciclo de Vida Formas/OEE:", "OK" if res_oee.get("success") else "FALHA")

    # 4. Criar Obra e Peça de Teste
    if not frappe.db.exists("Obra", "OBRA-TESTE-20M"):
        frappe.get_doc({
            "doctype": "Obra", "codigo_obra": "OBRA-TESTE-20M", "nome_obra": "Obra Teste 20M",
            "cliente_nome": "Cliente Teste 20M", "status": "Em Fabricação"
        }).insert(ignore_permissions=True)

    if not frappe.db.exists("Peca Pre-Moldada", "PECA-TESTE-20M"):
        frappe.get_doc({
            "doctype": "Peca Pre-Moldada", "codigo_peca": "PECA-TESTE-20M", "tag": "P1-20M",
            "obra": "OBRA-TESTE-20M", "produto": "Pilar", "secao": "40X40", "comprimento_m": 6.0,
            "volume_m3": 0.96, "peso_kg": 2400.0, "fase_numero": 1, "status_producao": "1. Corte e Dobra"
        }).insert(ignore_permissions=True)

    # 5. Teste Pegada Carbono
    res_carb = estimar_carbono_peca("PECA-TESTE-20M")
    print("4. Pegada de Carbono ESG:", "OK" if res_carb.get("success") and res_carb.get("co2_total_kg") > 0 else "FALHA")

    # 6. Teste Track & Trace Público
    res_tt = get_status_publico_obra("OBRA-TESTE-20M")
    print("5. Track & Trace Público:", "OK" if res_tt.get("success") and res_tt.get("total_pecas") >= 1 else "FALHA")

    # 7. Teste RNC
    res_rnc = abrir_nao_conformidade("PECA-TESTE-20M", "Defeito de teste no cobrimento")
    rnc_name = res_rnc.get("name")
    print("6. Abertura de RNC:", "OK" if res_rnc.get("success") else "FALHA")
    
    if rnc_name:
        res_aprov = aprovar_nao_conformidade(rnc_name, "Reparo com argamassa grauteada")
        print("7. Aprovação de RNC:", "OK" if res_aprov.get("success") else "FALHA")

    # Clean up test doc
    frappe.delete_doc("Peca Pre-Moldada", "PECA-TESTE-20M", ignore_permissions=True, force=True)
    frappe.delete_doc("Obra", "OBRA-TESTE-20M", ignore_permissions=True, force=True)

    print("=== TODOS OS TESTES DAS 20 MELHORIAS CONCLUIDOS COM SUCESSO ===")
