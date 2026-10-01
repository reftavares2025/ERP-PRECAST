"""
Segunda metade do provisionamento de um cliente novo: cria as 4 Web Pages
(painel, bipar, apresentação pública, portal do cliente), a Company e o
primeiro usuário (assento de Direção) com senha já definida. Roda depois
de `provision_schema.run` numa site que acabou de ser criada — ver
scripts/provisionar_cliente.sh.
"""
import frappe


def publicar_paginas():
    """Publica as 4 telas (Web Pages) a partir de sites/<site>/www. O que o cliente vê
    é o registro no banco, não o arquivo: sempre rode isto depois de trocar um HTML."""
    bench_path = "/home/frappe/frappe-bench"
    site = frappe.local.site

    paginas = [
        ("painel.html", "painel-controle-agil", "painel", "ERP Precast — Controle Ágil"),
        ("bipar.html", "bipar-chao-de-fabrica", "bipar", "ERP Precast — Lançamentos por QR Code"),
        ("erp-precast-apresentacao.html", "erp-precast", "erp-precast-apresentacao", "ERP Precast"),
        ("portal-obra.html", "portal-do-cliente", "portal-obra", "Portal do Cliente"),
        ("diario-obra.html", "diario-de-obra", "diario-obra", "ERP Precast — Diário de Obra"),
    ]
    for filename, webpage_name, route, title in paginas:
        path = f"{bench_path}/sites/{site}/www/{filename}"
        try:
            with open(path, encoding="utf-8") as f:
                html = f.read()
        except FileNotFoundError:
            print(f"AVISO: {filename} não encontrado em sites/{site}/www, pulando.")
            continue
        if frappe.db.exists("Web Page", webpage_name):
            doc = frappe.get_doc("Web Page", webpage_name)
            doc.content_type = "HTML"
            doc.main_section = html
            doc.main_section_html = html
            doc.published = 1
            doc.save(ignore_permissions=True)
        else:
            doc = frappe.get_doc({
                "doctype": "Web Page", "title": title, "route": route,
                "published": 1, "content_type": "HTML", "main_section": html, "main_section_html": html,
            })
            doc.insert(ignore_permissions=True, set_name=webpage_name)
        print(f"Web Page ok: {webpage_name}")

    frappe.db.commit()
    frappe.clear_cache()


# ---------------------------------------------------------------------------
# O que o cliente enxerga no ERPNext por trás do ERP Precast. Só o que é vendido
# fica visível para ele; automação, personalização e configuração técnica ficam
# restritas ao System Manager (a conta do fornecedor, nunca a do cliente).
# ---------------------------------------------------------------------------
ICONES_SO_FORNECEDOR = [
    "Framework", "Frappe Framework", "Organization", "Manufacturing", "Projects", "Quality", "Subcontracting",
    "Assets", "ERPNext Settings", "My Workspaces", "Support", "Pré-Fabricados & NBR 9062", "Subscription",
    "Share Management", "Accounts Setup", "Automation", "Build", "Data", "Email", "Integrations",
    "Printing", "System", "Users", "Website",
]

# Papéis técnicos que o cliente não recebe.
PAPEIS_SO_FORNECEDOR = [
    "System Manager", "Script Manager", "Workspace Manager", "Translator", "Website Manager", "Newsletter Manager",
    "Knowledge Base Contributor", "Knowledge Base Editor", "Support Team", "Academics User", "Maintenance Manager",
    "Maintenance User", "Fleet Manager", "Manufacturing Manager", "Manufacturing User", "Projects Manager",
    "Projects User", "Quality Manager", "Dashboard Manager", "Prepared Report User", "Marketing Manager",
]

# Papéis de negócio dos módulos vendidos: Vendas/CRM, Contabilidade, Compras, Estoque e RH.
PAPEIS_NEGOCIO = [
    "Sales User", "Sales Manager", "Sales Master Manager", "Accounts User", "Accounts Manager", "Purchase User",
    "Purchase Manager", "Purchase Master Manager", "Stock User", "Stock Manager", "Item Manager", "Delivery User",
    "Delivery Manager", "Fulfillment User", "HR User", "HR Manager", "Report Manager", "Analytics", "Auditor",
]


