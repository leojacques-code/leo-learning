#!/usr/bin/env bash
#
# Arrêt / rollback du POC Documenso sur Oracle Cloud.
#
# Arrête Caddy, Documenso, Mailpit, PostgreSQL et le récepteur de webhooks.
# LES DONNÉES SONT CONSERVÉES : aucun volume n'est supprimé, ni ici ni par
# accident. `docker compose down -v` n'est jamais appelé par ce script.
#
# Pour tout détruire, il faut le vouloir explicitement : scripts/99-purge.sh,
# qui demande de taper SUPPRIMER. Il n'est jamais lancé automatiquement.
#
# Usage :
#   ./oracle-stop.sh          arrête la pile
#   ./oracle-stop.sh --start  la relance
#   ./oracle-stop.sh --status état courant

set -euo pipefail

POC_STATE_DIR=/opt/documenso-poc
POC_SRC_DIR=/opt/leo-learning/experiments/documenso-poc

dc() {
  docker compose \
    --project-directory "$POC_SRC_DIR" \
    --env-file "$POC_STATE_DIR/.env" \
    --env-file "$POC_STATE_DIR/oracle.env" \
    -f "$POC_SRC_DIR/compose.yml" \
    -f "$POC_SRC_DIR/compose.oracle.yml" \
    "$@"
}

case "${1:-stop}" in
  --start|start)
    echo "[oracle-stop] relance de la pile"
    dc up -d
    ;;
  --status|status)
    dc ps
    ;;
  stop|--stop)
    echo "[oracle-stop] arrêt de la pile, volumes conservés"
    dc down
    echo
    echo "Conteneurs arrêtés. Volumes intacts :"
    docker volume ls --filter name=documenso-poc --format '  {{.Name}}'
    echo
    echo "Relancer : $0 --start"
    ;;
  *)
    echo "Usage : $0 [stop|--start|--status]" >&2
    exit 1
    ;;
esac
