"""
Cria, de forma idempotente, todo o schema customizado do ERP Precast
(doctypes + papeis de setor) numa site nova ou já existente. É o script
canônico usado tanto pra reparar um cliente existente quanto pra provisionar um novo
novo — ver scripts/provisionar_cliente.sh.

O schema fica embutido neste arquivo (ver SCHEMA_JSON abaixo) pra não
depender de nenhum outro arquivo estar no lugar certo dentro do container.
Pra atualizar depois de mudar um doctype na Desk, regenere o dump (ver
core_patches/README.md) e cole o JSON novo aqui.
"""
import json

import frappe

SETORES_ASSENTO = ["Direção", "Produção", "Qualidade", "Logística", "Comercial", "Financeiro", "RH"]

# Ordem que evita qualquer problema de Link apontando pra doctype que ainda
# não existe (não é estritamente necessário no Frappe, mas deixa o log claro).
ORDEM_CRIACAO = [
    "Transportadora", "Motorista", "Caminhao", "Obra", "Forma Pista", "Romaneio",
    "Peca Pre-Moldada", "Fase Historico", "Nao Conformidade", "Checklist Qualidade",
    "Contato Comercial", "Nota Fiscal", "Cotacao Insumo",
    "Assento", "Configuracao Assentos",
]

SCHEMA_JSON = r'''
{
 "Obra": {
  "module": "Projects",
  "naming_rule": "By fieldname",
  "autoname": "field:codigo_obra",
  "issingle": 0,
  "fields": [
   {
    "fieldname": "codigo_obra",
    "label": "Código da Obra",
    "fieldtype": "Data",
    "reqd": 1,
    "unique": 1
   },
   {
    "fieldname": "nome_obra",
    "label": "Nome da Obra",
    "fieldtype": "Data",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "cliente",
    "label": "Cliente",
    "fieldtype": "Link",
    "options": "Customer",
    "in_list_view": 1
   },
   {
    "fieldname": "cliente_nome",
    "label": "Nome do Cliente",
    "fieldtype": "Data"
   },
   {
    "fieldname": "cidade_uf",
    "label": "Cidade / UF",
    "fieldtype": "Data",
    "in_list_view": 1
   },
   {
    "fieldname": "fck_padrao",
    "label": "FCK Padrão",
    "fieldtype": "Data",
    "default": "40 MPa"
   },
   {
    "fieldname": "status",
    "label": "Status",
    "fieldtype": "Select",
    "options": "Orçamento\nContratada\nEm Projeto\nEm Fabricação\nConcluída",
    "in_list_view": 1,
    "default": "Em Fabricação"
   },
   {
    "fieldname": "cor_identificacao",
    "label": "Cor no Cronograma",
    "fieldtype": "Color",
    "default": "#1e40af"
   },
   {
    "fieldname": "arquivo_cad",
    "label": "Arquivo CAD Original",
    "fieldtype": "Data"
   },
   {
    "fieldname": "customer",
    "label": "Cliente (ERPNext)",
    "fieldtype": "Link",
    "options": "Customer"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Peca Pre-Moldada": {
  "module": "Manufacturing",
  "naming_rule": "By fieldname",
  "autoname": "field:codigo_peca",
  "issingle": 0,
  "fields": [
   {
    "fieldname": "codigo_peca",
    "label": "Código da Peça",
    "fieldtype": "Data",
    "reqd": 1,
    "in_list_view": 1,
    "unique": 1
   },
   {
    "fieldname": "tag",
    "label": "Etiqueta / Tag",
    "fieldtype": "Data",
    "in_list_view": 1
   },
   {
    "fieldname": "obra",
    "label": "Obra",
    "fieldtype": "Link",
    "options": "Obra",
    "in_list_view": 1
   },
   {
    "fieldname": "cliente",
    "label": "Cliente",
    "fieldtype": "Data"
   },
   {
    "fieldname": "produto",
    "label": "Tipo de Peça",
    "fieldtype": "Select",
    "options": "Pilar\nViga\nPainel de Fechamento\nLaje Alveolar\nBloco de Fundação\nTerça\nEscada\nEstaca\nOutros",
    "in_list_view": 1,
    "default": "Pilar"
   },
   {
    "fieldname": "grupo",
    "label": "Grupo",
    "fieldtype": "Select",
    "options": "Armada\nProtendida\nMista",
    "default": "Armada"
   },
   {
    "fieldname": "secao",
    "label": "Seção (cm)",
    "fieldtype": "Data",
    "in_list_view": 1
   },
   {
    "fieldname": "comprimento_m",
    "label": "Comprimento (m)",
    "fieldtype": "Float",
    "in_list_view": 1
   },
   {
    "fieldname": "volume_m3",
    "label": "Volume (m³)",
    "fieldtype": "Float"
   },
   {
    "fieldname": "peso_kg",
    "label": "Peso (kg)",
    "fieldtype": "Float",
    "in_list_view": 1
   },
   {
    "fieldname": "fck",
    "label": "FCK",
    "fieldtype": "Data",
    "default": "40 MPa"
   },
   {
    "fieldname": "cobrimento_cm",
    "label": "Cobrimento (cm)",
    "fieldtype": "Float",
    "default": "2.5"
   },
   {
    "fieldname": "status_producao",
    "label": "Status Produção",
    "fieldtype": "Select",
    "options": "1. Corte e Dobra\n2. Armação Pronta\n3. Forma e Embutidos\n4. Concretado\n5. Curado / Desmoldado\n6. Pátio / Liberado CQ\n7. Expedido\n8. Montado na Obra",
    "in_list_view": 1,
    "default": "1. Corte e Dobra"
   },
   {
    "fieldname": "fase_numero",
    "label": "Fase Atual (1 a 9)",
    "fieldtype": "Int",
    "default": "1"
   },
   {
    "fieldname": "prancha_pdf",
    "label": "Prancha Individual (PDF)",
    "fieldtype": "Attach"
   },
   {
    "fieldname": "prancha_png",
    "label": "Print da Peça (PNG)",
    "fieldtype": "Attach Image"
   },
   {
    "fieldname": "prancha_url",
    "label": "URL Direta Prancha",
    "fieldtype": "Data"
   },
   {
    "fieldname": "print_url",
    "label": "URL Direta Print",
    "fieldtype": "Data"
   },
   {
    "fieldname": "arquivo_origem",
    "label": "Arquivo CAD de Origem",
    "fieldtype": "Data"
   },
   {
    "fieldname": "dimensoes_confirmadas",
    "label": "Dimensões Confirmadas",
    "fieldtype": "Check",
    "default": "1"
   },
   {
    "fieldname": "aviso_engenharia",
    "label": "Avisos de Engenharia",
    "fieldtype": "Small Text"
   },
   {
    "fieldname": "qr_code_payload",
    "label": "Payload QR Code",
    "fieldtype": "Data"
   },
   {
    "fieldname": "data_fabricacao_prevista",
    "label": "Data Prevista",
    "fieldtype": "Date"
   },
   {
    "fieldname": "data_fabricacao_real",
    "label": "Data Fabricação",
    "fieldtype": "Date"
   },
   {
    "fieldname": "forma_utilizada",
    "label": "Pista / Forma",
    "fieldtype": "Data"
   },
   {
    "fieldname": "forma_pista",
    "label": "Forma/Pista",
    "fieldtype": "Link",
    "options": "Forma Pista"
   },
   {
    "fieldname": "data_programada",
    "label": "Data Programada",
    "fieldtype": "Date"
   },
   {
    "fieldname": "romaneio",
    "label": "Romaneio",
    "fieldtype": "Link",
    "options": "Romaneio"
   },
   {
    "fieldname": "custo_estimado_peca",
    "label": "Custo Estimado (R$)",
    "fieldtype": "Currency"
   },
   {
    "fieldname": "preco_venda_sugerido",
    "label": "Preço de Venda Sugerido (R$)",
    "fieldtype": "Currency"
   },
   {
    "fieldname": "faturado_montagem",
    "label": "Faturado (Montagem)",
    "fieldtype": "Check",
    "default": "0"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Forma Pista": {
  "module": "Custom",
  "naming_rule": "By fieldname",
  "autoname": "field:codigo",
  "issingle": 0,
  "fields": [
   {
    "fieldname": "codigo",
    "label": "Código",
    "fieldtype": "Data",
    "reqd": 1,
    "in_list_view": 1,
    "unique": 1
   },
   {
    "fieldname": "tipo",
    "label": "Tipo",
    "fieldtype": "Select",
    "options": "Pista de Protensão\nFôrma\nMesa Vibratória",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "comprimento_m",
    "label": "Comprimento (m)",
    "fieldtype": "Float"
   },
   {
    "fieldname": "largura_m",
    "label": "Largura (m)",
    "fieldtype": "Float"
   },
   {
    "fieldname": "capacidade_kg",
    "label": "Capacidade (kg)",
    "fieldtype": "Float"
   },
   {
    "fieldname": "status",
    "label": "Status",
    "fieldtype": "Select",
    "options": "Livre\nOcupada\nManutenção",
    "in_list_view": 1,
    "default": "Livre"
   },
   {
    "fieldname": "giros_realizados",
    "label": "Giros Realizados",
    "fieldtype": "Int",
    "in_list_view": 1,
    "default": "0"
   },
   {
    "fieldname": "giros_limite_manutencao",
    "label": "Giros até Manutenção Preventiva",
    "fieldtype": "Int",
    "default": "50"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Fase Historico": {
  "module": "Custom",
  "naming_rule": "Autoincrement",
  "autoname": null,
  "issingle": 0,
  "fields": [
   {
    "fieldname": "codigo_peca",
    "label": "Peça",
    "fieldtype": "Link",
    "options": "Peca Pre-Moldada",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "forma_pista",
    "label": "Forma/Pista",
    "fieldtype": "Link",
    "options": "Forma Pista",
    "in_list_view": 1
   },
   {
    "fieldname": "fase_anterior",
    "label": "Fase Anterior",
    "fieldtype": "Int"
   },
   {
    "fieldname": "fase_nova",
    "label": "Fase Nova",
    "fieldtype": "Int",
    "in_list_view": 1
   },
   {
    "fieldname": "data_hora",
    "label": "Data/Hora",
    "fieldtype": "Datetime",
    "in_list_view": 1
   },
   {
    "fieldname": "usuario",
    "label": "Usuário",
    "fieldtype": "Data"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Nao Conformidade": {
  "module": "Custom",
  "naming_rule": "Autoincrement",
  "autoname": null,
  "issingle": 0,
  "fields": [
   {
    "fieldname": "codigo_peca",
    "label": "Peça",
    "fieldtype": "Link",
    "options": "Peca Pre-Moldada",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "descricao",
    "label": "Descrição do Defeito",
    "fieldtype": "Small Text",
    "reqd": 1
   },
   {
    "fieldname": "foto",
    "label": "Foto/Laudo Fotográfico",
    "fieldtype": "Attach Image"
   },
   {
    "fieldname": "status",
    "label": "Status",
    "fieldtype": "Select",
    "options": "Aberta\nEm Reparo\nAprovada",
    "in_list_view": 1,
    "default": "Aberta"
   },
   {
    "fieldname": "receita_reparo",
    "label": "Receita de Reparo (Engenharia)",
    "fieldtype": "Small Text"
   },
   {
    "fieldname": "aberto_por",
    "label": "Aberto por",
    "fieldtype": "Data"
   },
   {
    "fieldname": "data_abertura",
    "label": "Data de Abertura",
    "fieldtype": "Datetime",
    "in_list_view": 1
   },
   {
    "fieldname": "data_aprovacao",
    "label": "Data de Aprovação",
    "fieldtype": "Datetime"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Romaneio": {
  "module": "Custom",
  "naming_rule": "By fieldname",
  "autoname": "field:codigo",
  "issingle": 0,
  "fields": [
   {
    "fieldname": "codigo",
    "label": "Código",
    "fieldtype": "Data",
    "reqd": 1,
    "in_list_view": 1,
    "unique": 1
   },
   {
    "fieldname": "obra",
    "label": "Obra",
    "fieldtype": "Link",
    "options": "Obra",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "caminhao",
    "label": "Caminhão",
    "fieldtype": "Link",
    "options": "Caminhao",
    "reqd": 1
   },
   {
    "fieldname": "motorista",
    "label": "Motorista",
    "fieldtype": "Link",
    "options": "Motorista"
   },
   {
    "fieldname": "data_expedicao",
    "label": "Data de Expedição",
    "fieldtype": "Date",
    "reqd": 1
   },
   {
    "fieldname": "status",
    "label": "Status",
    "fieldtype": "Select",
    "options": "Montando\nDespachado\nEntregue",
    "in_list_view": 1,
    "default": "Montando"
   },
   {
    "fieldname": "peso_total_kg",
    "label": "Peso Total (kg)",
    "fieldtype": "Float"
   },
   {
    "fieldname": "assinatura_recebedor",
    "label": "Assinatura do Recebedor",
    "fieldtype": "Attach Image"
   },
   {
    "fieldname": "recebedor_nome",
    "label": "Nome de Quem Recebeu",
    "fieldtype": "Data"
   },
   {
    "fieldname": "data_entrega",
    "label": "Data/Hora da Entrega",
    "fieldtype": "Datetime"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Caminhao": {
  "module": "Custom",
  "naming_rule": "By fieldname",
  "autoname": "field:placa",
  "issingle": 0,
  "fields": [
   {
    "fieldname": "placa",
    "label": "Placa",
    "fieldtype": "Data",
    "reqd": 1,
    "in_list_view": 1,
    "unique": 1
   },
   {
    "fieldname": "transportadora",
    "label": "Transportadora",
    "fieldtype": "Link",
    "options": "Transportadora"
   },
   {
    "fieldname": "capacidade_kg",
    "label": "Capacidade (kg)",
    "fieldtype": "Float",
    "reqd": 1
   },
   {
    "fieldname": "motorista_padrao",
    "label": "Motorista Padrão",
    "fieldtype": "Link",
    "options": "Motorista"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Motorista": {
  "module": "Custom",
  "naming_rule": "By fieldname",
  "autoname": "field:nome",
  "issingle": 0,
  "fields": [
   {
    "fieldname": "nome",
    "label": "Nome",
    "fieldtype": "Data",
    "reqd": 1,
    "in_list_view": 1,
    "unique": 1
   },
   {
    "fieldname": "cnh",
    "label": "CNH",
    "fieldtype": "Data"
   },
   {
    "fieldname": "telefone",
    "label": "Telefone",
    "fieldtype": "Data"
   },
   {
    "fieldname": "transportadora",
    "label": "Transportadora",
    "fieldtype": "Link",
    "options": "Transportadora"
   },
   {
    "fieldname": "avaliacao",
    "label": "Avaliação (1-5)",
    "fieldtype": "Int",
    "default": "5"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Transportadora": {
  "module": "Custom",
  "naming_rule": "By fieldname",
  "autoname": "field:nome",
  "issingle": 0,
  "fields": [
   {
    "fieldname": "nome",
    "label": "Nome",
    "fieldtype": "Data",
    "reqd": 1,
    "in_list_view": 1,
    "unique": 1
   },
   {
    "fieldname": "cnpj",
    "label": "CNPJ",
    "fieldtype": "Data"
   },
   {
    "fieldname": "telefone",
    "label": "Telefone",
    "fieldtype": "Data"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Checklist Qualidade": {
  "module": "Custom",
  "naming_rule": "Autoincrement",
  "autoname": null,
  "issingle": 0,
  "fields": [
   {
    "fieldname": "codigo_peca",
    "label": "Peça",
    "fieldtype": "Link",
    "options": "Peca Pre-Moldada",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "etapa",
    "label": "Etapa",
    "fieldtype": "Select",
    "options": "1. Corte e Dobra\n2. Armação\n3. Fôrma\n4. Fôrma + Armação (Insertos)\n5. Concretagem",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "aprovado",
    "label": "Aprovado",
    "fieldtype": "Check",
    "default": "1"
   },
   {
    "fieldname": "inspetor",
    "label": "Inspetor",
    "fieldtype": "Data"
   },
   {
    "fieldname": "data_inspecao",
    "label": "Data/Hora da Inspeção",
    "fieldtype": "Datetime"
   },
   {
    "fieldname": "observacoes",
    "label": "Observações",
    "fieldtype": "Small Text"
   },
   {
    "fieldname": "caminhao_betoneira",
    "label": "Caminhão Betoneira",
    "fieldtype": "Data"
   },
   {
    "fieldname": "lote_concreto",
    "label": "Lote do Concreto",
    "fieldtype": "Data"
   },
   {
    "fieldname": "fck_corpo_prova",
    "label": "FCK Corpo de Prova",
    "fieldtype": "Data"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Contato Comercial": {
  "module": "Custom",
  "naming_rule": "Autoincrement",
  "autoname": null,
  "issingle": 0,
  "fields": [
   {
    "fieldname": "nome",
    "label": "Nome",
    "fieldtype": "Data",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "empresa",
    "label": "Empresa",
    "fieldtype": "Data",
    "in_list_view": 1
   },
   {
    "fieldname": "telefone",
    "label": "Telefone",
    "fieldtype": "Data"
   },
   {
    "fieldname": "email",
    "label": "E-mail",
    "fieldtype": "Data",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "mensagem",
    "label": "Mensagem",
    "fieldtype": "Small Text"
   },
   {
    "fieldname": "data_envio",
    "label": "Data do Envio",
    "fieldtype": "Datetime"
   },
   {
    "fieldname": "status",
    "label": "Status",
    "fieldtype": "Select",
    "options": "Novo\nEm Contato\nConvertido\nDescartado",
    "in_list_view": 1,
    "default": "Novo"
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Nota Fiscal": {
  "module": "Custom",
  "naming_rule": "Autoincrement",
  "autoname": null,
  "issingle": 0,
  "fields": [
   {
    "fieldname": "sales_invoice",
    "label": "Fatura (Sales Invoice)",
    "fieldtype": "Link",
    "options": "Sales Invoice",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "referencia",
    "label": "Referência",
    "fieldtype": "Data",
    "in_list_view": 1
   },
   {
    "fieldname": "status",
    "label": "Status",
    "fieldtype": "Select",
    "options": "processando_autorizacao\nautorizado\nerro_autorizacao\nerro\ncancelado",
    "in_list_view": 1
   },
   {
    "fieldname": "numero_nf",
    "label": "Número da NF",
    "fieldtype": "Data",
    "in_list_view": 1
   },
   {
    "fieldname": "chave_acesso",
    "label": "Chave de Acesso",
    "fieldtype": "Data"
   },
   {
    "fieldname": "mensagem_erro",
    "label": "Mensagem/Erro",
    "fieldtype": "Small Text"
   },
   {
    "fieldname": "ambiente",
    "label": "Ambiente",
    "fieldtype": "Select",
    "options": "Homologação\nProdução",
    "default": "Homologação"
   },
   {
    "fieldname": "data_emissao",
    "label": "Data de Emissão",
    "fieldtype": "Datetime",
    "in_list_view": 1
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Cotacao Insumo": {
  "module": "Custom",
  "naming_rule": "Autoincrement",
  "autoname": null,
  "issingle": 0,
  "fields": [
   {
    "fieldname": "data",
    "label": "Data",
    "fieldtype": "Date",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "insumo",
    "label": "Insumo",
    "fieldtype": "Select",
    "options": "Dólar (USD)\nAço CA-50\nAço CA-60\nCimento CP-II\nCimento CP-V\nAreia\nBrita/Pedra\nCordoalha\nTerra\nOutro",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "insumo_outro",
    "label": "Nome do Insumo (se Outro)",
    "fieldtype": "Data"
   },
   {
    "fieldname": "valor",
    "label": "Valor",
    "fieldtype": "Float",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "unidade",
    "label": "Unidade",
    "fieldtype": "Select",
    "options": "USD\nkg\nsaca 50kg\nton\nm³\nunidade",
    "in_list_view": 1
   },
   {
    "fieldname": "fonte",
    "label": "Fonte",
    "fieldtype": "Select",
    "options": "Manual\nAutomático",
    "in_list_view": 1,
    "default": "Manual"
   },
   {
    "fieldname": "observacao",
    "label": "Observação",
    "fieldtype": "Small Text"
   },
   {
    "fieldname": "lancado_por",
    "label": "Lançado por",
    "fieldtype": "Data",
    "read_only": 1
   }
  ],
  "permissions": [
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Assento": {
  "module": "Custom",
  "naming_rule": "Autoincrement",
  "autoname": null,
  "issingle": 0,
  "fields": [
   {
    "fieldname": "user",
    "label": "Usuário",
    "fieldtype": "Link",
    "options": "User",
    "reqd": 1,
    "in_list_view": 1,
    "unique": 1
   },
   {
    "fieldname": "setor",
    "label": "Setor",
    "fieldtype": "Select",
    "options": "Direção\nProdução\nQualidade\nLogística\nComercial\nFinanceiro\nRH",
    "reqd": 1,
    "in_list_view": 1
   },
   {
    "fieldname": "ativo",
    "label": "Ativo",
    "fieldtype": "Check",
    "in_list_view": 1,
    "default": "1"
   },
   {
    "fieldname": "incluido_no_plano",
    "label": "Incluído no plano base",
    "fieldtype": "Check",
    "default": "1"
   },
   {
    "fieldname": "data_ativacao",
    "label": "Data de Ativação",
    "fieldtype": "Datetime"
   }
  ],
  "permissions": [
   {
    "role": "Direção",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   },
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 },
 "Configuracao Assentos": {
  "module": "Custom",
  "naming_rule": "",
  "autoname": null,
  "issingle": 1,
  "fields": [
   {
    "fieldname": "limite_direcao",
    "label": "Limite - Direção",
    "fieldtype": "Int",
    "default": "1"
   },
   {
    "fieldname": "limite_producao",
    "label": "Limite - Produção",
    "fieldtype": "Int",
    "default": "1"
   },
   {
    "fieldname": "limite_qualidade",
    "label": "Limite - Qualidade",
    "fieldtype": "Int",
    "default": "1"
   },
   {
    "fieldname": "limite_logistica",
    "label": "Limite - Logística",
    "fieldtype": "Int",
    "default": "1"
   },
   {
    "fieldname": "limite_comercial",
    "label": "Limite - Comercial",
    "fieldtype": "Int",
    "default": "1"
   },
   {
    "fieldname": "limite_financeiro",
    "label": "Limite - Financeiro",
    "fieldtype": "Int",
    "default": "1"
   },
   {
    "fieldname": "limite_rh",
    "label": "Limite - RH",
    "fieldtype": "Int",
    "default": "1"
   }
  ],
  "permissions": [
   {
    "role": "Direção",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   },
   {
    "role": "System Manager",
    "read": 1,
    "write": 1,
    "create": 1,
    "delete": 1
   }
  ]
 }
}
'''


