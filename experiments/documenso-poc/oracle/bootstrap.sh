#!/usr/bin/env bash
#
# Préparation de la VM Oracle Cloud pour le POC Documenso.
#
# IDEMPOTENT : conçu pour être relancé à chaque déploiement sans rien casser.
# Chaque action vérifie d'abord si elle est déjà faite.
#
# Ce script n'installe QUE ce dont la pile a besoin :
#   git, curl, ca-certificates, openssl, jq, python3, Docker, Compose v2.
# Pas de Node, pas de PostgreSQL hôte, pas de Nginx, pas de Portainer.
#
# Il ne journalise jamais de secret : il n'en manipule aucun.

set -euo pipefail

log() { printf '[bootstrap] %s\n' "$*"; }

# ---------------------------------------------------------------------------
# 1. Contrôles de plateforme
# ---------------------------------------------------------------------------
ARCH="$(uname -m)"
log "architecture : $ARCH"
log "noyau        : $(uname -r)"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  log "système      : ${PRETTY_NAME:-inconnu}"
fi

if [[ "$ARCH" != "aarch64" && "$ARCH" != "arm64" ]]; then
  log "AVERTISSEMENT : architecture inattendue ($ARCH). La recette vise ARM64."
fi

# ---------------------------------------------------------------------------
# 2. Paquets de base
# ---------------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive

need_pkg=()
for p in git curl ca-certificates openssl jq python3 gnupg iptables-persistent; do
  dpkg -s "$p" >/dev/null 2>&1 || need_pkg+=("$p")
done

if ((${#need_pkg[@]})); then
  log "installation : ${need_pkg[*]}"
  # iptables-persistent pose deux questions debconf ; on y répond d'avance.
  echo 'iptables-persistent iptables-persistent/autosave_v4 boolean false' | sudo debconf-set-selections
  echo 'iptables-persistent iptables-persistent/autosave_v6 boolean false' | sudo debconf-set-selections
  sudo apt-get update -qq
  sudo apt-get install -y -qq "${need_pkg[@]}"
else
  log "paquets de base : déjà présents"
fi

# ---------------------------------------------------------------------------
# 3. Docker Engine + Compose v2, dépôt officiel Docker
# ---------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  log "installation de Docker depuis le dépôt officiel"
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$(dpkg --print-architecture)" "$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
else
  log "Docker : déjà présent"
fi

if ! docker compose version >/dev/null 2>&1; then
  log "installation du plugin Compose v2"
  sudo apt-get install -y -qq docker-compose-plugin
fi

log "docker  : $(docker --version)"
log "compose : $(docker compose version --short 2>/dev/null || echo inconnu)"

# Docker doit repartir seul après un reboot. C'est ce qui rend le test de
# redémarrage de la VM significatif.
sudo systemctl enable --now docker >/dev/null 2>&1 || true
sudo systemctl is-enabled docker >/dev/null 2>&1 \
  && log "docker.service : activé au démarrage" \
  || log "AVERTISSEMENT : docker.service n'est pas activé au démarrage"

# L'utilisateur courant doit pouvoir parler au démon sans sudo.
if ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
  log "ajout de $USER au groupe docker"
  sudo usermod -aG docker "$USER"
  log "note : la nouvelle appartenance de groupe ne vaut qu'à la prochaine session."
fi

# ---------------------------------------------------------------------------
# 4. Pare-feu hôte : 22, 80, 443 et rien d'autre en entrée
# ---------------------------------------------------------------------------
# Les images Ubuntu d'Oracle arrivent avec une chaîne INPUT restrictive. On
# n'y touche que par AJOUT de règles ACCEPT : jamais de changement de
# politique, jamais de flush. Une erreur ici couperait SSH.
add_input_accept() {
  local port="$1"
  if sudo iptables -C INPUT -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null; then
    log "iptables : $port/tcp déjà autorisé"
  else
    log "iptables : autorisation de $port/tcp"
    sudo iptables -I INPUT 1 -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT
  fi
}
add_input_accept 22
add_input_accept 80
add_input_accept 443

sudo mkdir -p /etc/iptables
sudo sh -c 'iptables-save > /etc/iptables/rules.v4' || log "AVERTISSEMENT : sauvegarde iptables impossible"

# ufw n'est pas utilisé : il entrerait en conflit avec les chaînes Docker.
if command -v ufw >/dev/null 2>&1 && sudo ufw status 2>/dev/null | grep -q '^Status: active'; then
  log "AVERTISSEMENT : ufw est actif, vérifier qu'il autorise 80 et 443"
fi

# ---------------------------------------------------------------------------
# 5. Durcissement SSH
# ---------------------------------------------------------------------------
# Écrit dans un drop-in, validé par `sshd -t` AVANT tout rechargement. Si la
# configuration obtenue est invalide, le drop-in est retiré et rien n'est
# rechargé : la session SSH en cours ne peut pas être perdue.
SSHD_DROPIN=/etc/ssh/sshd_config.d/99-documenso-poc.conf
SSHD_WANTED=$(cat <<'EOF'
# Durcissement POC Documenso. Clé uniquement, pas de root.
PasswordAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
EOF
)

if [[ -d /etc/ssh/sshd_config.d ]] && grep -q '^Include /etc/ssh/sshd_config.d/' /etc/ssh/sshd_config 2>/dev/null; then
  if [[ -f "$SSHD_DROPIN" ]] && [[ "$(sudo cat "$SSHD_DROPIN")" == "$SSHD_WANTED" ]]; then
    log "SSH : durcissement déjà en place"
  else
    log "SSH : application du durcissement"
    printf '%s\n' "$SSHD_WANTED" | sudo tee "$SSHD_DROPIN" >/dev/null
    if sudo sshd -t; then
      sudo systemctl reload ssh 2>/dev/null || sudo systemctl reload sshd 2>/dev/null || true
      log "SSH : configuration valide, service rechargé"
    else
      log "ERREUR : configuration sshd invalide, retour en arrière"
      sudo rm -f "$SSHD_DROPIN"
      sudo sshd -t && log "SSH : état antérieur rétabli"
    fi
  fi
else
  log "AVERTISSEMENT : pas de sshd_config.d exploitable, durcissement SSH ignoré"
fi

# Les distributions récentes désactivent aussi les mots de passe depuis
# cloud-init ; on ne touche pas à ces fichiers pour ne pas créer de conflit.

# ---------------------------------------------------------------------------
# 6. Arborescence d'exécution, hors dépôt Git
# ---------------------------------------------------------------------------
sudo mkdir -p /opt/documenso-poc/{certs,state,demo,webhook,artifacts}
sudo chown -R "$USER":"$USER" /opt/documenso-poc
chmod 700 /opt/documenso-poc/certs /opt/documenso-poc/artifacts
chmod 755 /opt/documenso-poc /opt/documenso-poc/demo

sudo mkdir -p /var/backups/documenso-poc
sudo chown "$USER":"$USER" /var/backups/documenso-poc
sudo chmod 700 /var/backups/documenso-poc

log "bootstrap terminé"
