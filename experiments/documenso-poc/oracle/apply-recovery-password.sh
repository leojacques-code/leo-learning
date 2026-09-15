#!/usr/bin/env bash
# Applique le secret de récupération GitHub aux accès Basic Auth Mailpit + Demo.
# Le secret arrive dans un fichier temporaire chmod 600 déposé par GitHub Actions.
# Il n'est jamais affiché, commité ni conservé hors de auth.env sur la VM.

set -euo pipefail

POC_STATE_DIR=/opt/documenso-poc
AUTH_FILE="$POC_STATE_DIR/state/auth.env"
RECOVERY_FILE="${1:-/tmp/documenso-poc-recovery-password}"
CADDY_IMAGE='caddy:2.10-alpine'

log() { printf '[recovery] %s\n' "$*"; }
die() { printf '[recovery] ERREUR : %s\n' "$*" >&2; exit 1; }

cleanup() {
  unset RECOVERY_PASSWORD NEW_MAIL_HASH NEW_DEMO_HASH || true
  if [[ -f "$RECOVERY_FILE" ]]; then
    shred -u "$RECOVERY_FILE" 2>/dev/null || rm -f "$RECOVERY_FILE"
  fi
}
trap cleanup EXIT

[[ -f "$RECOVERY_FILE" ]] || { log "aucun secret de récupération à appliquer"; exit 0; }
[[ -f "$AUTH_FILE" ]] || die "fichier auth.env introuvable"
chmod 600 "$RECOVERY_FILE"

# Le secret doit être une seule ligne. GitHub Actions ajoute uniquement le LF final.
[[ "$(wc -l < "$RECOVERY_FILE" | tr -d ' ')" == "1" ]] \
  || die "le secret de récupération doit tenir sur une seule ligne"
IFS= read -r RECOVERY_PASSWORD < "$RECOVERY_FILE" || true
[[ ${#RECOVERY_PASSWORD} -ge 12 ]] \
  || die "le secret de récupération doit contenir au moins 12 caractères"

# Préserver les identifiants applicatifs existants. shellcheck disable=SC1090
set +u
. "$AUTH_FILE"
set -u
[[ -n "${POC_AUTH_USER:-}" ]] || die "POC_AUTH_USER absent"
[[ -n "${POC_APP_BOOTSTRAP_PASSWORD:-}" ]] || die "POC_APP_BOOTSTRAP_PASSWORD absent"
[[ -n "${POC_APP_HASH:-}" ]] || die "POC_APP_HASH absent"

hash_pw() {
  local pw="$1" out=''
  out="$(printf '%s\n' "$pw" \
    | docker run --rm -i "$CADDY_IMAGE" caddy hash-password 2>/dev/null \
    | tr -d '\r\n')"
  [[ "$out" == \$2* ]] || return 1
  printf '%s' "$out"
}

NEW_MAIL_HASH="$(hash_pw "$RECOVERY_PASSWORD")" || die "hachage bcrypt impossible pour Mailpit"
NEW_DEMO_HASH="$(hash_pw "$RECOVERY_PASSWORD")" || die "hachage bcrypt impossible pour Demo"

TMP_FILE="$AUTH_FILE.tmp.$$"
umask 077
{
  printf 'POC_AUTH_USER=%q\n' "$POC_AUTH_USER"
  printf 'POC_MAIL_PASSWORD=%q\n' "$RECOVERY_PASSWORD"
  printf 'POC_DEMO_PASSWORD=%q\n' "$RECOVERY_PASSWORD"
  printf 'POC_APP_BOOTSTRAP_PASSWORD=%q\n' "$POC_APP_BOOTSTRAP_PASSWORD"
  printf 'POC_MAIL_HASH=%q\n' "$NEW_MAIL_HASH"
  printf 'POC_DEMO_HASH=%q\n' "$NEW_DEMO_HASH"
  printf 'POC_APP_HASH=%q\n' "$POC_APP_HASH"
} > "$TMP_FILE"
chmod 600 "$TMP_FILE"
mv -f "$TMP_FILE" "$AUTH_FILE"
chmod 600 "$AUTH_FILE"

log "mot de passe de récupération appliqué à Mailpit et à la page Demo"