def _criar_roles():
    for setor in SETORES_ASSENTO:
        role_name = "Direção" if setor == "Direção" else f"Setor {setor}"
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert(ignore_permissions=True)
            print(f"Role criado: {role_name}")
    if not frappe.db.exists("Role", "Operador de Fábrica"):
        frappe.get_doc({"doctype": "Role", "role_name": "Operador de Fábrica", "desk_access": 0}).insert(ignore_permissions=True)
        print("Role criado: Operador de Fábrica")


def _criar_doctype(nome, definicao):
    if frappe.db.exists("DocType", nome):
        print(f"SKIP (já existe): {nome}")
        return

    doc_dict = {
        "doctype": "DocType", "name": nome, "module": definicao["module"], "custom": 1,
        "naming_rule": definicao["naming_rule"], "fields": definicao["fields"],
        "permissions": definicao["permissions"],
    }
    if definicao.get("autoname"):
        doc_dict["autoname"] = definicao["autoname"]
    if definicao.get("issingle"):
        doc_dict["issingle"] = 1

    frappe.get_doc(doc_dict).insert(ignore_permissions=True)
    print(f"DocType criado: {nome}")


def run():
    schema = json.loads(SCHEMA_JSON)

    _criar_roles()

    for nome in ORDEM_CRIACAO:
        definicao = schema.get(nome)
        if not definicao:
            print(f"AVISO: '{nome}' não está no schema embutido, pulei.")
            continue
        _criar_doctype(nome, definicao)

    garantir_doctypes_novos()
    print("Schema provisionado.")


