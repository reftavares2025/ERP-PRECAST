#!/bin/sh
# Instala as dependencias do caminho PyNFe (NF-e direto na SEFAZ, sem
# gateway) dentro do container do backend. So precisa rodar de novo se o
# container for recriado (docker compose down/up, atualizacao de imagem) -
# um `docker restart` normal preserva o que ja foi instalado.
set -e

CONTAINER=erpnext-pre-fabricado-backend-1

docker exec -u root "$CONTAINER" bash -c \
  "apt-get update -qq && apt-get install -y -qq libxmlsec1-dev libxmlsec1-openssl pkg-config libxml2-dev python3-dev build-essential"

docker exec "$CONTAINER" bash -c \
  "cd /home/frappe/frappe-bench && ./env/bin/pip install --no-cache-dir lxml xmlsec pynfe signxml"

echo "PyNFe pronto. Ative com: docker exec $CONTAINER bench --site frontend set-config nfe_metodo pynfe"
