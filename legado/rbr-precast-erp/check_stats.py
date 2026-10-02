import frappe

def check_stats():
    total = frappe.db.count("Peca Pre Moldada")
    pecas = frappe.db.get_all("Peca Pre Moldada", fields=["tag", "tipo_elemento", "volume_m3", "peso_t", "fase_atual"], limit=5)
    vol_total = sum(frappe.db.get_all("Peca Pre Moldada", pluck="volume_m3"))
    peso_total = sum(frappe.db.get_all("Peca Pre Moldada", pluck="peso_t"))
    
    print("=" * 60)
    print(f"📊 DADOS OFICIAIS DENTRO DO ERPNEXT:")
    print(f"Total de Peças Cadastradas: {total}")
    print(f"Volume Total: {vol_total:.3f} m³")
    print(f"Peso Total NBR 9062: {peso_total:.2f} t")
    print("=" * 60)
    print("Amostra das 5 primeiras peças:")
    for p in pecas:
        print(f" - {p.tag}: {p.tipo_elemento} | Vol: {p.volume_m3}m³ | Peso: {p.peso_t}t | Fase: {p.fase_atual}")
    print("=" * 60)