DIARIO_OBRA = {
    "module": "Custom", "naming_rule": "Autoincrement", "autoname": None, "issingle": 0,
    "fields": [
        {"fieldname": "obra", "label": "Obra", "fieldtype": "Link", "options": "Obra", "reqd": 1, "in_list_view": 1},
        {"fieldname": "data", "label": "Data", "fieldtype": "Date", "reqd": 1, "in_list_view": 1},
        {"fieldname": "clima", "label": "Clima", "fieldtype": "Select", "options": "\nSol\nNublado\nChuva"},
        {"fieldname": "autor", "label": "Registrado por", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "resumo", "label": "O que foi feito", "fieldtype": "Long Text"},
    ],
    "permissions": [
        {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
        {"role": "Direção", "read": 1},
    ],
}


ROSTO_OPERADOR = {
    "module": "Custom", "naming_rule": "Autoincrement", "autoname": None, "issingle": 0,
    "fields": [
        {"fieldname": "usuario", "label": "Usuário", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1},
        {"fieldname": "nome", "label": "Nome", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "setores", "label": "Setores (JSON)", "fieldtype": "Long Text"},
        {"fieldname": "descritor", "label": "Descritor do rosto (JSON)", "fieldtype": "Long Text"},
        {"fieldname": "ativo", "label": "Ativo", "fieldtype": "Check", "default": "1"},
        {"fieldname": "ultimo_acesso", "label": "Último acesso", "fieldtype": "Datetime"},
    ],
    "permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
}


_PERMISSOES_BASE = [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}]

