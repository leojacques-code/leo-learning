#!/usr/bin/env bash
#
# Orchestrateur exécuté sur la VM Oracle par le workflow GitHub Actions.
#
# Enchaîne, dans l'ordre et de façon idempotente :
#   bootstrap hôte → déploiement → amorçage applicatif → fermeture de
#   l'inscription → contrôles → test de persistance → sauvegarde → restitution
#   chiffrée des éléments sensibles.
#
# N'affiche jamais de valeur sensible : voir l'en-tête de oracle/relay.sh pour
# le canal de retour utilisé.

set -euo pipefail

POC_STATE_DIR=/opt/documenso-poc
POC_SRC_DIR=/opt/leo-learning/experiments/documenso-poc
ORACLE_DIR="$POC_SRC_DIR/oracle"

log() { printf '\n########## %s ##########\n' "$*"; }

log "1/8 BOOTSTRAP DE L'HÔTE"
bash "$ORACLE_DIR/bootstrap.sh"

log "2/8 DÉPLOIEMENT DE LA PILE"
bash "$ORACLE_DIR/deploy.sh"

# shellcheck disable=SC1091
set -a; . "$POC_STATE_DIR/oracle.env"; . "$POC_STATE_DIR/state/auth.env"; set +a
PHASE="$(cat "$POC_STATE_DIR/state/last-phase")"

log "3/8 GÉNÉRATION DES MODÈLES DE DÉMONSTRATION"
python3 "$POC_SRC_DIR/scripts/05-generate-demo-templates.py" || true

log "4/8 AMORÇAGE APPLICATIF ET RECETTE FONCTIONNELLE"
if [[ "$PHASE" == bootstrap ]]; then
  # L'application est encore derrière le Basic Auth de bootstrap : l'inscription
  # est ouverte côté Documenso mais personne d'autre ne peut l'atteindre.
  python3 "$ORACLE_DIR/seed.py" \
    --base "https://$POC_HOSTNAME" \
    --basic-auth "$POC_AUTH_USER:$POC_APP_BOOTSTRAP_PASSWORD" \
    --repo-dir "$POC_SRC_DIR"

  touch "$POC_STATE_DIR/state/bootstrapped"

  log "5/8 FERMETURE DE L'INSCRIPTION ET RETRAIT DU BASIC AUTH APPLICATIF"
  bash "$ORACLE_DIR/deploy.sh"
else
  python3 "$ORACLE_DIR/seed.py" \
    --base "https://$POC_HOSTNAME" \
    --repo-dir "$POC_SRC_DIR"
  log "5/8 INSCRIPTION DÉJÀ FERMÉE, BASIC AUTH APPLICATIF DÉJÀ RETIRÉ"
fi

# Configuration de la page de démonstration : uniquement le chemin du lien
# direct, qui est fait pour être partagé. Aucun jeton d'API, aucun secret.
python3 "$ORACLE_DIR/write-demo-config.py"
cp -f "$POC_SRC_DIR/demo/bulk-send-demo.csv" "$POC_STATE_DIR/demo/bulk-send-demo.csv"
chmod 644 "$POC_STATE_DIR/demo/bulk-send-demo.csv"

log "6/8 CONTRÔLES D'APRÈS DÉPLOIEMENT"
bash "$ORACLE_DIR/checks.sh" || echo "[run] des contrôles ont échoué, voir ci-dessus"

log "7/8 PERSISTANCE : REDÉMARRAGE DE LA PILE"
bash "$ORACLE_DIR/persistence.sh" || echo "[run] test de persistance en échec, voir ci-dessus"

log "8/8 SAUVEGARDE ET RESTITUTION CHIFFRÉE"
bash "$POC_SRC_DIR/scripts/oracle-backup.sh"
bash "$ORACLE_DIR/relay.sh"

echo
echo "[run] terminé."
