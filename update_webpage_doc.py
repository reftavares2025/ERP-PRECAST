import frappe

def update_web_page():
    html_path = "/home/frappe/frappe-bench/sites/frontend/www/painel.html"
    with open(html_path, 'r', encoding='utf-8') as f:
        new_html = f.read()

    doc = frappe.get_doc('Web Page', 'painel-controle-agil')
    doc.main_section = new_html
    doc.main_section_html = new_html
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    print("Updated Web Page 'painel-controle-agil' successfully!")

if __name__ == '__main__':
    update_web_page()