LOTE_CONCRETO = {
    "module": "Custom", "naming_rule": "By fieldname", "autoname": "field:codigo", "issingle": 0,
    "fields": [
        {"fieldname": "codigo", "label": "Código do lote", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1},
        {"fieldname": "data_concretagem", "label": "Data da concretagem", "fieldtype": "Date", "in_list_view": 1},
        {"fieldname": "usina", "label": "Usina / fornecedor", "fieldtype": "Data"},
        {"fieldname": "traco", "label": "Traço", "fieldtype": "Data"},
        {"fieldname": "fck_especificado", "label": "fck especificado (MPa)", "fieldtype": "Float", "reqd": 1},
        {"fieldname": "slump_cm", "label": "Slump (cm)", "fieldtype": "Float"},
        {"fieldname": "temperatura_c", "label": "Temperatura (°C)", "fieldtype": "Float"},
        {"fieldname": "volume_m3", "label": "Volume (m³)", "fieldtype": "Float"},
        {"fieldname": "nota_fiscal", "label": "Nota fiscal / ticket", "fieldtype": "Data"},
        {"fieldname": "observacoes", "label": "Observações", "fieldtype": "Small Text"},
        {"fieldname": "registrado_por", "label": "Registrado por", "fieldtype": "Data"},
    ],
    "permissions": _PERMISSOES_BASE,
}

