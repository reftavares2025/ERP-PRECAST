"""
Percorre as telas do ERPNext que o cliente enxerga e lista os textos que ainda estão em inglês.
Uso: python tests/coletar_textos_desk.py > /tmp/textos.json   (cria o usuário de teste e apaga no fim)
"""
import json
import os
import re
import sys

import requests
from playwright.sync_api import sync_playwright

U = "http://localhost:8088"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EM = "coleta.textos@example.com"
SENHA = "Senha#Coleta2026x"
NEGOCIO = ["Sales User", "Sales Manager", "Sales Master Manager", "Accounts User", "Accounts Manager", "Purchase User", "Purchase Manager", "Purchase Master Manager", "Stock User", "Stock Manager", "Item Manager", "Delivery User", "Delivery Manager", "Fulfillment User", "HR User", "HR Manager", "Report Manager", "Analytics", "Auditor"]

COLETAR = """() => {
  const vistos = new Set();
  const out = [];
  const raiz = document.querySelector('.layout-main, .page-container, body');
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const n = w.currentNode; const t = (n.nodeValue || '').replace(/\\s+/g, ' ').trim();
    const el = n.parentElement;
    if (!t || t.length > 80 || t.length < 3 || !el || el.closest('script,style,noscript')) continue;
    const r = el.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue;
    if (!vistos.has(t)) { vistos.add(t); out.push(t); }
  }
  return out;
}"""


def senha_admin():
    for l in open(os.path.join(RAIZ, "precast_service_credentials.env"), encoding="utf-8"):
        if l.startswith("ADMIN_PASSWORD="):
            return l.split("=", 1)[1].strip()


def main():
    s = requests.Session()
    s.post(U + "/api/method/login", json={"usr": "Administrator", "pwd": senha_admin()})
    s.delete(U + f"/api/resource/User/{EM}")
    s.post(U + "/api/resource/User", json={"email": EM, "first_name": "Coleta", "send_welcome_email": 0, "new_password": SENHA, "roles": [{"role": r} for r in ["Direção"] + NEGOCIO]})
    textos = {}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome")
            ctx = b.new_context(viewport={"width": 1500, "height": 900})
            pg = ctx.new_page()
            ctx.request.post(U + "/api/method/login", data=json.dumps({"usr": EM, "pwd": SENHA}), headers={"Content-Type": "application/json"})
            alvos = ["selling", "crm", "buying", "stock", "invoicing", "payments", "financial-reports", "taxes", "banking", "budget",
                     "expenses", "leaves", "payroll", "shift-&-attendance", "recruitment", "performance", "tenure", "tax-&-benefits",
                     "quotation", "sales-order", "sales-invoice", "customer", "purchase-order", "supplier", "item", "employee",
                     "expense-claim", "leave-application", "payment-entry", "journal-entry", "delivery-note", "stock-entry", "lead", "opportunity"]
            for alvo in alvos:
                try:
                    pg.goto(U + "/desk/" + alvo, wait_until="networkidle")
                    pg.wait_for_timeout(1800)
                    textos[alvo] = pg.evaluate(COLETAR)
                except Exception as e:
                    textos[alvo] = ["ERRO " + str(e)[:60]]
            b.close()
    finally:
        s.delete(U + f"/api/resource/User/{EM}")
    print(json.dumps(textos, ensure_ascii=False))


if __name__ == "__main__":
    main()