def limpar_arquivos_orfaos(horas=24):
    """Pranchas e QR Codes que nenhuma peça usa mais (obra excluída, leitura antiga) saem do disco.
    Só apaga o que tem mais de `horas`: a prancha de uma importação ainda não gravada precisa continuar visível."""
    import os, time
    raiz = "/home/frappe/frappe-bench/sites/frontend/public/files"
    pecas = frappe.get_all("Peca Pre-Moldada", fields=["name", "prancha_url", "print_url", "prancha_pdf", "prancha_png"])
    usados = {os.path.basename(str(u)) for p in pecas for u in (p.prancha_url, p.print_url, p.prancha_pdf, p.prancha_png) if u}
    codigos = {p.name for p in pecas}
    limite = time.time() - horas * 3600
    removidos = 0
    for pasta, mantem in (("pranchas", lambda f: f in usados), ("qrcodes", lambda f: os.path.splitext(f)[0] in codigos)):
        caminho = os.path.join(raiz, pasta)
        if not os.path.isdir(caminho):
            continue
        for f in os.listdir(caminho):
            arq = os.path.join(caminho, f)
            if os.path.isfile(arq) and not mantem(f) and os.path.getmtime(arq) < limite:
                os.remove(arq)
                removidos += 1
    if removidos:
        print(f"Arquivos órfãos removidos: {removidos}")


def aplicar_marca():
    """Logo, ícone e nome da marca nas telas de entrada (login) e no site."""
    for campo, valor in (("app_logo", "/files/precast_logo.png"), ("favicon", "/files/favicon.png"), ("app_name", "ERP Precast"),
                         ("brand_html", "<img src='/files/precast_logo.png' style='height:28px;margin-right:8px'><b>ERP Precast</b>")):
        if frappe.db.get_single_value("Website Settings", campo) != valor:
            frappe.db.set_single_value("Website Settings", campo, valor)
    frappe.db.set_single_value("Website Settings", "banner_image", "/files/precast_logo.png")
    estilo = ("<style>@font-face{font-family:'Inter';font-weight:100 900;font-display:swap;src:url('/files/inter-latin-wght-normal.woff2') format('woff2');"
              "unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}"
              "body,.btn,input,button{font-family:'Inter',sans-serif!important}"
              ".btn-primary,.btn-login,.btn-primary:hover{background:#2563EB!important;border-color:#2563EB!important;color:#fff!important}"
              "a,.text-muted a{color:#2563EB}.for-login .page-card-head h4,.page-card-head h4{color:#0F172A}</style>")
    frappe.db.set_single_value("Website Settings", "head_html", estilo)


PAPEIS_RH = ["HR User", "HR Manager"]
PAPEIS_SEM_RH = {"Operador de Fábrica", "Encarregado de Obra"}  # operador e encarregado são gratuitos e só veem o chão de fábrica e a obra


def liberar_rh():
    """Todo usuário do sistema (exceto operador e encarregado) recebe os papéis do RH."""
    for email in frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, pluck="name"):
        if email in ("Administrator", "Guest"):
            continue
        usuario = frappe.get_doc("User", email)
        atuais = {r.role for r in usuario.roles}
        if atuais & PAPEIS_SEM_RH:
            continue
        faltam = [p for p in PAPEIS_RH if p not in atuais and frappe.db.exists("Role", p)]
        if faltam:
            for p in faltam:
                usuario.append("roles", {"role": p})
            usuario.save(ignore_permissions=True)
            print(f"RH liberado: {email}")


def remover_links_quebrados():
    """Itens de menu do desk que apontam para um DocType que esta versão não tem somem do menu."""
    for item in frappe.get_all("Workspace Sidebar Item", filters={"link_type": "DocType"}, fields=["name", "link_to", "parent"]):
        if item.link_to and not frappe.db.exists("DocType", item.link_to):
            frappe.db.delete("Workspace Sidebar Item", {"name": item.name})
            print(f"Menu {item.parent}: removido link quebrado para {item.link_to}")