CORPO_PROVA = {
    "module": "Custom", "naming_rule": "Autoincrement", "autoname": None, "issingle": 0,
    "fields": [
        {"fieldname": "lote", "label": "Lote", "fieldtype": "Link", "options": "Lote Concreto", "reqd": 1, "in_list_view": 1},
        {"fieldname": "idade_dias", "label": "Idade (dias)", "fieldtype": "Int", "reqd": 1, "in_list_view": 1},
        {"fieldname": "data_ruptura", "label": "Data da ruptura", "fieldtype": "Date"},
        {"fieldname": "carga_kn", "label": "Carga (kN)", "fieldtype": "Float"},
        {"fieldname": "fck_obtido", "label": "fck obtido (MPa)", "fieldtype": "Float", "reqd": 1, "in_list_view": 1},
        {"fieldname": "fck_especificado", "label": "fck especificado (MPa)", "fieldtype": "Float"},
        {"fieldname": "resultado", "label": "Resultado", "fieldtype": "Select", "options": "Parcial\nAprovado\nReprovado", "in_list_view": 1},
        {"fieldname": "responsavel", "label": "Responsável", "fieldtype": "Data"},
    ],
    "permissions": _PERMISSOES_BASE,
}

CERTIFICADO_ACO = {
    "module": "Custom", "naming_rule": "By fieldname", "autoname": "field:corrida", "issingle": 0,
    "fields": [
        {"fieldname": "corrida", "label": "Corrida / lote do aço", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1},
        {"fieldname": "bitola_mm", "label": "Bitola (mm)", "fieldtype": "Float", "reqd": 1, "in_list_view": 1},
        {"fieldname": "fabricante", "label": "Fabricante", "fieldtype": "Data"},
        {"fieldname": "norma", "label": "Categoria / norma", "fieldtype": "Data", "default": "CA-50"},
        {"fieldname": "data_recebimento", "label": "Data de recebimento", "fieldtype": "Date"},
        {"fieldname": "nota_fiscal", "label": "Nota fiscal", "fieldtype": "Data"},
        {"fieldname": "certificado_anexo", "label": "Certificado (arquivo)", "fieldtype": "Data"},
        {"fieldname": "registrado_por", "label": "Registrado por", "fieldtype": "Data"},
    ],
    "permissions": _PERMISSOES_BASE,
}

