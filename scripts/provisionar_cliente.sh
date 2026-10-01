#!/bin/sh
# Provisiona um cliente novo do zero, de ponta a ponta, num unico comando:
# site novo + apps + schema customizado + telas + empresa + admin com senha.
#
# Uso:
#   scripts/provisionar_cliente.sh <dominio-do-site> "<Nome da Empresa>" <email-admin> <senha-admin>
#
# Exemplo:
#   scripts/provisionar_cliente.sh precast-silva.local "Silva Pré-Moldados LTDA" contato@silva.com.br "SenhaForte#2026"
#
# Pre-requisito: precast_api.py, provision_schema.py, provision_finalize.py e precast_traducoes.py ja
# tem que estar copiados pra dentro de apps/frappe/frappe/ no container
# (sao compartilhados por todas as sites do bench, entao normalmente ja
# estao la de uma rodada anterior - só reaplicar se o container foi
# recriado do zero, ver core_patches/README.md).
set -e
export MSYS_NO_PATHCONV=1  # Git Bash no Windows não deve reescrever caminhos do container

if [ -z "$4" ]; then
  echo "Uso: $0 <dominio-do-site> \"<Nome da Empresa>\" <email-admin> <senha-admin>"
  exit 1
fi

SITE=$1
EMPRESA=$2
ADMIN_EMAIL=$3
ADMIN_SENHA=$4
CONTAINER=erpnext-pre-fabricado-backend-1
DIR="$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })"
DB_ROOT_PASSWORD=$(grep '^DB_PASSWORD=' "$DIR/.env" | cut -d= -f2-)

echo "== 1/6: criando site $SITE =="
docker exec "$CONTAINER" bench new-site "$SITE" --mariadb-root-password "$DB_ROOT_PASSWORD" --admin-password "$ADMIN_SENHA"

echo "== 2/6: instalando ERPNext =="
docker exec "$CONTAINER" bench --site "$SITE" install-app erpnext

echo "== 3/6: instalando HRMS =="
docker exec "$CONTAINER" bench --site "$SITE" install-app hrms

echo "== 4/6: copiando telas (Web Pages) =="
docker exec "$CONTAINER" mkdir -p "/home/frappe/frappe-bench/sites/$SITE/www"
for f in painel.html bipar.html erp-precast-apresentacao.html portal-obra.html diario-obra.html; do
  docker exec -u root -i "$CONTAINER" bash -c "cat > /home/frappe/frappe-bench/sites/$SITE/www/$f && chown frappe:frappe /home/frappe/frappe-bench/sites/$SITE/www/$f" < "$DIR/$f"
done

echo "== 5/6: criando schema customizado (doctypes + papeis de setor) =="
docker exec "$CONTAINER" bench --site "$SITE" execute frappe.provision_schema.run

echo "== 6/6: criando empresa, admin (Direção) e publicando as telas =="
docker exec "$CONTAINER" bench --site "$SITE" execute frappe.provision_finalize.run --kwargs "{\"empresa\": \"$EMPRESA\", \"email\": \"$ADMIN_EMAIL\", \"senha\": \"$ADMIN_SENHA\"}"

echo ""
echo "Pronto. Cliente '$EMPRESA' provisionado em '$SITE'."
echo "Login: $ADMIN_EMAIL"
echo ""
echo "Falta configurar por cliente (fora deste script):"
echo "  - Certificado NF-e (nfe_certificado_path / nfe_certificado_senha / nfe_ie)"
echo "  - WhatsApp desse cliente (whatsapp_evolution_*), se ele quiser notificacao propria"
echo "  - Apontar o dominio real (DNS + HTTPS) pra esse site"
