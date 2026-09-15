#!/usr/bin/env bash
#
# Restauration du POC Documenso depuis une sauvegarde.
#
# JAMAIS LANCÉ AUTOMATIQUEMENT. Ni le workflow GitHub Actions, ni deploy.sh, ni
# aucun autre script de ce dépôt n'appelle celui-ci. Il s'exécute à la main,
# en connaissance de cause, et demande une confirmation explicite.
#
# Il ÉCRASE la base courante. Toute donnée créée depuis la sauvegarde est
# perdue.
#
# Usage :
#   ./oracle-restore.sh                     liste les sauvegardes disponibles
#   ./oracle-restore.sh 20260915T101500Z    restaure celle-ci

set -euo pipefail

POC_STATE_DIR=/opt/documenso-poc
POC_SRC_DIR=/opt/leo-learning/experiments/documenso-poc
BACKUP_ROOT=/var/backups/documenso-poc

dc() {
  docker compose \
    --project-directory "$POC_SRC_DIR" \
    --env-file "$POC_STATE_DIR/.env" \
    --env-file "$POC_STATE_DIR/oracle.env" \
    -f "$POC_SRC_DIR/compose.yml" \
    -f "$POC_SRC_DIR/compose.oracle.yml" \
    "$@"
}

if [[ $# -eq 0 ]]; then
  echo "Sauvegardes disponibles dans $BACKUP_ROOT :"
  find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d -printf '  %f\n' | sort
  echo
  echo "Usage : $0 <horodatage>"
  exit 0
fi

SRC="$BACKUP_ROOT/$1"
[[ -d "$SRC" ]] || { echo "Sauvegarde introuvable : $SRC" >&2; exit 1; }
[[ -f "$SRC/documenso_poc.dump" ]] || { echo "Dump absent de $SRC" >&2; exit 1; }

echo "Manifeste de la sauvegarde :"
sed 's/^/  /' "$SRC/MANIFEST.txt"
echo
echo "Cette opération va :"
echo "  - arrêter Documenso"
echo "  - ÉCRASER la base documenso_poc par le contenu de la sauvegarde"
echo "  - toute donnée créée après $1 sera DÉFINITIVEMENT perdue"
echo
echo "Le .env et le certificat NE sont PAS restaurés automatiquement : si vous"
echo "en avez besoin, ils sont dans $SRC (env.backup, cert.p12) et doivent être"
echo "recopiés à la main, après avoir vérifié qu'ils correspondent bien à ce dump."
echo "Restaurer un dump avec un NEXT_PRIVATE_ENCRYPTION_KEY différent rendrait"
echo "les données chiffrées illisibles."
echo

read -r -p 'Taper exactement RESTAURER pour confirmer : ' answer
[[ "$answer" == "RESTAURER" ]] || { echo "Annulé. Rien n'a été modifié."; exit 1; }

echo "[restore] arrêt de l'application"
dc stop documenso

echo "[restore] restauration de la base"
docker exec -i documenso-poc-db \
  pg_restore -U documenso -d documenso_poc --clean --if-exists --no-owner \
  < "$SRC/documenso_poc.dump"

echo "[restore] redémarrage de l'application"
dc up -d documenso

echo "[restore] terminé. Vérifier l'état :"
echo "  curl -s http://127.0.0.1:3000/api/health"