REVISAO_PROJETO = {
    "module": "Custom", "naming_rule": "Autoincrement", "autoname": None, "issingle": 0,
    "fields": [
        {"fieldname": "obra", "label": "Obra", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "numero", "label": "Número", "fieldtype": "Int", "in_list_view": 1},
        {"fieldname": "revisao", "label": "Revisão", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "arquivo", "label": "Arquivo", "fieldtype": "Data"},
        {"fieldname": "modo", "label": "Modo de gravação", "fieldtype": "Data"},
        {"fieldname": "data_hora", "label": "Data e hora", "fieldtype": "Datetime"},
        {"fieldname": "usuario", "label": "Quem gravou", "fieldtype": "Data"},
        {"fieldname": "resumo", "label": "Resumo (JSON)", "fieldtype": "Long Text"},
        {"fieldname": "diff", "label": "Diferenças (JSON)", "fieldtype": "Long Text"},
    ],
    "permissions": _PERMISSOES_BASE,
}

PLANO_CORTE = {
    "module": "Custom", "naming_rule": "Autoincrement", "autoname": None, "issingle": 0,
    "fields": [
        {"fieldname": "obra", "label": "Obra", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "numero", "label": "Número", "fieldtype": "Int", "in_list_view": 1},
        {"fieldname": "status", "label": "Situação", "fieldtype": "Select", "options": "Gerado\nEm corte\nConcluído\nCancelado", "default": "Gerado", "in_list_view": 1},
        {"fieldname": "data_hora", "label": "Data e hora", "fieldtype": "Datetime"},
        {"fieldname": "usuario", "label": "Quem gerou", "fieldtype": "Data"},
        {"fieldname": "barra_m", "label": "Barra (m)", "fieldtype": "Float"},
        {"fieldname": "barras", "label": "Barras", "fieldtype": "Int"},
        {"fieldname": "perda_pct", "label": "Perda (%)", "fieldtype": "Float"},
        {"fieldname": "aco_comprado_kg", "label": "Aço em barras (kg)", "fieldtype": "Float"},
        {"fieldname": "desatualizado", "label": "Desatualizado por revisão", "fieldtype": "Check", "default": "0"},
        {"fieldname": "pecas", "label": "Peças (JSON)", "fieldtype": "Long Text"},
        {"fieldname": "resultado", "label": "Plano (JSON)", "fieldtype": "Long Text"},
    ],
    "permissions": _PERMISSOES_BASE,
}

