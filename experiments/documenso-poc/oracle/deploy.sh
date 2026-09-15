#!/usr/bin/env bash
#
# Déploiement du POC Documenso sur la VM Oracle Cloud.
#
# Lancé par .github/workflows/deploy-documenso-oracle.yml, sur la VM, via SSH.
# Idempotent : relançable à volonté.
#
# CONFIDENTIALITÉ. Ce script s'exécute dans un job GitHub Actions dont les
# journaux sont PUBLICS (dépôt public). Il n'écrit donc jamais sur la sortie
# standard : mot de passe, clé, passphrase, jeton de signature ou lien de
# signature. Les valeurs sensibles produites ici sont chiffrées vers
# oracle/relay-cert.pem, dont la clé privée n'existe que dans l'environnement
# de l'agent qui a préparé le déploiement. Seul le chiffré transite.
#
# Aucun `set -x` n'est activé.

set -euo pipefail

POC_STATE_DIR=/opt/documenso-poc
REPO_DIR=/opt/leo-learning
POC_SRC_DIR="$REPO_DIR/experiments/documenso-poc"
ORACLE_DIR="$POC_SRC_DIR/oracle"
CADDY_IMAGE='caddy:2.10-alpine'

log() { printf '[deploy] %s\n' "$*"; }
die() { printf '[deploy] ERREUR : %s\n' "$*" >&2; exit 1; }

# Appel HTTP avec Basic Auth sans jamais placer le mot de passe en argument de
# commande : il serait sinon visible dans la table des processus.
curl_auth() {
  local user="$1" pass="$2"; shift 2
  printf 'user = "%s:%s"\n' "$user" "$pass" | curl --config - "$@"
}

# ---------------------------------------------------------------------------
# 1. Hostname public
# ---------------------------------------------------------------------------
discover_public_ip() {
  local ip=''
  # Service de métadonnées Oracle : source de vérité, aucune dépendance externe.
  ip="$(curl -fsS --max-time 5 -H 'Authorization: Bearer Oracle' \
        http://169.254.169.254/opc/v2/vnics/ 2>/dev/null \
        | jq -r '[.[].publicIp] | map(select(. != null and . != "")) | first // empty' 2>/dev/null || true)"
  if [[ -z "$ip" ]]; then
    ip="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"
  fi
  printf '%s' "$ip"
}

