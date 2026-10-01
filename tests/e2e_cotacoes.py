"""
Cotações do dia no Chrome: editar valor, adicionar matéria-prima, salvar e excluir.
Restaura o estado original no fim. Uso: python tests/e2e_cotacoes.py
"""
import json
import os
import sys

import requests
from playwright.sync_api import sync_playwright

U = "http://localhost:8088"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok_geral = []


def checar(nome, ok, detalhe=""):
    ok_geral.append(bool(ok))
    print(("  OK    " if ok else "  FALHA "), nome, ("- " + str(detalhe)[:140]) if detalhe else "")


def senha():
    for l in open(os.path.join(RAIZ, "precast_service_credentials.env"), encoding="utf-8"):
        if l.startswith("ADMIN_PASSWORD="):
            return l.split("=", 1)[1].strip()


def main():
    pw = senha()
    erros = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        ctx = b.new_context(viewport={"width": 1600, "height": 900})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: erros.append(e.message))
        pg.on("dialog", lambda d: d.accept())
        ctx.request.post(U + "/api/method/login", data=json.dumps({"usr": "Administrator", "pwd": pw}), headers={"Content-Type": "application/json"})
        pg.goto(U + "/painel", wait_until="networkidle")
        pg.wait_for_timeout(1200)
        pg.click(".tab-cotacoes")
        pg.wait_for_selector("#cotacoesTableBody tr")
        pg.wait_for_timeout(1500)

        linhas = pg.locator("#cotacoesTableBody tr").count()
        checar("tabela de matérias-primas carregou", linhas >= 8, f"{linhas} linhas")
        checar("Aço CA-50 e cimento CP-II protegidos (sem botão excluir)", pg.locator('tr[data-nome="Aço CA-50"] button').count() == 0 and pg.locator('tr[data-nome="Cimento CP-II"] button').count() == 0)

        print("[editar e salvar]")
        linha = pg.locator('tr[data-nome="Aço CA-60"]')
        linha.locator(".cot-valor").fill("2.91")
        linha.locator(".cot-obs").fill("Fornecedor teste UI")
        checar("linha editada fica marcada", linha.get_attribute("data-editada") == "1")
        checar("botão avisa que há alterações", "alterações" in pg.locator("#btnSalvarCotacoes").inner_text())
        pg.click("#btnSalvarCotacoes")
        pg.wait_for_timeout(2500)
        checar("mensagem de salvo", "salva" in pg.locator("#cotStatus").inner_text(), pg.locator("#cotStatus").inner_text())
        checar("valor salvo aparece depois de recarregar a tabela", pg.locator('tr[data-nome="Aço CA-60"] .cot-valor').input_value() == "2.91")
        checar("situação vira 'Do dia'", "Do dia" in pg.locator('tr[data-nome="Aço CA-60"]').inner_text())

        print("[adicionar matéria-prima]")
        pg.click("text=Adicionar matéria-prima")
        pg.fill("#cotNovoNome", "Desmoldante UI")
        pg.select_option("#cotNovoUnidade", "unidade")
        pg.fill("#cotNovoValor", "12.5")
        pg.click("text=✓ Adicionar")
        pg.wait_for_timeout(2500)
        nova = pg.locator('tr[data-nome="Desmoldante UI"]')
        checar("matéria-prima nova aparece na tabela", nova.count() == 1)
        checar("com o valor informado", nova.locator(".cot-valor").input_value() == "12.5")
        pg.click("text=Adicionar matéria-prima")
        pg.fill("#cotNovoNome", "desmoldante ui")
        pg.click("text=✓ Adicionar")
        pg.wait_for_timeout(1500)
        checar("nome repetido é recusado", "já está" in pg.locator("#cotStatus").inner_text(), pg.locator("#cotStatus").inner_text())

        print("[excluir]")
        nova.locator("button").click()
        pg.wait_for_timeout(2500)
        checar("matéria-prima extra some da tabela", pg.locator('tr[data-nome="Desmoldante UI"]').count() == 0)
        pg.locator('tr[data-nome="Terra"] button').click()
        pg.wait_for_timeout(2500)
        checar("matéria-prima padrão sai da lista", pg.locator('tr[data-nome="Terra"]').count() == 0)
        checar("sem erros de JavaScript", not erros, erros)
        b.close()

    # restaura: Terra volta, Aço CA-60 sem o lançamento de teste
    s = requests.Session()
    s.post(U + "/api/method/login", json={"usr": "Administrator", "pwd": pw})
    s.post(U + "/api/method/frappe.precast_api.adicionar_insumo", json={"nome": "Terra", "unidade": "kg"})
    import datetime
    filtros = [["lancado_por", "=", "Administrator"], ["fonte", "=", "Manual"], ["data", "=", datetime.date.today().isoformat()]]
    for c in s.get(U + "/api/resource/Cotacao Insumo", params={"filters": json.dumps(filtros), "limit": 100}).json().get("data", []):
        s.delete(U + f"/api/resource/Cotacao Insumo/{c['name']}")
    print(f"\n{sum(ok_geral)}/{len(ok_geral)} verificações ok")
    sys.exit(0 if all(ok_geral) else 1)


if __name__ == "__main__":
    main()
