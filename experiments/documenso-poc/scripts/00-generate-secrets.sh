#!/usr/bin/env bash
#
# Génère les secrets cryptographiques du POC dans experiments/documenso-poc/.env
#
# Les valeurs ne sont jamais affichées ni versionnées : .env est couvert par
# le .gitignore du dossier. Le script refuse d'écraser un .env existant.

set -euo pipefail

POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$POC_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  echo "Refus : $ENV_FILE existe déjà."
  echo "Le supprimer manuellement d'abord si vous voulez régénérer les secrets."
  echo "Attention : régénérer NEXT_PRIVATE_ENCRYPTION_KEY rend illisibles les"
  echo "données déjà chiffrées en base."
  exit 1
fi

command -v openssl >/dev/null || { echo "openssl introuvable."; exit 1; }

# 32 octets d'entropie, encodés en base64url sans padding.
gen() { openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n'; }

umask 077

cat > "$ENV_FILE" <<EOF
# Secrets du POC Documenso. NE JAMAIS COMMITER CE FICHIER.
# Généré le $(date +%Y-%m-%d) par scripts/00-generate-secrets.sh

POSTGRES_PASSWORD=$(gen)
NEXTAUTH_SECRET=$(gen)
NEXT_PRIVATE_ENCRYPTION_KEY=$(gen)
NEXT_PRIVATE_ENCRYPTION_SECONDARY_KEY=$(gen)

# Renseigné par scripts/01-generate-certificate.sh
NEXT_PRIVATE_SIGNING_PASSPHRASE=
EOF

chmod 600 "$ENV_FILE"

echo "Secrets générés dans $ENV_FILE (permissions 600)."
echo "Étape suivante : ./scripts/01-generate-certificate.sh"