PUBLIC_IP="$(discover_public_ip)"
[[ "$PUBLIC_IP" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] \
  || die "adresse IPv4 publique introuvable (obtenu : '${PUBLIC_IP:-vide}')"

APP_HOST="${PUBLIC_IP//./-}.sslip.io"
MAIL_HOST="mail.${APP_HOST}"
DEMO_HOST="demo.${APP_HOST}"

# Le hostname public n'est pas un secret : il figurera dans les journaux de
# Certificate Transparency dès la première émission de certificat, et c'est
# l'URL que l'utilisateur ouvrira sur son téléphone. Il est donc affiché
# volontairement, pour que le déploiement soit vérifiable depuis les journaux.
log "hostname application : $APP_HOST"
log "hostname mailpit     : $MAIL_HOST"
log "hostname démo        : $DEMO_HOST"

# Résolution locale vers la boucle : la VM ne peut pas nécessairement joindre
# sa propre adresse publique (le hairpin NAT n'est pas garanti chez Oracle).
# Sans cela, les vérifications HTTPS menées depuis la VM échoueraient alors
# même que le service répond parfaitement depuis Internet.
sudo sed -i '/# documenso-poc sslip.io/,+1d' /etc/hosts
printf '# documenso-poc sslip.io\n127.0.0.1 %s %s %s\n' "$APP_HOST" "$MAIL_HOST" "$DEMO_HOST" \
  | sudo tee -a /etc/hosts >/dev/null
log "/etc/hosts : résolution locale des trois hostnames vers 127.0.0.1"

# ---------------------------------------------------------------------------
# 2. Secrets applicatifs, créés SUR la VM, jamais transmis
# ---------------------------------------------------------------------------
export DOCUMENSO_POC_STATE_DIR="$POC_STATE_DIR"

if [[ ! -f "$POC_STATE_DIR/.env" ]]; then
  log "génération des secrets applicatifs"
  bash "$POC_SRC_DIR/scripts/00-generate-secrets.sh" >/dev/null
else
  log "secrets applicatifs : déjà présents, conservés tels quels"
fi
chmod 600 "$POC_STATE_DIR/.env"

if [[ ! -f "$POC_STATE_DIR/certs/cert.p12" ]]; then
  log "génération du certificat de signature POC"
  bash "$POC_SRC_DIR/scripts/01-generate-certificate.sh" >/dev/null
else
  log "certificat de signature : déjà présent, conservé tel quel"
fi
chmod 600 "$POC_STATE_DIR/certs/cert.p12"

# Garde-fou : ne JAMAIS régénérer les clés de chiffrement sur une base qui
# contient déjà des données. Elles deviendraient illisibles.
grep -q '^NEXT_PRIVATE_ENCRYPTION_KEY=.\+' "$POC_STATE_DIR/.env" \
  || die "NEXT_PRIVATE_ENCRYPTION_KEY vide dans $POC_STATE_DIR/.env"
grep -q '^NEXT_PRIVATE_SIGNING_PASSPHRASE=.\+' "$POC_STATE_DIR/.env" \
  || die "NEXT_PRIVATE_SIGNING_PASSPHRASE vide dans $POC_STATE_DIR/.env"

# ---------------------------------------------------------------------------
# 3. Identifiants Basic Auth de Caddy
# ---------------------------------------------------------------------------
AUTH_FILE="$POC_STATE_DIR/state/auth.env"

if [[ ! -f "$AUTH_FILE" ]]; then
  log "génération des identifiants Basic Auth"
  docker pull -q "$CADDY_IMAGE" >/dev/null

  # 32 caractères base64url : nettement au-delà des ~24 demandés, le hash
  # bcrypt qui en découle n'est pas attaquable par force brute.
  gen_pw() { openssl rand -base64 48 | tr -d '=+/\n' | cut -c1-32; }

  _mail_pw="$(gen_pw)"; _demo_pw="$(gen_pw)"; _app_pw="$(gen_pw)"

  # Le mot de passe passe par stdin, jamais en argument : il n'apparaît donc
  # ni dans la table des processus ni dans la ligne de commande du conteneur.
  hash_pw() { printf '%s' "$1" | docker run --rm -i "$CADDY_IMAGE" caddy hash-password; }

  umask 077
  {
    printf 'POC_AUTH_USER=triactis\n'
    printf 'POC_MAIL_PASSWORD=%s\n' "$_mail_pw"
    printf 'POC_DEMO_PASSWORD=%s\n' "$_demo_pw"
    printf 'POC_APP_BOOTSTRAP_PASSWORD=%s\n' "$_app_pw"
    printf 'POC_MAIL_HASH=%s\n' "$(hash_pw "$_mail_pw")"
    printf 'POC_DEMO_HASH=%s\n' "$(hash_pw "$_demo_pw")"
    printf 'POC_APP_HASH=%s\n' "$(hash_pw "$_app_pw")"
  } > "$AUTH_FILE"
  chmod 600 "$AUTH_FILE"
  unset _mail_pw _demo_pw _app_pw
else
  log "identifiants Basic Auth : déjà présents, conservés"
fi

# shellcheck disable=SC1090
set -a; . "$AUTH_FILE"; set +a

# ---------------------------------------------------------------------------
# 4. État du bootstrap
# ---------------------------------------------------------------------------
# Tant que le compte POC n'existe pas, l'inscription doit rester possible ;
# l'application est alors intégralement protégée par Basic Auth, pour que
# personne d'autre ne puisse s'inscrire. Une fois le compte créé, l'inscription
# est coupée à la source et le Basic Auth applicatif est retiré.
BOOTSTRAP_MARKER="$POC_STATE_DIR/state/bootstrapped"

if [[ -f "$BOOTSTRAP_MARKER" ]]; then
  PHASE=open
  POC_DISABLE_SIGNUP=true
else
  PHASE=bootstrap
  POC_DISABLE_SIGNUP=false
fi
log "phase : $PHASE (NEXT_PUBLIC_DISABLE_SIGNUP=$POC_DISABLE_SIGNUP)"
printf '%s\n' "$PHASE" > "$POC_STATE_DIR/state/last-phase"

# ---------------------------------------------------------------------------
# 5. Rendu de la configuration
# ---------------------------------------------------------------------------
umask 022

cat > "$POC_STATE_DIR/oracle.env" <<EOF
POC_HOSTNAME=$APP_HOST
POC_MAIL_HOSTNAME=$MAIL_HOST
POC_DEMO_HOSTNAME=$DEMO_HOST
POC_DISABLE_SIGNUP=$POC_DISABLE_SIGNUP
EOF
chmod 644 "$POC_STATE_DIR/oracle.env"

render_caddyfile() {
  local phase="$1"
  if [[ "$phase" == bootstrap ]]; then
    TPL_APP_GUARD="$(printf '\tbasic_auth {\n\t\t%s %s\n\t}\n' "$POC_AUTH_USER" "$POC_APP_HASH")"
  else
    TPL_APP_GUARD=''
  fi
  export TPL_APP_GUARD
  export TPL_APP_HOST="$APP_HOST" TPL_MAIL_HOST="$MAIL_HOST" TPL_DEMO_HOST="$DEMO_HOST"
  export TPL_AUTH_USER="$POC_AUTH_USER" TPL_MAIL_HASH="$POC_MAIL_HASH" TPL_DEMO_HASH="$POC_DEMO_HASH"

  python3 "$ORACLE_DIR/render-caddyfile.py" \
    "$ORACLE_DIR/Caddyfile.tpl" "$POC_STATE_DIR/Caddyfile"

  chmod 644 "$POC_STATE_DIR/Caddyfile"
  unset TPL_APP_GUARD TPL_APP_HOST TPL_MAIL_HOST TPL_DEMO_HOST TPL_AUTH_USER TPL_MAIL_HASH TPL_DEMO_HASH
}

CADDY_HASH_BEFORE="$(sha256sum "$POC_STATE_DIR/Caddyfile" 2>/dev/null | cut -d' ' -f1 || true)"
render_caddyfile "$PHASE"
CADDY_HASH_AFTER="$(sha256sum "$POC_STATE_DIR/Caddyfile" | cut -d' ' -f1)"

# Actifs de démonstration et récepteur de webhooks, recopiés hors du dépôt Git
# pour que les montages soient stables quel que soit le commit déployé.
cp -rf "$POC_SRC_DIR/demo/public/." "$POC_STATE_DIR/demo/"
cp -f "$ORACLE_DIR/webhook_sink.py" "$POC_STATE_DIR/webhook/webhook_sink.py"
chmod -R a+r "$POC_STATE_DIR/demo"
chmod 644 "$POC_STATE_DIR/webhook/webhook_sink.py"

# ---------------------------------------------------------------------------
# 6. Démarrage de la pile
# ---------------------------------------------------------------------------
dc() {
  docker compose \
    --project-directory "$POC_SRC_DIR" \
    --env-file "$POC_STATE_DIR/.env" \
    --env-file "$POC_STATE_DIR/oracle.env" \
    -f "$POC_SRC_DIR/compose.yml" \
    -f "$POC_SRC_DIR/compose.oracle.yml" \
    "$@"
}

# Validation de la composition SANS afficher les variables résolues :
# `docker compose config` sans --quiet dumperait les secrets dans un journal
# public.
dc config --quiet || die "composition Docker invalide"
log "composition Docker : valide"

log "démarrage de la pile"
dc up -d --remove-orphans

# Le Caddyfile est monté par chemin : son contenu peut changer sans que Compose
# ne recrée le conteneur. On redémarre donc Caddy explicitement quand sa
# configuration a bougé, sinon l'ancienne resterait chargée, ce qui laisserait
# par exemple le Basic Auth de bootstrap en place après son retrait.
if [[ "$CADDY_HASH_BEFORE" != "$CADDY_HASH_AFTER" ]]; then
  log "configuration Caddy modifiée : redémarrage du conteneur"
  dc restart caddy
  sleep 3
fi

# ---------------------------------------------------------------------------
# 7. Santé
# ---------------------------------------------------------------------------
log "attente de Documenso sur la boucle locale"
ready=0
for _ in $(seq 1 120); do
  if curl -fsS --max-time 5 http://127.0.0.1:3000/api/health >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 5
done
if ((ready == 0)); then
  dc logs --tail=150 documenso || true
  die "Documenso ne répond pas sur /api/health"
fi
log "Documenso répond : $(curl -fsS --max-time 5 http://127.0.0.1:3000/api/health | jq -c . 2>/dev/null || echo ok)"

log "attente du certificat TLS public (Caddy / Let's Encrypt)"
tls=0
for _ in $(seq 1 72); do
  if [[ "$PHASE" == bootstrap ]]; then
    curl_auth "$POC_AUTH_USER" "$POC_APP_BOOTSTRAP_PASSWORD" \
      -fsS --max-time 8 -o /dev/null "https://$APP_HOST/api/health" 2>/dev/null && { tls=1; break; }
  else
    curl -fsS --max-time 8 -o /dev/null "https://$APP_HOST/api/health" 2>/dev/null && { tls=1; break; }
  fi
  sleep 5
done
if ((tls == 0)); then
  dc logs --tail=100 caddy || true
  die "HTTPS public indisponible sur https://$APP_HOST"
fi
log "HTTPS public : certificat valide, application jointe via Caddy"

log "infrastructure déployée"