# Rastreabilidade de cada peça: de qual lote de concreto e de quais corridas de aço ela saiu.
CAMPOS_PECA_RASTRO = [
    {"fieldname": "lote_concreto", "label": "Lote do concreto", "fieldtype": "Link", "options": "Lote Concreto"},
    {"fieldname": "corridas_aco", "label": "Corridas do aço (lista)", "fieldtype": "Small Text"},
    {"fieldname": "plano_corte", "label": "Plano de corte do aço", "fieldtype": "Data"},
]


# Dados que a prancha de detalhamento traz de cada peça (lista de ferros, aço real, folha).
CAMPOS_PECA_PRANCHA = [
    {"fieldname": "peso_aco_kg", "label": "Aço da prancha (kg)", "fieldtype": "Float", "precision": "3"},
    {"fieldname": "taxa_aco_kg_m3", "label": "Taxa de aço (kg/m³)", "fieldtype": "Float", "precision": "3"},
    {"fieldname": "lista_ferros", "label": "Lista de ferros (JSON)", "fieldtype": "Long Text"},
    {"fieldname": "folha_prancha", "label": "Folha da prancha", "fieldtype": "Data"},
    {"fieldname": "titulo_prancha", "label": "Título da prancha", "fieldtype": "Data"},
    {"fieldname": "fonte_leitura", "label": "Fonte da leitura", "fieldtype": "Data"},
]


