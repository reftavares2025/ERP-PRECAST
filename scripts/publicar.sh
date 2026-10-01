#!/bin/sh
# Publica tudo que mudou no projeto para o site em execução, num comando só:
# API (precast_api.py), provisionamento, patches do Frappe, arquivos estáticos do
# HRMS e as 4 telas (Web Pages). O cliente vê o registro Web Page do banco, não o
# arquivo .html, então copiar o arquivo sozinho não muda nada na tela.
#
# Uso:  scripts/publicar.sh [site]        (padrão: frontend)
set -e
export MSYS_NO_PATHCONV=1

SITE=${1:-frontend}
BACKEND=erpnext-pre-fabricado-backend-1
FRONTEND=erpnext-pre-fabricado-frontend-1
DIR="$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })"
BENCH=/home/frappe/frappe-bench

echo "== 1/6: API e provisionamento =="
for f in precast_api.py provision_schema.py provision_finalize.py precast_traducoes.py precast_suporte.py precast_fiscal.py precast_padrao_cad.py precast_traducoes_auto.py precast_traducoes_geradas.json precast_rosto.py precast_qualidade.py; do
  docker cp "$DIR/$f" "$BACKEND:$BENCH/apps/frappe/frappe/$f"
done

echo "== 2/6: patches do Frappe (login, hooks, backup) =="
HOOKS=$BENCH/apps/frappe/frappe/hooks.py
if docker exec "$BACKEND" grep -q "frappe.precast_api.get_website_user_home_page" "$HOOKS"    && docker exec "$BACKEND" grep -q "backup_diario_com_alerta" "$HOOKS"; then
  echo "já aplicados"
else
  (cd "$DIR" && sh scripts/apply_core_patches.sh)
fi

# Nome dos módulos que aparece no menu do cliente (idempotente; some se o container for recriado).
docker exec "$BACKEND" sed -i 's/^app_title = "ERPNext"/app_title = "ERP Precast"/' "$BENCH/apps/erpnext/erpnext/hooks.py"
docker exec "$BACKEND" sed -i 's/^app_title = "Frappe HR"/app_title = "Recursos Humanos"/' "$BENCH/apps/hrms/hrms/hooks.py"
docker exec "$BACKEND" sed -i 's/"title": "Frappe HR"/"title": "Recursos Humanos"/' "$BENCH/apps/hrms/hrms/hooks.py"
docker exec "$BACKEND" sed -i 's/"title": "ERPNext"/"title": "ERP Precast"/' "$BENCH/apps/erpnext/erpnext/hooks.py"
# O HRMS aponta para /desk/people, página que esta versão não tem; a entrada do RH abre a lista de colaboradores.
docker exec "$BACKEND" sed -i "s#/desk/people#/desk/employee#g" "$BENCH/apps/hrms/hrms/hooks.py"

echo "== 3/6: telas para sites/$SITE/www =="
docker exec "$BACKEND" mkdir -p "$BENCH/sites/$SITE/www"
for f in painel.html bipar.html erp-precast-apresentacao.html portal-obra.html diario-obra.html; do
  docker cp "$DIR/$f" "$BACKEND:$BENCH/sites/$SITE/www/$f"
done

echo "== marca: logo, ícone e fonte Inter =="
for f in brand/precast_logo.png brand/favicon.png brand/precast_icon.png brand/inter-latin-wght-normal.woff2 brand/inter-latin-ext-wght-normal.woff2; do
  docker cp "$DIR/$f" "$BACKEND:$BENCH/sites/$SITE/public/files/$(basename "$f")"
done
docker exec "$BACKEND" mkdir -p "$BENCH/sites/$SITE/public/files/face"
docker cp "$DIR/brand/face/." "$BACKEND:$BENCH/sites/$SITE/public/files/face/"
docker exec -u root "$BACKEND" chown -R frappe:frappe "$BENCH/sites/$SITE/public/files"

echo "== 4/6: arquivos estáticos (CSS/JS/imagens) no servidor web =="
# O proxy serve /assets do próprio container; se ele for recriado, volta com um pacote incompleto
# (telas sem estilo, login sem JavaScript). Copia o pacote completo do backend, resolvendo os atalhos.
docker exec "$BACKEND" tar -C "$BENCH" -chf - assets | docker exec -i -u root "$FRONTEND" tar -C "$BENCH" -xf -

echo "== 5/6: reiniciando o backend =="
docker restart "$BACKEND" >/dev/null
i=0
until [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8088/api/method/ping)" = "200" ]; do
  i=$((i+1)); [ "$i" -gt 60 ] && { echo "backend não voltou em 2 minutos"; exit 1; }
  sleep 2
done

echo "== 6/6: publicando as telas, aplicando a visibilidade do cliente e limpando o cache =="
docker exec -w "$BENCH" "$BACKEND" bench --site "$SITE" execute frappe.provision_schema.garantir_doctypes_novos
docker exec -w "$BENCH" "$BACKEND" bench --site "$SITE" execute frappe.provision_finalize.publicar_paginas
docker exec -w "$BENCH" "$BACKEND" bench --site "$SITE" execute frappe.provision_finalize.aplicar_visibilidade
docker exec -w "$BENCH" "$BACKEND" bench --site "$SITE" clear-website-cache

echo "Pronto. Faça Ctrl+Shift+R no navegador."
