import frappe

def set_pt_br():
    # 1. System Settings
    sys_settings = frappe.get_single("System Settings")
    sys_settings.language = "pt-BR"
    sys_settings.country = "Brazil"
    sys_settings.currency = "BRL"
    sys_settings.time_zone = "America/Sao_Paulo"
    sys_settings.date_format = "dd/mm/yyyy"
    sys_settings.time_format = "HH:mm:ss"
    sys_settings.number_format = "#.###,##"
    sys_settings.save(ignore_permissions=True)
    
    # 2. User Administrator
    admin = frappe.get_doc("User", "Administrator")
    admin.language = "pt-BR"
    admin.save(ignore_permissions=True)
    
    frappe.db.commit()
    print("✅ Idioma Português (Brasil), Moeda BRL (R$) e Fuso Horário configurados com sucesso no ERPNext!")

if __name__ == "__main__":
    pass
