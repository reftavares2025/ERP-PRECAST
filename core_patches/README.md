# Patches em arquivos core do Frappe

Estes arquivos vivem dentro da imagem do container (não no volume `sites`),
então **se o container for recriado do zero** (`docker compose up --force-recreate`,
atualização de imagem, `docker compose down` + `up`), essas mudanças somem
e precisam ser reaplicadas. Um `docker restart` normal NÃO apaga isso.

## O que precisa ser reaplicado

1. **`apps/frappe/frappe/www/login.py`** (arquivo completo salvo em
   `frappe_www_login.py` nesta pasta) — redireciona qualquer usuário
   autenticado pra `get_home_page()` em vez de `/desk` (multi-tenant).
   Restaurar com:
   ```
   docker cp core_patches/frappe_www_login.py <container>:/home/frappe/frappe-bench/apps/frappe/frappe/www/login.py
   ```

2. **`apps/frappe/frappe/hooks.py`** — duas linhas:
   - `get_website_user_home_page = "frappe.precast_api.get_website_user_home_page"`
     (perto da linha 26, junto dos outros hooks de website)
   - dentro de `scheduler_events["daily_long"]`, adicionar
     `"frappe.precast_api.backup_diario_com_alerta"` (a lista vem vazia por
     padrão: `"daily_long": []`)

3. **Dependências do PyNFe** — rodar `scripts/install_pynfe_deps.sh`
   (instala libxmlsec1 + pynfe/lxml/xmlsec/signxml no ambiente Python do bench).

4. **`provision_schema.py` e `provision_finalize.py`** (raiz do projeto) —
   copiar de novo pra `apps/frappe/frappe/` (compartilhado por todas as
   sites do bench). Sem isso, `scripts/provisionar_cliente.sh` não funciona
   em nenhum site, nem no de um cliente existente:
   ```
   docker cp provision_schema.py <container>:/home/frappe/frappe-bench/apps/frappe/frappe/provision_schema.py
   docker cp provision_finalize.py <container>:/home/frappe/frappe-bench/apps/frappe/frappe/provision_finalize.py
   ```

5. **Segredos em `site_config.json`** (isso sim sobrevive porque fica no
   volume `sites` — não precisa reaplicar, só conferir que está lá):
   `whatsapp_evolution_url`, `whatsapp_evolution_instance`,
   `whatsapp_evolution_apikey`, `whatsapp_notificar_numero`,
   `focus_nfe_token`, `nfe_metodo`, `nfe_certificado_path`,
   `nfe_certificado_senha`, `nfe_ie`.

## Publicar e testar

- `scripts/publicar.sh [site]` copia a API (`precast_api.py`), o provisionamento, as 4 telas e os
  arquivos estáticos do HRMS, reaplica estes patches se faltarem, reinicia o backend e grava as
  telas no banco (o cliente vê o registro Web Page, não o arquivo). Rode depois de mexer em
  qualquer `.html` ou em `precast_api.py`.
- `tests/e2e_sistema.py` (API + motor CAD), `tests/e2e_ui.py` e `tests/e2e_cotacoes.py` (Chrome)
  e `tests/varredura_botoes.py` (clica em todos os botões) apagam o que criam.
- Vários clientes no mesmo servidor: um site por cliente (`scripts/provisionar_cliente.sh`). O proxy
  escolhe o site pelo domínio (`FRAPPE_SITE_NAME_HEADER: $$host` em `pwd.yml`, o arquivo que sobe a
  stack: `docker compose -f pwd.yml up -d`). Esta máquina atende por `localhost`, `127.0.0.1` e o IP da
  rede através de atalhos em `sites/` (`localhost -> frontend`). Em produção, aponte o domínio de cada
  cliente (DNS + HTTPS) para o servidor e use o domínio como nome do site no provisionamento.
- Rótulos dos módulos no menu do cliente: `scripts/publicar.sh` troca `app_title` de "ERPNext" para
  "ERP Precast" (`apps/erpnext/erpnext/hooks.py`) e de "Frappe HR" para "Recursos Humanos"
  (`apps/hrms/hrms/hooks.py`). Se o container for recriado, rode o `publicar.sh` de novo.
