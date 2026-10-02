import frappe
from frappe.utils import now_datetime

FASES_NBR9062 = [
    "1. Corte e Dobra de Aço",
    "2. Armação Estrutural",
    "3. Fôrmas & Embutidos",
    "4. Concretagem",
    "5. Cura & Desmolde",
    "6. Acabamento & CQ",
    "7. Expedição & Pátio",
    "8. Execução na Obra"
]

@frappe.whitelist(allow_guest=True)
def bipar_peca(qr_code, operador, nova_fase=None, inspecao_ok=1, observacoes=""):
    """
    Registra a bipagem no chão de fábrica e avança a fase da peça
    """
    if not qr_code or not operador:
        frappe.throw("Código QR e Nome do Operador são obrigatórios.")

    clean_code = qr_code.strip()
    tag = clean_code

    # Se for string formatada TrueQR (Ex: TRUEQR|V-01|OBRA|...)
    if clean_code.startswith("TRUEQR|"):
        parts = clean_code.split("|")
        if len(parts) >= 2:
            tag = parts[1]

    # Localizar a peça no MariaDB
    if not frappe.db.exists("Peca Pre Moldada", tag):
        # Tenta buscar por hash ou tag parcial
        tag_match = frappe.db.get_value("Peca Pre Moldada", {"trueqr_hash": tag}, "tag")
        if tag_match:
            tag = tag_match
        else:
            frappe.throw(f"Peça '{tag}' não localizada no sistema.")

    peca = frappe.get_doc("Peca Pre Moldada", tag)
    fase_anterior = peca.fase_atual or FASES_NBR9062[0]

    # Determinar a próxima fase
    if nova_fase and nova_fase in FASES_NBR9062:
        fase_destino = nova_fase
    else:
        # Avança para a próxima etapa na esteira
        try:
            current_idx = FASES_NBR9062.index(fase_anterior)
            if current_idx < len(FASES_NBR9062) - 1:
                fase_destino = FASES_NBR9062[current_idx + 1]
            else:
                fase_destino = FASES_NBR9062[-1]
        except ValueError:
            fase_destino = FASES_NBR9062[0]

    # Atualizar a peça
    peca.fase_atual = fase_destino
    peca.ultimo_operador = operador
    peca.data_ultimo_bip = now_datetime()
    
    # Atualizar status comercial
    if "Concretagem" in fase_destino:
        peca.status = "Concretada"
    elif "Cura" in fase_destino:
        peca.status = "Em Cura"
    elif "CQ" in fase_destino:
        peca.status = "Aprovada CQ"
    elif "Expedição" in fase_destino:
        peca.status = "No Pátio"
    elif "Obra" in fase_destino:
        peca.status = "Entregue na Obra"
    elif "Armação" in fase_destino:
        peca.status = "Em Armação"
    
    peca.save(ignore_permissions=True)

    # Criar registro de auditoria no DocType Apontamento Rastreabilidade
    apont = frappe.new_doc("Apontamento Rastreabilidade")
    apont.peca = peca.name
    apont.fase = fase_destino
    apont.operador = operador
    apont.data_hora = now_datetime()
    apont.inspecao_aprovada = int(inspecao_ok)
    apont.observacoes = observacoes or f"Avanço de {fase_anterior} para {fase_destino}"
    apont.insert(ignore_permissions=True)

    frappe.db.commit()

    return {
        "status": "success",
        "tag": peca.tag,
        "obra": peca.obra,
        "fase_anterior": fase_anterior,
        "fase_atual": fase_destino,
        "operador": operador,
        "data_hora": peca.data_ultimo_bip.strftime('%d/%m/%Y %H:%M:%S'),
        "volume_m3": peca.volume_m3,
        "peso_t": peca.peso_t
    }

@frappe.whitelist(allow_guest=True)
def get_painel_producao(obra=None):
    """
    Retorna o 'Andar da Carruagem' em tempo real para o painel executivo e terminal
    """
    filters = {}
    if obra:
        filters["obra"] = obra

    todas_pecas = frappe.db.get_all("Peca Pre Moldada", filters=filters, fields=["name", "tag", "obra", "tipo_elemento", "fase_atual", "volume_m3", "peso_t", "ultimo_operador", "data_ultimo_bip"])
    
    funil = []
    for fase in FASES_NBR9062:
        pecas_na_fase = [p for p in todas_pecas if p.fase_atual == fase]
        vol_fase = sum(p.volume_m3 or 0.0 for p in pecas_na_fase)
        peso_fase = sum(p.peso_t or 0.0 for p in pecas_na_fase)
        funil.append({
            "fase": fase,
            "total_pecas": len(pecas_na_fase),
            "volume_m3": round(vol_fase, 3),
            "peso_t": round(peso_fase, 2)
        })

    ultimos_apontamentos = frappe.db.get_all(
        "Apontamento Rastreabilidade",
        fields=["name", "peca", "fase", "operador", "data_hora", "inspecao_aprovada", "observacoes"],
        order_by="data_hora desc",
        limit=10
    )

    return {
        "total_pecas": len(todas_pecas),
        "volume_total_m3": round(sum(p.volume_m3 or 0.0 for p in todas_pecas), 3),
        "peso_total_t": round(sum(p.peso_t or 0.0 for p in todas_pecas), 2),
        "funil": funil,
        "ultimos_apontamentos": ultimos_apontamentos
    }
