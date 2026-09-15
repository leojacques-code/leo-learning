#!/usr/bin/env bash
#
# Test de persistance du POC Documenso.
#
# Inventorie les données, redémarre la pile, réinventorie, compare. Puis fait
# la même chose avec un arrêt complet suivi d'une relance, ce qui est un test
# plus dur qu'un simple `restart`.
#
# `docker compose down -v` n'est JAMAIS appelé : les volumes ne sont pas
# touchés. Le script échoue plutôt que de supprimer quoi que ce soit.

set -uo pipefail

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

inventory() {
  python3 "$POC_SRC_DIR/oracle/seed.py" --base http://127.0.0.1:3000 --inventory-only
}

wait_healthy() {
  for _ in $(seq 1 90); do
    curl -fsS --max-time 5 http://127.0.0.1:3000/api/health >/dev/null 2>&1 && return 0
    sleep 5
  done
  return 1
}

echo "[persistance] inventaire avant"
BEFORE="$(inventory)"
printf '%s\n' "$BEFORE" | sed 's/^/  /'

echo "[persistance] docker compose restart"
dc restart >/dev/null
wait_healthy || { echo "[persistance] ECHEC : l'application ne repart pas après restart"; exit 1; }

AFTER_RESTART="$(inventory)"
if [[ "$(printf '%s' "$BEFORE" | jq -S 'del(.mails)')" == "$(printf '%s' "$AFTER_RESTART" | jq -S 'del(.mails)')" ]]; then
  echo "[persistance] OK : inventaire identique après restart"
else
  echo "[persistance] ECHEC : inventaire différent après restart"
  printf '%s\n' "$AFTER_RESTART" | sed 's/^/  /'
  exit 1
fi

echo "[persistance] arrêt complet (down, SANS -v) puis relance"
dc down >/dev/null
dc up -d >/dev/null
wait_healthy || { echo "[persistance] ECHEC : l'application ne repart pas après down/up"; exit 1; }

AFTER_CYCLE="$(inventory)"
# Les données Documenso doivent être strictement identiques. Le nombre de
# courriels est écarté de la comparaison : Mailpit a bien un volume, mais son
# compteur peut bouger si un job de relance part pendant le cycle.
if [[ "$(printf '%s' "$BEFORE" | jq -S 'del(.mails)')" == "$(printf '%s' "$AFTER_CYCLE" | jq -S 'del(.mails)')" ]]; then
  echo "[persistance] OK : inventaire identique après down/up"
  printf '%s\n' "$AFTER_CYCLE" | sed 's/^/  /'
else
  echo "[persistance] ECHEC : inventaire différent après down/up"
  printf '%s\n' "$AFTER_CYCLE" | sed 's/^/  /'
  exit 1
fi

echo "[persistance] volumes conservés :"
docker volume ls --filter name=documenso-poc --format '  {{.Name}}'
