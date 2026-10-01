"""
Traduções para português do Brasil dos textos do ERPNext/RH que a tradução oficial deixou em inglês
(telas que o cliente enxerga). Vira registros do cadastro de Traduções do site; idempotente.
Cobertura medida em 30/09/2026 percorrendo as telas dos módulos vendidos: tests/coletar_textos_desk.py.
"""
import frappe

IDIOMA = "pt-BR"

TRADUCOES = {
    # marca
    "ERPNext": "ERP Precast", "Frappe HR": "Recursos Humanos", "Frappe CRM": "CRM",
    # tela de entrada
    "Sign In": "Entrar", "Welcome! Please sign in to continue.": "Bem-vindo! Entre para continuar.", "Forgot password?": "Esqueceu a senha?",
    "Login": "Entrar", "Login to ERP Precast": "Entrar no ERP Precast", "Login with Email Link": "Entrar com link por e-mail",
    # contabilidade e compras
    "Accounting Entries": "Lançamentos Contábeis", "Accounting Reports": "Relatórios Contábeis",
    "Advances": "Adiantamentos", "Advance Payment Status": "Situação do Adiantamento",
    "Billing Currency": "Moeda de Faturamento", "Billing Status": "Situação do Faturamento",
    "Budget Variance": "Variação do Orçamento", "Consolidated Report": "Relatório Consolidado",
    "Cost Center Allocation": "Alocação de Centro de Custo", "Custom Financial Statement": "Demonstrativo Financeiro Personalizado",
    "Customer Ledger": "Razão de Clientes", "Customer Ledger Summary": "Resumo do Razão de Clientes",
    "Customer Type": "Tipo de Cliente", "Entry Type": "Tipo de Lançamento", "Financial Report Template": "Modelo de Relatório Financeiro",
    "Financial Reports": "Relatórios Financeiros", "Incoming Bills": "Faturas Recebidas", "Outgoing Bills": "Faturas a Pagar",
    "Outgoing Payment": "Pagamentos Efetuados", "Payables": "Contas a Pagar", "Receivables": "Contas a Receber",
    "Payment Type": "Tipo de Pagamento", "Process Payment Reconciliation": "Processar Conciliação de Pagamentos",
    "Procurement Tracker": "Acompanhamento de Compras", "Project Profitability": "Rentabilidade do Projeto",
    "Repost Payment Ledger": "Reprocessar Razão de Pagamentos", "Supplier Ledger": "Razão de Fornecedores",
    "Supplier Ledger Summary": "Resumo do Razão de Fornecedores", "Supplier of Goods or Services.": "Fornecedor de bens ou serviços.",
    "Tax Masters": "Cadastros de Impostos", "Tax Setup": "Configuração de Impostos", "Tax Template": "Modelo de Imposto",
    "Terms Template": "Modelo de Termos", "Terms and Conditions Template": "Modelo de Termos e Condições",
    "Unreconcile Payment": "Desfazer Conciliação de Pagamento", "Ledgers": "Razões",
    "Material Requests for which Supplier Quotations are not created": "Requisições de Material sem Cotação de Fornecedor",
    "Items to Order and Receive": "Itens para Pedir e Receber", "Requested Items To Be Transferred": "Itens Solicitados para Transferência",
    "Subcontracted Item To Be Received": "Item Subcontratado a Receber", "Purchase Orders Count": "Quantidade de Pedidos de Compra",
    "Total Purchase Amount": "Valor Total de Compras", "Total Sales Amount": "Valor Total de Vendas",
    # vendas e estoque
    "Sales & Purchase": "Vendas e Compras", "Sales Pipeline": "Funil de Vendas", "Potential Sales Deal": "Negócio em Potencial",
    "Sales Partner Target Variance Based On Item Group": "Desvio de Meta do Parceiro de Vendas por Grupo de Itens",
    "Items & Pricing": "Itens e Preços", "Items Catalogue": "Catálogo de Itens", "Item Manufacturer": "Fabricante do Item",
    "Item Variant Details": "Detalhes das Variantes do Item", "Item Wise Consumption": "Consumo por Item",
    "Itemwise Recommended Reorder Level": "Nível de Reposição Recomendado por Item", "Has Variants": "Possui Variantes",
    "Inventory Dimension": "Dimensão de Estoque", "Batch Item Expiry Status": "Validade dos Itens por Lote", "Batch No": "Nº do Lote",
    "Serial No": "Nº de Série", "Serial No Ledger": "Razão de Nº de Série", "Serial No Status": "Situação do Nº de Série",
    "Serial No Service Contract Expiry": "Vencimento do Contrato de Serviço por Nº de Série",
    "Serial No Warranty Expiry": "Vencimento da Garantia por Nº de Série",
    "Serial No and Batch Traceability": "Rastreabilidade por Nº de Série e Lote", "Serial and Batch Bundle": "Pacote de Nº de Série e Lote",
    "Warehouse Wise Stock Balance": "Saldo de Estoque por Depósito", "Total Active Items": "Total de Itens Ativos",
    "Total Stock Value": "Valor Total em Estoque", "Total Warehouses": "Total de Depósitos", "POS": "PDV",
    "Point-of-Sale Profile": "Perfil do Ponto de Venda", "Unit of Measure (UOM)": "Unidade de Medida (UM)",
    "Masters & Reports": "Cadastros e Relatórios", "Reports & Masters": "Relatórios e Cadastros",
    "Transactions & Reports": "Transações e Relatórios", "Fleet Management": "Gestão de Frota", "Tools": "Ferramentas",
    "Begin typing for results.": "Comece a digitar para ver os resultados.", "Filters": "Filtros",
    # recursos humanos
    "Activity Type": "Tipo de Atividade", "Additional Salary": "Salário Adicional", "Address And Contacts": "Endereços e Contatos",
    "Application": "Solicitação", "Apply / Approve Leaves": "Solicitar / Aprovar Licenças", "Appointment Letter": "Carta de Contratação",
    "Appointment Letter Template": "Modelo de Carta de Contratação", "Appraisal": "Avaliação de Desempenho",
    "Appraisal Cycle": "Ciclo de Avaliação", "Appraisal Overview": "Visão Geral das Avaliações", "Attendance": "Frequência",
    "Attendance Request": "Solicitação de Frequência", "Benefit Application": "Solicitação de Benefício", "Benefit Claim": "Pedido de Benefício",
    "Benefits": "Benefícios", "Bulk Salary Structure Assignment": "Atribuição em Massa de Estrutura Salarial", "Claims": "Reembolsos",
    "Compensatory Leave Request": "Solicitação de Folga Compensatória", "Daily Work Summary": "Resumo Diário de Trabalho",
    "Daily Work Summary Group": "Grupo do Resumo Diário de Trabalho", "Daily Work Summary Replies": "Respostas do Resumo Diário de Trabalho",
    "Deduction Reports": "Relatórios de Deduções", "Department Wise Openings": "Vagas por Departamento",
    "Employee Analytics": "Análise de Colaboradores", "Employee Attendance Tool": "Ferramenta de Frequência de Colaboradores",
    "Employee Benefit Application": "Solicitação de Benefício do Colaborador", "Employee Benefit Claim": "Pedido de Benefício do Colaborador",
    "Employee Birthday": "Aniversariantes", "Employee Checkin": "Registro de Ponto", "Employee Exits": "Desligamentos",
    "Employee Grievance": "Reclamação de Colaborador", "Employee Hours Utilization Based On Timesheet": "Utilização de Horas por Folha de Ponto",
    "Employee Incentive": "Incentivo ao Colaborador", "Employee Information": "Informações do Colaborador",
    "Employee Leave Balance": "Saldo de Licenças do Colaborador", "Employee Leave Balance Summary": "Resumo do Saldo de Licenças",
    "Employee Onboarding": "Integração de Colaborador", "Employee Onboarding Template": "Modelo de Integração de Colaborador",
    "Employee Performance Feedback": "Feedback de Desempenho do Colaborador", "Employee Promotion": "Promoção de Colaborador",
    "Employee Referral": "Indicação de Colaborador", "Employee Separation": "Desligamento de Colaborador", "Employee Skill Map": "Mapa de Competências",
    "Employee Tax Exemption Category": "Categoria de Isenção de Imposto do Colaborador",
    "Employee Tax Exemption Declaration": "Declaração de Isenção de Imposto do Colaborador",
    "Employee Tax Exemption Proof Submission": "Comprovação de Isenção de Imposto do Colaborador",
    "Employee Tax Exemption Sub Category": "Subcategoria de Isenção de Imposto do Colaborador",
    "Employees on leave this month": "Colaboradores de licença neste mês", "Employees on leave today": "Colaboradores de licença hoje",
    "Employees working on a holiday": "Colaboradores trabalhando em feriado", "Exemption": "Isenção", "Exemption Declaration": "Declaração de Isenção",
    "Exemption Submission Proof": "Comprovante de Isenção", "Exits (This Month)": "Desligamentos (neste mês)",
    "Expense Claim": "Reembolso de Despesa", "Expense Claim Type": "Tipo de Reembolso de Despesa", "Expense Claims": "Reembolsos de Despesa",
    "Unpaid Expense Claim": "Reembolsos de Despesa Não Pagos", "Feedback Score": "Nota do Feedback", "Final Score": "Nota Final",
    "Goal Score": "Nota da Meta", "Self Score": "Autoavaliação", "Grievance": "Reclamação", "Grievance Type": "Tipo de Reclamação",
    "Hiring Pipeline": "Funil de Contratação", "Import Employees": "Importar Colaboradores", "Income Tax Computation": "Cálculo do Imposto de Renda",
    "Income Tax Deductions": "Deduções do Imposto de Renda", "Income Tax Slab": "Tabela do Imposto de Renda", "Interview": "Entrevista",
    "Interview Feedback": "Feedback da Entrevista", "Interview Type": "Tipo de Entrevista", "Interviews": "Entrevistas",
    "Interviews (This Week)": "Entrevistas (esta semana)", "Job Applicant": "Candidato à Vaga", "Job Offer": "Proposta de Emprego",
    "Job Opening": "Vaga", "Job Portal": "Portal de Vagas", "Job Requisition": "Requisição de Vaga", "Jobs": "Vagas",
    "Leave Allocation": "Alocação de Licença", "Leave Application": "Solicitação de Licença", "Leave Block List": "Lista de Bloqueio de Licenças",
    "Leave Control Panel": "Painel de Controle de Licenças", "Leave Encashment": "Conversão de Licença em Dinheiro", "Leave Period": "Período de Licença",
    "Leave Policy": "Política de Licenças", "Leave Policy Assignment": "Atribuição de Política de Licenças", "Leave Type": "Tipo de Licença",
    "Leaves": "Licenças", "Monthly Attendance Sheet": "Folha Mensal de Frequência", "New Hires (This Month)": "Novas Contratações (neste mês)",
    "Onboarding": "Integração", "Overtime": "Hora Extra", "Overtime Slip": "Folha de Hora Extra", "Overtime Type": "Tipo de Hora Extra",
    "Outgoing Salary": "Salários Pagos", "Payroll": "Folha de Pagamento", "Payroll Entry": "Lançamento da Folha de Pagamento",
    "Payroll Period": "Período da Folha de Pagamento", "Payroll Reports": "Relatórios da Folha de Pagamento", "Performance": "Desempenho",
    "Professional Tax Deductions": "Deduções de Imposto Profissional", "Provident Fund Deductions": "Deduções do Fundo de Previdência",
    "Recruitment": "Recrutamento", "Recruitment Analytics": "Análise de Recrutamento", "Retention Bonus": "Bônus de Retenção", "Roster": "Escala",
    "Salary Component": "Componente Salarial", "Salary Payments Based On Payment Mode": "Pagamentos de Salário por Forma de Pagamento",
    "Salary Payments via ECS": "Pagamentos de Salário via Transferência", "Salary Register": "Registro de Salários", "Salary Slip": "Holerite",
    "Salary Structure": "Estrutura Salarial", "Salary Structure Assignment": "Atribuição de Estrutura Salarial",
    "Salary Withholding": "Retenção de Salário", "Shift Assignment": "Atribuição de Turno", "Shift Assignment Tool": "Ferramenta de Atribuição de Turno",
    "Shift Attendance": "Frequência por Turno", "Shift Location": "Local do Turno", "Shift Request": "Solicitação de Turno",
    "Shift Schedule": "Escala de Turnos", "Shift Schedule Assignment": "Atribuição de Escala de Turnos", "Shift Type": "Tipo de Turno",
    "Staffing Plan": "Plano de Pessoal", "Tax & Benefits": "Impostos e Benefícios", "Tenure": "Tempo de Casa", "Training": "Treinamento",
    "Training Event": "Evento de Treinamento", "Training Feedback": "Feedback de Treinamento", "Training Program": "Programa de Treinamento",
    "Training Result": "Resultado de Treinamento", "Trainings (This Week)": "Treinamentos (esta semana)",
    # filtros de relatório
    "Masters &amp; Reports": "Cadastros e Relatórios", "Reports &amp; Masters": "Relatórios e Cadastros",
    "Transactions &amp; Reports": "Transações e Relatórios", "Tax &amp; Benefits": "Impostos e Benefícios",
    "Items &amp; Pricing": "Itens e Preços", "Sales &amp; Purchase": "Vendas e Compras", "Bank Remittance": "Remessa Bancária",
    "Demo Customer Group": "Grupo de Clientes (modelo)", "Interview Feedback": "Feedback da Entrevista",
    "company": "Empresa", "customer": "Cliente", "department": "Departamento", "employee": "Colaborador", "party": "Parte",
    "project": "Projeto", "status": "Situação", "supplier": "Fornecedor", "territory": "Território", "title": "Título",
}


def aplicar_traducoes():
    # nome do aplicativo de RH no menu inicial (o rótulo não passa pela tradução)
    if frappe.db.exists("Desktop Icon", "Frappe HR") and not frappe.db.exists("Desktop Icon", {"label": "Recursos Humanos"}):
        frappe.db.set_value("Desktop Icon", "Frappe HR", "label", "Recursos Humanos")
    from frappe.precast_traducoes_auto import carregar
    todas = {**carregar(), **TRADUCOES}  # as escritas à mão têm prioridade
    novas = 0
    for origem, destino in todas.items():
        existente = frappe.db.get_value("Translation", {"language": IDIOMA, "source_text": origem}, ["name", "translated_text"], as_dict=True)
        if existente:
            if existente.translated_text != destino:
                frappe.db.set_value("Translation", existente.name, "translated_text", destino)
            continue
        frappe.get_doc({"doctype": "Translation", "language": IDIOMA, "source_text": origem, "translated_text": destino}).insert(ignore_permissions=True)
        novas += 1
    frappe.db.commit()
    frappe.clear_cache()
    print(f"Traduções: {novas} novas, {len(todas) - novas} já existiam.")
