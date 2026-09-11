#!/usr/bin/env bash
#
# SUPPRESSION COMPLÈTE DU POC.
#
# Opération IRRÉVERSIBLE. Détruit la base et donc les comptes, templates,
# documents et PDF signés du POC. Demande une confirmation explicite.

set -euo pipefail

POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$POC_DIR"

echo "Cette opération va supprimer définitivement :"
echo
echo "  - les conteneurs documenso-poc-app, documenso-poc-db, documenso-poc-mail"
echo "  - le volume documenso-poc-db, soit TOUTES les données du POC"
echo "    (comptes, templates, documents, PDF signés)"
echo "  - le réseau documenso-poc_default"
echo
echo "NE SONT PAS touchés par ce script, à supprimer à la main si souhaité :"
echo "  - $POC_DIR/.env (secrets)"
echo "  - $POC_DIR/certs/cert.p12 (certificat)"
echo "  - $POC_DIR/test-templates/ (vos PDF de test)"
echo "  - les images Docker téléchargées"
echo
echo "C'est IRRÉVERSIBLE. Il n'y a pas de sauvegarde."
echo

read -r -p 'Taper exactement SUPPRIMER pour confirmer : ' answer
if [[ "$answer" != "SUPPRIMER" ]]; then
  echo "Annulé. Rien n'a été supprimé."
  exit 1
fi

docker compose down -v --remove-orphans

echo
echo "POC supprimé."
echo "Pour retirer aussi les secrets et le certificat :"
echo "  rm -f $POC_DIR/.env $POC_DIR/certs/cert.p12"
