#!/usr/bin/env bash
#
# Sauvegarde du POC Documenso hébergé sur Oracle Cloud.
#
# Sauvegarde :
#   - le dump PostgreSQL complet (comptes, modèles, documents, PDF scellés,
#     puisque les PDF sont stockés en base) ;
#   - le fichier .env, sans lequel l'application refuse de démarrer ;
#   - le certificat de signature cert.p12.
#
# LIMITE À CONNAÎTRE, ET ELLE EST SÉRIEUSE. La sauvegarde est écrite sur le
# MÊME disque que les données. Ce n'est donc pas un plan de reprise : elle
# protège d'une erreur de manipulation, d'une migration ratée ou d'une purge
# accidentelle, pas de la perte du volume de démarrage ni de la disparition de
# l'instance. Un vrai dispositif suppose une copie hors de la machine (Object
# Storage, poste du cabinet, autre fournisseur), qui n'est pas mise en place
# ici et devra l'être avant tout usage sérieux.
#
# La restauration n'est JAMAIS automatique : voir oracle-restore.sh.

set -euo pipefail

POC_STATE_DIR=/opt/documenso-poc
POC_SRC_DIR=/opt/leo-learning/experiments/documenso-poc
BACKUP_ROOT=/var/backups/documenso-poc
KEEP=7

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_ROOT/$STAMP"

log() { printf '[backup] %s\n' "$*"; }

command -v docker >/dev/null || { echo "docker introuvable" >&2; exit 1; }
[[ -f "$POC_STATE_DIR/.env" ]] || { echo "$POC_STATE_DIR/.env introuvable" >&2; exit 1; }

umask 077
mkdir -p "$DEST"

# --- base de données --------------------------------------------------------
log "dump PostgreSQL en cours"
docker exec -i documenso-poc-db \
  pg_dump -U documenso -d documenso_poc --format=custom --no-owner \
  > "$DEST/documenso_poc.dump"

size="$(stat -c %s "$DEST/documenso_poc.dump")"
(( size > 10000 )) || { echo "dump anormalement petit ($size octets), sauvegarde abandonnée" >&2;
                        rm -rf "$DEST"; exit 1; }
log "dump : $size octets"

# --- secrets ----------------------------------------------------------------
# Le .env et le certificat sont le point de reprise : sans eux, la base est
# inexploitable (clés de chiffrement applicatif) et l'application ne démarre pas.
cp -p "$POC_STATE_DIR/.env" "$DEST/env.backup"
cp -p "$POC_STATE_DIR/certs/cert.p12" "$DEST/cert.p12"
[[ -f "$POC_STATE_DIR/state/auth.env" ]] && cp -p "$POC_STATE_DIR/state/auth.env" "$DEST/auth.env.backup"
[[ -f "$POC_STATE_DIR/state/seed-state.json" ]] && cp -p "$POC_STATE_DIR/state/seed-state.json" "$DEST/seed-state.json"

# --- manifeste --------------------------------------------------------------
{
  printf 'horodatage        : %s\n' "$STAMP"
  printf 'commit deploye    : %s\n' "$(git -C /opt/leo-learning rev-parse HEAD 2>/dev/null || echo inconnu)"
  printf 'image documenso   : %s\n' "$(docker inspect --format '{{.Config.Image}}' documenso-poc-app 2>/dev/null || echo inconnu)"
  printf 'dump octets       : %s\n' "$size"
  printf 'sha256 dump       : %s\n' "$(sha256sum "$DEST/documenso_poc.dump" | cut -d' ' -f1)"
  printf 'sha256 env        : %s\n' "$(sha256sum "$DEST/env.backup" | cut -d' ' -f1)"
  printf 'sha256 cert.p12   : %s\n' "$(sha256sum "$DEST/cert.p12" | cut -d' ' -f1)"
} > "$DEST/MANIFEST.txt"

chmod 700 "$DEST"
chmod 600 "$DEST"/*

# --- rotation ---------------------------------------------------------------
mapfile -t old < <(find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | sort -r | tail -n +$((KEEP + 1)))
for dir in "${old[@]:-}"; do
  [[ -n "$dir" ]] || continue
  log "rotation : suppression de $dir"
  rm -rf "${BACKUP_ROOT:?}/$dir"
done

log "sauvegarde écrite dans $DEST"
log "RAPPEL : même disque que les données, ce n'est pas un plan de reprise."
ls -1 "$BACKUP_ROOT" | sed 's/^/[backup]   /'
