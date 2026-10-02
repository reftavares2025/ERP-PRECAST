#!/bin/sh
# Backup completo do site (banco e arquivos) com rodízio. Pode ser agendado todo dia.
#
# Uso:  sh scripts/backup_diario.sh [pasta_de_destino] [dias_guardados]
#   pasta_de_destino  onde guardar as cópias (padrão: ./backups)
#   dias_guardados    quantos dias de cópia manter (padrão: 14)
#
# Se a variável BACKUP_RCLONE_DESTINO existir (por exemplo "b2:minha-empresa/erp"), as cópias também são enviadas
# para lá com o rclone (Backblaze B2, Google Drive, OneDrive, R2...). O backup do Frappe já sai criptografado;
# a chave (backup_encryption_key do site_config) fica fora da pasta de cópias: guarde-a em outro lugar.
set -eu

DESTINO="${1:-./backups}"
DIAS="${2:-14}"
CONTAINER="${PRECAST_BACKEND_CONTAINER:-erpnext-pre-fabricado-backend-1}"
SITE="${PRECAST_SITE:-frontend}"
PASTA_NO_CONTAINER="/home/frappe/frappe-bench/sites/$SITE/private/backups"
CARIMBO="$(date +%Y-%m-%d_%H%M)"
SAIDA="$DESTINO/$CARIMBO"

mkdir -p "$SAIDA"
echo "== gerando o backup do site $SITE =="
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" bash -lc "cd /home/frappe/frappe-bench && bench --site $SITE backup --with-files" > "$SAIDA/saida_do_backup.txt"

echo "== copiando os arquivos novos para $SAIDA =="
NOVOS="$(MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" bash -lc "ls -1t $PASTA_NO_CONTAINER | head -4")"
for f in $NOVOS; do
  MSYS_NO_PATHCONV=1 docker cp "$CONTAINER:$PASTA_NO_CONTAINER/$f" "$SAIDA/$f"
done

if [ "$(ls -1 "$SAIDA" | grep -c -E 'database|files|site_config')" -lt 3 ]; then
  echo "ERRO: o backup não gerou o banco, os arquivos e a configuração." >&2
  exit 1
fi

echo "== apagando cópias com mais de $DIAS dias =="
find "$DESTINO" -maxdepth 1 -mindepth 1 -type d -mtime +"$DIAS" -exec rm -rf {} \;

if [ -n "${BACKUP_RCLONE_DESTINO:-}" ]; then
  echo "== enviando para $BACKUP_RCLONE_DESTINO =="
  rclone copy "$SAIDA" "$BACKUP_RCLONE_DESTINO/$CARIMBO"
fi

echo "Pronto: $SAIDA"
du -sh "$SAIDA"
