#!/usr/bin/env bash
#
# Contrôles d'après déploiement du POC Documenso sur Oracle Cloud.
#
# Exécuté sur la VM. N'affiche que des constats, jamais une valeur sensible.
# Un échec de contrôle n'interrompt pas le script : le rapport complet est
# produit, puis le code de sortie reflète le nombre d'échecs.

set -uo pipefail

POC_STATE_DIR=/opt/documenso-poc
POC_SRC_DIR=/opt/leo-learning/experiments/documenso-poc

# shellcheck disable=SC1091
set -a; . "$POC_STATE_DIR/oracle.env"; set +a

FAILURES=0
ok()   { printf '  [ OK ] %s\n' "$*"; }
ko()   { printf '  [ KO ] %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
warn() { printf '  [ -- ] %s\n' "$*"; }
section() { printf '\n== %s ==\n' "$*"; }

dc() {
  docker compose \
    --project-directory "$POC_SRC_DIR" \
    --env-file "$POC_STATE_DIR/.env" \
    --env-file "$POC_STATE_DIR/oracle.env" \
    -f "$POC_SRC_DIR/compose.yml" \
    -f "$POC_SRC_DIR/compose.oracle.yml" \
    "$@"
}

# ---------------------------------------------------------------------------
section "Conteneurs"
# ---------------------------------------------------------------------------
dc ps --format 'table {{.Service}}\t{{.Status}}' || true

for svc in database documenso mailpit caddy webhook-sink; do
  status="$(dc ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk -v s="$svc" '$1==s{print $2}')"
  [[ "$status" == "running" ]] && ok "service $svc : running" || ko "service $svc : ${status:-absent}"
done

pg="$(docker inspect --format '{{.State.Health.Status}}' documenso-poc-db 2>/dev/null || echo inconnu)"
[[ "$pg" == "healthy" ]] && ok "PostgreSQL : healthy" || ko "PostgreSQL : $pg"

# ---------------------------------------------------------------------------
section "Santé applicative"
# ---------------------------------------------------------------------------
health="$(curl -fsS --max-time 10 http://127.0.0.1:3000/api/health 2>/dev/null || echo '')"
if [[ -n "$health" ]]; then
  ok "boucle locale /api/health : $(printf '%s' "$health" | jq -c . 2>/dev/null || printf '%s' "$health")"
else
  ko "boucle locale /api/health : pas de réponse"
fi

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$POC_HOSTNAME/api/health" || echo 000)"
[[ "$code" == "200" ]] && ok "HTTPS public /api/health : 200" || ko "HTTPS public /api/health : $code"

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$POC_HOSTNAME/signin" || echo 000)"
[[ "$code" == "200" ]] && ok "HTTPS public /signin : 200" || ko "HTTPS public /signin : $code"

# L'inscription publique doit être fermée une fois le compte POC créé.
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
        -X POST -H 'Content-Type: application/json' \
        -d '{"name":"probe","email":"probe@triactis.test","password":"Probe-Probe-Probe!7"}' \
        "https://$POC_HOSTNAME/api/auth/email-password/signup" || echo 000)"
if [[ "$code" == "400" || "$code" == "403" ]]; then
  ok "inscription publique : refusée par l'API (HTTP $code)"
else
  ko "inscription publique : l'API a répondu $code, elle devrait refuser"
fi

# Le certificat TLS doit être public et valide, pas auto-signé.
issuer="$(echo | openssl s_client -connect "$POC_HOSTNAME:443" -servername "$POC_HOSTNAME" 2>/dev/null \
          | openssl x509 -noout -issuer 2>/dev/null || true)"
if printf '%s' "$issuer" | grep -qi "let's encrypt\|zerossl"; then
  ok "certificat TLS : ${issuer#issuer=}"
else
  ko "certificat TLS inattendu : ${issuer:-illisible}"
fi

# ---------------------------------------------------------------------------
section "Protection de Mailpit et de la page de démonstration"
# ---------------------------------------------------------------------------
for host in "$POC_MAIL_HOSTNAME" "$POC_DEMO_HOSTNAME"; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$host/" || echo 000)"
  [[ "$code" == "401" ]] && ok "$host sans identifiants : 401" \
                         || ko "$host sans identifiants : $code (401 attendu)"
