#!/usr/bin/env bash
#
# Démarre la stack POC et attend que l'application réponde.
# Les migrations Prisma sont appliquées par l'entrypoint de l'image officielle
# au premier démarrage : rien à lancer à la main, rien de concurrent.

set -euo pipefail

POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$POC_DIR"

[[ -f .env ]] || { echo "Lancer d'abord ./scripts/00-generate-secrets.sh"; exit 1; }
[[ -f certs/cert.p12 ]] || { echo "Lancer d'abord ./scripts/01-generate-certificate.sh"; exit 1; }

docker compose up -d

echo "Démarrage en cours. Premier lancement : compter quelques minutes"
echo "(migrations Prisma sur une base vierge)."

for i in $(seq 1 90); do
  if curl -fsS http://localhost:3000/api/health >/dev/null 2>&1; then
    echo
    echo "Documenso répond."
    echo "  Application : http://localhost:3000"
    echo "  Boîte mail  : http://localhost:8025"
    echo
    echo "Créez votre compte de test, puis récupérez le lien de vérification"
    echo "dans la boîte mail ci-dessus."
    exit 0
  fi
  printf '.'
  sleep 5
done

echo
echo "Pas de réponse sur /api/health après 7 minutes. Journaux :"
echo "  docker compose -f $POC_DIR/compose.yml logs documenso"
exit 1
