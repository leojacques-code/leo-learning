#!/usr/bin/env bash
#
# Vérification d'état après un redémarrage de la machine.
#
# Lancé par le workflow une fois que le port 22 répond à nouveau. Il contrôle
# que le POC est reparti tout seul : Docker actif au démarrage, conteneurs
# relancés par leur politique `restart: unless-stopped`, HTTPS servi, et
# surtout données intactes.
#
# Écrit son marqueur en cas de succès : le test ne se rejoue pas à chaque
# déploiement, un redémarrage n'ayant pas à être une routine.

set -uo pipefail

POC_STATE_DIR=/opt/documenso-poc
POC_SRC_DIR=/opt/leo-learning/experiments/documenso-poc

# shellcheck disable=SC1091
set -a; . "$POC_STATE_DIR/oracle.env"; set +a

FAILURES=0
ok() { printf '  [ OK ] %s\n' "$*"; }
ko() { printf '  [ KO ] %s\n' "$*"; FAILURES=$((FAILURES + 1)); }

printf '\n== État au retour du redémarrage ==\n'
printf '  uptime : %s\n' "$(uptime -p 2>/dev/null || uptime)"
printf '  boot   : %s\n' "$(uptime -s 2>/dev/null || echo inconnu)"

systemctl is-active --quiet docker \
  && ok "docker.service : actif" \
  || ko "docker.service : inactif"

systemctl is-enabled --quiet docker \
  && ok "docker.service : activé au démarrage" \
  || ko "docker.service : non activé au démarrage"

# Les conteneurs reviennent par leur politique de redémarrage, sans
# intervention. On laisse à Documenso le temps de finir son démarrage.
ready=0
for _ in $(seq 1 60); do
  if curl -fsS --max-time 5 http://127.0.0.1:3000/api/health >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 5
done
((ready)) && ok "Documenso répond sur la boucle locale, sans relance manuelle" \
           || ko "Documenso ne répond pas après redémarrage"

for name in documenso-poc-db documenso-poc-app documenso-poc-caddy \
            documenso-poc-mail documenso-poc-webhook-sink; do
  state="$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null || echo absent)"
  [[ "$state" == running ]] && ok "conteneur $name : running" \
                            || ko "conteneur $name : $state"
done

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://$POC_HOSTNAME/api/health" || echo 000)"
[[ "$code" == "200" ]] && ok "HTTPS public : 200" || ko "HTTPS public : $code"

# Le certificat de signature est monté depuis l'hôte : sa disparition ne se
# verrait qu'à la première signature, donc on le contrôle ici.
health="$(curl -fsS --max-time 10 http://127.0.0.1:3000/api/health 2>/dev/null || echo '')"
printf '%s' "$health" | grep -q '"certificate":{"status":"ok"}' \
  && ok "certificat de signature : toujours monté et lisible" \
  || ko "certificat de signature : contrôle en échec"

printf '\n== Données après redémarrage ==\n'
python3 "$POC_SRC_DIR/oracle/seed.py" --base http://127.0.0.1:3000 --inventory-only \
  | sed 's/^/  /'

if [[ "$FAILURES" -eq 0 ]]; then
  touch "$POC_STATE_DIR/state/reboot-tested"
  printf '\n== Redémarrage : aucun contrôle en échec, test marqué comme passé ==\n'
else
  printf '\n== Redémarrage : %d contrôle(s) en échec ==\n' "$FAILURES"
fi
exit $(( FAILURES > 0 ? 1 : 0 ))