done

# ---------------------------------------------------------------------------
section "Ports en écoute sur l'hôte"
# ---------------------------------------------------------------------------
listen="$(ss -ltnH 2>/dev/null || sudo ss -ltnH)"
printf '%s\n' "$listen" | awk '{print "    " $4}' | sort -u

check_bind() {
  local port="$1" expect="$2"
  local lines
  lines="$(printf '%s\n' "$listen" | awk -v p=":$port\$" '$4 ~ p {print $4}')"
  if [[ -z "$lines" ]]; then
    [[ "$expect" == absent ]] && ok "port $port : aucune écoute" || ko "port $port : aucune écoute"
    return
  fi
  case "$expect" in
    public)
      printf '%s\n' "$lines" | grep -qE '^(0\.0\.0\.0|\*|\[::\]):' \
        && ok "port $port : écoute publique, attendu" \
        || ko "port $port : devrait être public"
      ;;
    local)
      if printf '%s\n' "$lines" | grep -qvE '^(127\.0\.0\.1|\[::1\]):'; then
        ko "port $port : écoute au-delà de la boucle locale ($(printf '%s' "$lines" | tr '\n' ' '))"
      else
        ok "port $port : boucle locale uniquement"
      fi
      ;;
  esac
}

check_bind 22 public
check_bind 80 public
check_bind 443 public
check_bind 3000 local
check_bind 55432 local
check_bind 8025 local
check_bind 1025 local
check_bind 5432 absent

# ---------------------------------------------------------------------------
section "Query string sensible : absence dans les journaux"
# ---------------------------------------------------------------------------
# Marqueur unique, valeur fictive. On ne se sert JAMAIS d'un vrai mot de passe
# pour ce contrôle.
MARKER="DO_NOT_LOG_QUERY_TEST_$(openssl rand -hex 8)"
curl -s -o /dev/null --max-time 15 \
  "https://$POC_HOSTNAME/signin?email=probe%40triactis.test&password=$MARKER" || true
curl -s -o /dev/null --max-time 15 \
  "https://$POC_HOSTNAME/forgot-password?email=probe%40triactis.test&password=$MARKER" || true
sleep 4

hits=0
for svc in caddy documenso; do
  n="$(dc logs --no-color --tail=4000 "$svc" 2>/dev/null | grep -c "$MARKER" || true)"
  [[ "$n" -gt 0 ]] && { ko "marqueur trouvé $n fois dans les journaux $svc"; hits=$((hits + n)); }
done

# Journaux éventuellement écrits dans le volume de données de Caddy.
n="$(docker run --rm -v documenso-poc-caddy-data:/d alpine:3 \
      sh -c "grep -rl '$MARKER' /d 2>/dev/null | wc -l" 2>/dev/null || echo 0)"
[[ "$n" -gt 0 ]] && { ko "marqueur trouvé dans le volume de données Caddy"; hits=$((hits + n)); }

[[ "$hits" -eq 0 ]] && ok "marqueur absent des journaux Caddy, Documenso et du volume Caddy"

# ---------------------------------------------------------------------------
section "Ressources"
# ---------------------------------------------------------------------------
df -h / | awk 'NR==1 || /\/$/ {print "    " $0}'
free -h | awk 'NR<=2 {print "    " $0}'
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>/dev/null | sed 's/^/    /'

# ---------------------------------------------------------------------------
section "Erreurs applicatives récentes"
# ---------------------------------------------------------------------------
err="$(dc logs --no-color --tail=1500 documenso 2>/dev/null | grep -cE '"statusCode":5[0-9][0-9]|HTTP 5[0-9][0-9]' || true)"
[[ "${err:-0}" -eq 0 ]] && ok "aucune erreur 5xx répétée dans les 1500 dernières lignes" \
                        || warn "$err lignes évoquant une 5xx, à examiner"

printf '\n== Bilan : %d contrôle(s) en échec ==\n' "$FAILURES"
exit $(( FAILURES > 0 ? 1 : 0 ))
