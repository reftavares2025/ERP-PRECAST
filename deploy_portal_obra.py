import frappe


def run():
    with open("/home/frappe/frappe-bench/sites/frontend/www/portal-obra.html", encoding="utf-8") as f:
        html = f.read()

    webpage_name = frappe.db.exists("Web Page", {"route": "portal-obra"}) or frappe.db.exists("Web Page", "portal-do-cliente") or frappe.db.exists("Web Page", "portal-obra")
    if webpage_name:
        doc = frappe.get_doc("Web Page", webpage_name)
        doc.main_section = html
        doc.main_section_html = html
        doc.content_type = "HTML"
        doc.published = 1
        doc.save(ignore_permissions=True)
        print(f"Portal do Cliente ({webpage_name}) atualizado.")
    else:
        doc = frappe.get_doc({
            "doctype": "Web Page", "title": "Portal do Cliente", "route": "portal-obra",
            "published": 1, "content_type": "HTML", "main_section": html, "main_section_html": html,
        })
        doc.insert(ignore_permissions=True, set_name="portal-obra")
        print("Portal do Cliente criado.")

    frappe.db.commit()