def garantir_campos_peca():
    """Campos novos da peça (Custom Field), sem recriar o DocType. Idempotente."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_field
    for campo in CAMPOS_PECA_PRANCHA + CAMPOS_PECA_RASTRO:
        if not frappe.db.exists("Custom Field", {"dt": "Peca Pre-Moldada", "fieldname": campo["fieldname"]}) and                 not frappe.get_meta("Peca Pre-Moldada").has_field(campo["fieldname"]):
            create_custom_field("Peca Pre-Moldada", {**campo, "insert_after": "aviso_engenharia"})


CAMPOS_FORMA = [
    {"fieldname": "ciclo_dias", "label": "Ciclo da forma (dias)", "fieldtype": "Float", "default": "1"},
]


def garantir_campos_forma():
    """Ciclo de cura da forma: a peça ocupa a forma por esse número de dias. Idempotente."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_field
    for campo in CAMPOS_FORMA:
        if not frappe.db.exists("Custom Field", {"dt": "Forma Pista", "fieldname": campo["fieldname"]}) and                 not frappe.get_meta("Forma Pista").has_field(campo["fieldname"]):
            create_custom_field("Forma Pista", {**campo, "insert_after": "giros_limite_manutencao"})


def garantir_doctypes_novos():
    """Cria os documentos que surgiram depois do schema inicial. Idempotente; roda no publicar.sh
    e no provisionamento de cliente novo."""
    _criar_roles()
    for papel in ("Encarregado de Obra",):
        if not frappe.db.exists("Role", papel):
            frappe.get_doc({"doctype": "Role", "role_name": papel, "desk_access": 0}).insert(ignore_permissions=True)
    _criar_doctype("Diario Obra", DIARIO_OBRA)
    _criar_doctype("Rosto Operador", ROSTO_OPERADOR)
    _criar_doctype("Lote Concreto", LOTE_CONCRETO)
    _criar_doctype("Corpo Prova", CORPO_PROVA)
    _criar_doctype("Certificado Aco", CERTIFICADO_ACO)
    _criar_doctype("Revisao Projeto", REVISAO_PROJETO)
    _criar_doctype("Plano Corte", PLANO_CORTE)
    garantir_campos_peca()
    garantir_campos_forma()
    frappe.db.commit()
    frappe.clear_cache()
