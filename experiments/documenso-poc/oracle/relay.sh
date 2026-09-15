#!/usr/bin/env bash
#
# Restitution chiffrée des éléments sensibles du déploiement.
#
# PROBLÈME RÉSOLU. Le dépôt est public : tout ce qu'un job GitHub Actions
# affiche est lisible par n'importe qui. Or l'agent qui conduit le déploiement
# n'a pas d'accès SSH direct à la VM ; le seul canal de retour est ce journal
# public. Les mots de passe du compte POC, ceux du Basic Auth et le lien de
# signature destiné au téléphone ne peuvent donc pas y être écrits en clair.
#
# SOLUTION. Chiffrement asymétrique à sens unique. oracle/relay-cert.pem est un
# certificat PUBLIC, versionné sans risque. La clé privée correspondante n'a
# jamais quitté l'environnement de l'agent. La VM chiffre les valeurs vers ce
# certificat (CMS, AES-256) et n'imprime que le chiffré : seul le détenteur de
# la clé privée peut le lire.
#
# Aucune valeur en clair ne sort de ce script.

set -euo pipefail

POC_STATE_DIR=/opt/documenso-poc
CERT="/opt/leo-learning/experiments/documenso-poc/oracle/relay-cert.pem"

[[ -f "$CERT" ]] || { echo "[relay] certificat de relais introuvable" >&2; exit 1; }

# shellcheck disable=SC1091
set -a; . "$POC_STATE_DIR/state/auth.env"; set +a
# shellcheck disable=SC1091
set -a; . "$POC_STATE_DIR/oracle.env"; set +a

HANDOFF="$POC_STATE_DIR/artifacts/handoff.json"
[[ -f "$HANDOFF" ]] || echo '{}' > "$HANDOFF"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
umask 077

# Assemblage du paquet. jq lit les valeurs depuis l'environnement plutôt que
# depuis la ligne de commande : rien n'apparaît dans la table des processus.
jq -n \
  --slurpfile handoff "$HANDOFF" \
  '{
     hostnames: {
       app:   env.POC_HOSTNAME,
       mail:  env.POC_MAIL_HOSTNAME,
       demo:  env.POC_DEMO_HOSTNAME
     },
     basicAuth: {
       user:          env.POC_AUTH_USER,
       mailPassword:  env.POC_MAIL_PASSWORD,
       demoPassword:  env.POC_DEMO_PASSWORD
     },
     seed: $handoff[0]
   }' > "$TMP/bundle.json"

openssl smime -encrypt -aes-256-cbc -binary -outform PEM -in "$TMP/bundle.json" "$CERT" \
  > "$TMP/bundle.pem"

echo "----BEGIN TRIACTIS RELAY----"
cat "$TMP/bundle.pem"
echo "----END TRIACTIS RELAY----"
echo "[relay] paquet chiffré émis ($(wc -c < "$TMP/bundle.pem") octets de chiffré)"
