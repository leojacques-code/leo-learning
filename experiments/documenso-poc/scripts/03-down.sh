#!/usr/bin/env bash
#
# Arrête la stack POC en CONSERVANT les données (comptes, templates, documents).
# Pour tout détruire, voir 99-purge.sh.

set -euo pipefail

POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$POC_DIR"

docker compose down

echo "Stack arrêtée. Le volume documenso-poc-db est conservé :"
echo "./scripts/02-up.sh redémarre le POC avec vos données intactes."
