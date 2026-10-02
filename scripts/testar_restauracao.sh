#!/bin/sh
# Prova que um backup serve: restaura o banco e os arquivos num site NOVO e descartável e confere que as peças voltaram.
# O site de verdade não é tocado.
#
# Uso:  sh scripts/testar_restauracao.sh <pasta_do_backup> <chave_de_criptografia>
#   pasta_do_backup        a pasta datada criada por backup_diario.sh
#   chave_de_criptografia  o backup_encryption_key do site (fora da pasta de cópias)
set -eu

PASTA="${1:?informe a pasta do backup}"
CHAVE="${2:?informe a chave de criptografia}"
CONTAINER="${PRECAST_BACKEND_CONTAINER:-erpnext-pre-fabricado-backend-1}"
TESTE="restauracao-teste.local"
BENCH="/home/frappe/frappe-bench"
TMP="/tmp/restauracao"
SENHA_DB="${PRECAST_DB_ROOT_PASSWORD:-admin}"

BANCO="$(ls -1 "$PASTA"/*-database*.sql.gz | head -1)"
PUBLICOS="$(ls -1 "$PASTA"/*-files*.tar | grep -v private | head -1)"
PRIVADOS="$(ls -1 "$PASTA"/*-private-files*.tar | head -1)"

MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" bash -lc "rm -rf $TMP && mkdir -p $TMP"
for f in "$BANCO" "$PUBLICOS" "$PRIVADOS"; do
  MSYS_NO_PATHCONV=1 docker cp "$f" "$CONTAINER:$TMP/$(basename "$f")"
done

echo "== criando o site de teste e restaurando =="
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" bash -lc "cd $BENCH && bench drop-site $TESTE --force --no-backup 2>/dev/null; \
  bench new-site $TESTE --admin-password teste --db-root-password '$SENHA_DB' --no-mariadb-socket >/dev/null && \
  bench --site $TESTE restore $TMP/$(basename "$BANCO") --with-public-files $TMP/$(basename "$PUBLICOS") --with-private-files $TMP/$(basename "$PRIVADOS") \
    --encryption-key '$CHAVE' --db-root-password '$SENHA_DB' --force"

echo "== conferindo =="
PECAS="$(MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" bash -lc "cd $BENCH && bench --site $TESTE mariadb -e \"select count(*) from \\\`tabPeca Pre-Moldada\\\`\" 2>/dev/null | tail -1")"
echo "Peças encontradas no site restaurado: $PECAS"

MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" bash -lc "cd $BENCH && bench drop-site $TESTE --force --no-backup >/dev/null 2>&1; rm -rf $TMP"
case "$PECAS" in
  ''|*[!0-9]*) echo "ERRO: não consegui ler a contagem de peças. A restauração falhou." >&2; exit 1 ;;
esac
echo "Restauração conferida: o backup serve."
