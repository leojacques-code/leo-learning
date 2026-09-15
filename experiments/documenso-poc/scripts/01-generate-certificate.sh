#!/usr/bin/env bash
#
# Génère le certificat X.509 auto-signé du POC et l'archive PKCS#12 attendue
# par Documenso, puis inscrit sa passphrase dans .env.
#
# PORTÉE JURIDIQUE : ce certificat sert exclusivement à un POC TECHNIQUE.
# Il ne constitue ni une signature qualifiée eIDAS, ni une QES, ni une AES,
# ni un certificat qualifié, ni un équivalent juridique de DocuSign.

set -euo pipefail

# Le POC local écrit dans le dossier du dépôt. Le déploiement Oracle passe
# DOCUMENSO_POC_STATE_DIR pour que secrets et certificat vivent hors du dépôt
# Git (/opt/documenso-poc), et survivent donc à tout `git fetch`/`git checkout`.
POC_DIR="${DOCUMENSO_POC_STATE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CERT_DIR="$POC_DIR/certs"
ENV_FILE="$POC_DIR/.env"
P12="$CERT_DIR/cert.p12"

[[ -f "$ENV_FILE" ]] || { echo "Lancer d'abord ./scripts/00-generate-secrets.sh"; exit 1; }
command -v openssl >/dev/null || { echo "openssl introuvable."; exit 1; }

if [[ -f "$P12" ]]; then
  echo "Refus : $P12 existe déjà. Le supprimer manuellement pour régénérer."
  exit 1
fi

mkdir -p "$CERT_DIR"
umask 077

PASSPHRASE="$(openssl rand -base64 24 | tr -d '=\n')"

# Fichiers intermédiaires en zone temporaire, détruits à la sortie du script
# quelle qu'en soit la cause.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

openssl req -x509 -newkey rsa:4096 -sha256 -days 365 -nodes \
  -keyout "$TMP/private.key" \
  -out "$TMP/certificate.crt" \
  -subj "/O=Triactis POC/CN=Documenso Test Signing Certificate" \
  -addext "keyUsage=critical,digitalSignature,nonRepudiation" \
  -addext "extendedKeyUsage=emailProtection" \
  -addext "basicConstraints=critical,CA:FALSE" \
  2>/dev/null

openssl pkcs12 -export \
  -in "$TMP/certificate.crt" \
  -inkey "$TMP/private.key" \
  -out "$P12" \
  -name "Triactis POC Signing" \
  -passout "pass:$PASSPHRASE"

chmod 600 "$P12"

# Inscription de la passphrase dans .env (remplace la ligne vide existante).
# On passe par un fichier temporaire pour ne pas exposer la valeur en argument
# de commande, où elle serait visible dans la table des processus.
PF="$TMP/pass"; printf '%s' "$PASSPHRASE" > "$PF"
python3 - "$ENV_FILE" "$PF" <<'PY'
import sys, pathlib
env, pf = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
secret = pf.read_text()
lines = env.read_text().splitlines()
key = "NEXT_PRIVATE_SIGNING_PASSPHRASE"
out, seen = [], False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={secret}"); seen = True
    else:
        out.append(line)
if not seen:
    out.append(f"{key}={secret}")
env.write_text("\n".join(out) + "\n")
PY

echo "Certificat généré : $P12"
echo "Passphrase inscrite dans .env. Clé privée et .crt intermédiaires détruits."
echo
openssl pkcs12 -in "$P12" -nokeys -passin "pass:$PASSPHRASE" 2>/dev/null \
  | openssl x509 -noout -subject -enddate
echo
echo "Rappel : POC technique uniquement. Aucune valeur eIDAS, QES ou AES."
echo "Étape suivante : ./scripts/02-up.sh"