def aplicar_visibilidade():
    """Idempotente. Esconde do cliente o que não é vendido e tira os papéis técnicos de quem tem
    o papel Direção (o dono da empresa). A conta Administrator e quem é só System Manager
    (fornecedor) continuam vendo tudo."""
    # O ícone do RH apontava para /desk/people, página que o HRMS desta versão não tem.
    if frappe.db.exists("Desktop Icon", "Frappe HR"):
        icone_rh = frappe.get_doc("Desktop Icon", "Frappe HR")
        if icone_rh.link != "/desk/employee":
            icone_rh.link = "/desk/employee"
            icone_rh.save(ignore_permissions=True)
    # O RH inteiro fica visível ao cliente (decisão do dono do produto): libera o ícone que já foi restrito.
    if frappe.db.exists("Desktop Icon", "HR Setup"):
        rh = frappe.get_doc("Desktop Icon", "HR Setup")
        if rh.roles:
            rh.set("roles", [])
            rh.save(ignore_permissions=True)
    for nome in ICONES_SO_FORNECEDOR:
        if not frappe.db.exists("Desktop Icon", nome):
            continue
        icone = frappe.get_doc("Desktop Icon", nome)
        if [r.role for r in icone.roles] == ["System Manager"]:
            continue
        icone.set("roles", [{"role": "System Manager"}])
        icone.save(ignore_permissions=True)
        print(f"Ícone restrito ao fornecedor: {nome}")

    aplicar_marca()
    limpar_arquivos_orfaos()
    liberar_rh()
    remover_links_quebrados()
    donos = frappe.get_all("Has Role", filters={"role": "Direção", "parenttype": "User"}, pluck="parent")
    for email in set(donos):
        if email in ("Administrator", "Guest"):
            continue
        usuario = frappe.get_doc("User", email)
        atuais = {r.role for r in usuario.roles}
        alvo = (atuais - set(PAPEIS_SO_FORNECEDOR)) | {p for p in PAPEIS_NEGOCIO if frappe.db.exists("Role", p)}
        if alvo == atuais:
            continue
        usuario.set("roles", [{"role": r} for r in sorted(alvo)])
        usuario.save(ignore_permissions=True)
        print(f"Papéis do cliente ajustados: {email}")
    frappe.db.commit()
    frappe.clear_cache()
    from frappe.precast_traducoes import aplicar_traducoes
    aplicar_traducoes()



def run(empresa="Cliente Teste", email="admin@teste.local", senha=None):
    empresa_nome = empresa
    admin_email = email

    bench_path = "/home/frappe/frappe-bench"
    site = frappe.local.site

    publicar_paginas()

    frappe.db.set_single_value("Website Settings", "home_page", "erp-precast-apresentacao")

    # 2. Empresa
    if not frappe.db.exists("Company", empresa_nome):
        company = frappe.get_doc({
            "doctype": "Company", "company_name": empresa_nome, "default_currency": "BRL", "country": "Brazil",
        })
        company.insert(ignore_permissions=True)
        print(f"Company criada: {empresa_nome}")
    frappe.db.set_single_value("Global Defaults", "default_company", empresa_nome)

    # 3. Admin (assento de Direção)
    if not frappe.db.exists("User", admin_email):
        user = frappe.get_doc({
            "doctype": "User", "email": admin_email, "first_name": empresa_nome.split()[0],
            "send_welcome_email": 0, "user_type": "System User",
        })
        user.append("roles", {"role": "Direção"})
        user.insert(ignore_permissions=True)
        print(f"Usuário admin criado: {admin_email}")

    if not frappe.db.exists("Assento", {"user": admin_email}):
        frappe.get_doc({
            "doctype": "Assento", "user": admin_email, "setor": "Direção", "ativo": 1,
            "incluido_no_plano": 1, "data_ativacao": frappe.utils.now_datetime(),
        }).insert(ignore_permissions=True)
        print("Assento de Direção criado.")

    if senha:
        from frappe.utils.password import update_password
        update_password(admin_email, senha)
        print("Senha do admin definida.")

    frappe.db.commit()
    frappe.clear_cache()
    aplicar_visibilidade()
    print("Provisionamento finalizado.")
