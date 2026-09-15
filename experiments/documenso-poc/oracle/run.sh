#!/usr/bin/env bash
#
# Orchestrateur exécuté sur la VM Oracle par le workflow GitHub Actions.
#
# Enchaîne, dans l'ordre et de façon idempotente :
#   bootstrap hôte → déploiement → amorçage applicatif → fermeture de
#   l'inscription → contrôles → test de persistance → sauvegarde → restitution
#   chiffrée des éléments sensibles → inventaire applicatif.
#
# N'affiche jamais de valeur sensible : voir l'en-tête de oracle/relay.sh pour
# le canal de retour utilisé.

set -euo pipefail

POC_STATE_DIR=/opt/documenso-poc
POC_SRC_DIR=/opt/leo-learning/experiments/documenso-poc
ORACLE_DIR="$POC_SRC_DIR/oracle"

log() { printf '\n########## %s ##########\n' "$*"; }

SEED_DEGRADED=0

# Amorçage d'une instance DÉJÀ amorcée.
#
# Il n'y a alors plus rien à créer : chaque étape se contente de constater que
# le compte, les modèles, le lien direct et le parcours signé sont déjà là.
# Mais l'amorçage se connecte au compte POC avec le mot de passe enregistré
# dans state/seed-state.json. Si ce mot de passe a été changé depuis
# l'interface Documenso, geste d'exploitation parfaitement légitime, la
# connexion échoue et, sous `set -e`, emportait jusqu'ici tout le reste du
# déploiement : contrôles, persistance et sauvegarde compris.
#
# Ce cas précis, et lui seul, devient un avertissement. Toute autre erreur
# d'amorçage interrompt toujours le déploiement.
run_seed_idempotent() {
  local log_file rc=0
  log_file="$(mktemp)"

  set +e
  "$@" 2>&1 | tee "$log_file"
  rc=${PIPESTATUS[0]}
  set -e

  if [[ "$rc" -eq 0 ]]; then
    rm -f "$log_file"
    return 0
  fi

  if grep -q 'INVALID_CREDENTIALS' "$log_file"; then
    rm -f "$log_file"
    SEED_DEGRADED=1
    echo
    echo "[run] AVERTISSEMENT : le mot de passe du compte POC enregistré dans"
    echo "[run] state/seed-state.json ne correspond plus à celui de la base."
    echo "[run] Il a vraisemblablement été changé depuis l'interface Documenso."
    echo "[run] L'instance étant déjà amorcée, l'amorçage n'avait rien à créer :"
    echo "[run] le déploiement se poursuit, contrôles et sauvegarde compris."
    return 0
  fi

  rm -f "$log_file"
  return "$rc"
}

# ---------------------------------------------------------------------------
# Groupe docker
# ---------------------------------------------------------------------------
# bootstrap.sh ajoute l'utilisateur au groupe `docker`, mais l'appartenance
# aux groupes est lue à l'ouverture de session : la session SSH en cours ne la
# porte pas encore, et le premier appel à docker échoue sur la socket.
#
# Plutôt que de basculer toute la pile sur `sudo docker` (ce qui rendrait les
# scripts inutilisables tels quels par un humain connecté normalement), on se
# relance une seule fois dans un shell qui porte le groupe. Aux exécutions
# suivantes la session SSH l'a déjà et cette branche n'est pas prise.
if [[ "${POC_DOCKER_GROUP_OK:-}" != "1" ]]; then
  log "1/8 BOOTSTRAP DE L'HÔTE"
  bash "$ORACLE_DIR/bootstrap.sh"

  if ! docker info >/dev/null 2>&1; then
    if id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
      echo "[run] groupe docker acquis mais pas encore effectif : relance via sg"
      exec sg docker -c "POC_DOCKER_GROUP_OK=1 bash '$ORACLE_DIR/run.sh'"
    fi
    echo "[run] ERREUR : la socket Docker est injoignable et l'utilisateur" >&2
    echo "[run] n'appartient pas au groupe docker." >&2
    exit 1
  fi
  export POC_DOCKER_GROUP_OK=1
else
  echo "[run] 1/8 bootstrap déjà passé, poursuite dans le shell portant le groupe docker"
fi

# Un secret de récupération peut être déposé temporairement par GitHub Actions.
# Il ne transite jamais en argument de commande ni dans les logs. Le script le
# consomme avant le rendu Caddy, puis le détruit.
RECOVERY_FILE=/tmp/documenso-poc-recovery-password
if [[ -f "$RECOVERY_FILE" ]]; then
  log "APPLICATION DU MOT DE PASSE DE RÉCUPÉRATION"
  bash "$ORACLE_DIR/apply-recovery-password.sh" "$RECOVERY_FILE"
fi

log "2/8 DÉPLOIEMENT DE LA PILE"
bash "$ORACLE_DIR/deploy.sh"

# shellcheck disable=SC1091
set -a; . "$POC_STATE_DIR/oracle.env"; . "$POC_STATE_DIR/state/auth.env"; set +a
PHASE="$(cat "$POC_STATE_DIR/state/last-phase")"

log "3/8 GÉNÉRATION DES MODÈLES DE DÉMONSTRATION"
python3 "$POC_SRC_DIR/scripts/05-generate-demo-templates.py"

log "4/8 AMORÇAGE APPLICATIF ET RECETTE FONCTIONNELLE"
if [[ "$PHASE" == bootstrap ]]; then
  # L'application est encore derrière le Basic Auth de bootstrap : l'inscription
  # est ouverte côté Documenso mais personne d'autre ne peut l'atteindre.
  # Ici le compte n'existe pas encore : la moindre erreur est bloquante.
  python3 "$ORACLE_DIR/seed.py" \
    --base "https://$POC_HOSTNAME" \
    --basic-auth "$POC_AUTH_USER:$POC_APP_BOOTSTRAP_PASSWORD" \
    --repo-dir "$POC_SRC_DIR"

  touch "$POC_STATE_DIR/state/bootstrapped"

  log "5/8 FERMETURE DE L'INSCRIPTION ET RETRAIT DU BASIC AUTH APPLICATIF"
  bash "$ORACLE_DIR/deploy.sh"
else
  run_seed_idempotent python3 "$ORACLE_DIR/seed.py" \
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
if [[ "$SEED_DEGRADED" -eq 1 ]]; then
  echo "[run] terminé, AVEC UNE RÉSERVE : l'amorçage n'a pas pu se connecter au"
  echo "[run] compte POC. Le mot de passe enregistré dans state/seed-state.json"
  echo "[run] est périmé. Pour le resynchroniser, deux voies :"
  echo "[run]   - inscrire le mot de passe courant dans state/seed-state.json ;"
  echo "[run]   - ou supprimer state/seed-state.json pour repartir d'un compte"
  echo "[run]     de démonstration neuf. Les données existantes sont conservées,"
  echo "[run]     mais les modèles et le parcours de démonstration sont recréés."
else
  echo "[run] terminé."
fi

# Inventaire en lecture seule, en dernier : c'est par la fin qu'on lit le
# journal d'un run. Il ne modifie rien et ne peut pas faire échouer le
# déploiement.
log "INVENTAIRE APPLICATIF (LECTURE SEULE)"
bash "$ORACLE_DIR/audit-inventory.sh" || echo "[run] inventaire incomplet, voir ci-dessus"
