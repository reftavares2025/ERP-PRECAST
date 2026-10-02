import frappe

def set_limits():
    # 1. System Settings
    sys_settings = frappe.get_single("System Settings")
    sys_settings.max_file_size = 500  # 500 MB
    sys_settings.save(ignore_permissions=True)
    
    # 2. Site Config
    frappe.conf.max_file_size = 524288000  # 500 MB em bytes
    
    frappe.db.commit()
    print("✅ Limite de Upload do ERPNext aumentado para 500 MB no System Settings e Site Config!")

if __name__ == "__main__":
    pass
