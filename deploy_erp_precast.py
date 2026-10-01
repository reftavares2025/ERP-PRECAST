import frappe


def run():
    bench_path = "/home/frappe/frappe-bench"

    # 1. Atualiza a Web Page do app (atras do login) com o novo branding/topbar dinamico
    with open(f"{bench_path}/sites/frontend/www/painel.html", encoding="utf-8") as f:
        app_html = f.read()
    if frappe.db.exists("Web Page", "painel-controle-agil"):
        doc = frappe.get_doc("Web Page", "painel-controle-agil")
        doc.main_section = app_html
        doc.main_section_html = app_html
        doc.save(ignore_permissions=True)
        print("App (painel) atualizado.")
    else:
        print("AVISO: Web Page do app nao encontrada, nao atualizada.")

    # 2. Cria/atualiza a pagina de apresentacao publica (ERP Precast)
    with open(f"{bench_path}/sites/frontend/www/erp-precast-apresentacao.html", encoding="utf-8") as f:
        pres_html = f.read()

    if frappe.db.exists("Web Page", "erp-precast"):
        pdoc = frappe.get_doc("Web Page", "erp-precast")
        pdoc.main_section = pres_html
        pdoc.main_section_html = pres_html
        pdoc.published = 1
        pdoc.save(ignore_permissions=True)
        print("Pagina de apresentacao atualizada.")
    else:
        pdoc = frappe.get_doc({
            "doctype": "Web Page",
            "title": "ERP Precast",
            "route": "erp-precast-apresentacao",
            "published": 1,
            "main_section": pres_html,
            "main_section_html": pres_html,
        })
        pdoc.insert(ignore_permissions=True)
        print("Pagina de apresentacao criada.")

    # 3. Define a pagina de apresentacao como home page publica do site
    frappe.db.set_single_value("Website Settings", "home_page", "erp-precast-apresentacao")
    print("Home page do site definida como erp-precast-apresentacao.")

    frappe.db.commit()
    print("Deploy concluido.")
