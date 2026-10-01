#!/bin/sh
# Reaplica os patches em arquivos core do Frappe que vivem dentro do
# container (perdidos se o container for recriado do zero). Idempotente -
# pode rodar de novo sem duplicar nada. Ver core_patches/README.md.
set -e

CONTAINER=erpnext-pre-fabricado-backend-1
HOOKS=/home/frappe/frappe-bench/apps/frappe/frappe/hooks.py
LOGIN=/home/frappe/frappe-bench/apps/frappe/frappe/www/login.py

# 1. login.py - restaura o arquivo inteiro (customizado)
docker cp "$(dirname "$0")/../core_patches/frappe_www_login.py" "$CONTAINER:$LOGIN"

# 2. hooks.py - home page multi-tenant
if ! docker exec "$CONTAINER" grep -q "get_website_user_home_page" "$HOOKS"; then
  docker exec "$CONTAINER" sed -i \
    '/^page_js = {"setup-wizard"/a\
\
# Multi-tenant: destino do login para qualquer usuario autenticado\
# (evita cair de volta na home page publica, que aponta pra apresentacao).\
get_website_user_home_page = "frappe.precast_api.get_website_user_home_page"' \
    "$HOOKS"
fi

# 3. hooks.py - backup diario
if ! docker exec "$CONTAINER" grep -q "backup_diario_com_alerta" "$HOOKS"; then
  docker exec "$CONTAINER" sed -i \
    's/"daily_long": \[\],/"daily_long": [\n\t\t"frappe.precast_api.backup_diario_com_alerta",\n\t],/' \
    "$HOOKS"
fi

# 4. dependencias do PyNFe
sh "$(dirname "$0")/install_pynfe_deps.sh"

docker restart "$CONTAINER"
echo "Patches core reaplicados."
