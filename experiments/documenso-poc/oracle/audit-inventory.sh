#!/usr/bin/env bash
#
# Inventaire applicatif du POC, en LECTURE SEULE.
#
# N'ecrit rien. N'affiche jamais de valeur sensible : ni mot de passe, ni
# jeton d'API, ni lien de signature, ni cookie, ni jeton de verification.
# Les adresses sont reduites a leur domaine et a une empreinte courte,
# suffisante pour suivre un compte d'une section a l'autre sans publier
# l'adresse dans un journal public.
#
# Le schema est cartographie avant d'etre interroge : le modele de donnees
# des organisations et des equipes differe entre versions majeures de
# Documenso. Les requetes hors schema echouent individuellement, sans
# interrompre l'inventaire (ON_ERROR_STOP reste a 0).

set -uo pipefail

POC_STATE_DIR=/opt/documenso-poc
POC_SRC_DIR=/opt/leo-learning/experiments/documenso-poc

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

q() {
  dc exec -T database psql -U documenso -d documenso_poc \
    -v ON_ERROR_STOP=0 -P pager=off -c "$1" 2>&1 | sed 's/^/  /'
}

section "Configuration effective du conteneur applicatif"
for k in NEXT_PUBLIC_DISABLE_SIGNUP NEXT_PRIVATE_ALLOWED_SIGNUP_DOMAINS NEXT_PUBLIC_WEBAPP_URL; do
  v="$(docker inspect documenso-poc-app \
        --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
        | awk -F= -v key="$k" '$1 == key { sub(/^[^=]*=/, ""); print; exit }')"
  printf '  %s = %s\n' "$k" "${v:-<absent>}"
done

section "Tables presentes"
q "select table_name from information_schema.tables
   where table_schema = 'public' order by table_name;"

section "Colonnes des tables d'identite, d'organisation et de modele"
q "select table_name, string_agg(column_name, ', ' order by ordinal_position) as colonnes
   from information_schema.columns
   where table_schema = 'public'
     and table_name ~* '(user|organisation|organization|team|member|group|template|envelope|apitoken|webhook)'
   group by table_name order by table_name;"

section "Comptes"
q "select id,
          substr(md5(lower(email)), 1, 6) as ref,
          split_part(email, '@', 2) as domaine,
          \"createdAt\"::date as cree_le
   from \"User\" order by id;"

section "Organisations"
q "select * from \"Organisation\" order by id;"
q "select id, name, \"ownerUserId\" from \"Organisation\" order by id;"

section "Appartenances aux organisations"
q "select * from \"OrganisationMember\" order by 1;"

section "Groupes d'organisation et leurs membres"
q "select * from \"OrganisationGroup\" order by 1;"
q "select * from \"OrganisationGroupMember\" order by 1;"

section "Equipes"
q "select * from \"Team\" order by id;"

section "Appartenances aux equipes"
q "select * from \"TeamMember\" order by 1;"
q "select * from \"TeamGroup\" order by 1;"

section "Modeles"
q "select id, type, title, \"templateType\", visibility, \"externalId\",
          \"teamId\", \"userId\", \"createdAt\"::date as cree_le
   from \"Envelope\" where type = 'TEMPLATE' order by id;"
q "select id, title, \"templateType\", visibility, \"externalId\",
          \"teamId\", \"userId\", \"createdAt\"::date as cree_le
   from \"Template\" order by id;"

section "Destinataires et champs par modele"
q "select e.id, left(e.title, 40) as titre,
          (select count(*) from \"Recipient\" r where r.\"envelopeId\" = e.id) as destinataires,
          (select count(*) from \"Field\" f where f.\"envelopeId\" = e.id) as champs
   from \"Envelope\" e where e.type = 'TEMPLATE' order by e.id;"

section "Documents et enveloppes"
q "select type, status, visibility, \"teamId\", count(*) as n
   from \"Envelope\" group by 1, 2, 3, 4 order by 1, 2, 3, 4;"
q "select id, type, status, left(title, 45) as titre, \"teamId\", \"userId\",
          \"externalId\", \"createdAt\"::date as cree_le
   from \"Envelope\" order by id;"

section "Jetons d'API (jamais la valeur du jeton)"
q "select id, name, \"userId\", \"teamId\", expires, \"createdAt\"::date as cree_le
   from \"ApiToken\" order by id;"

section "Lien direct et webhooks"
q "select id, \"envelopeId\", token is not null as jeton_present, enabled
   from \"TemplateDirectLink\" order by id;"
q "select id, \"webhookUrl\" is not null as url_presente, enabled,
          \"eventTriggers\", \"userId\", \"teamId\"
   from \"Webhook\" order by id;"

section "Etat du fichier d'amorcage"
if [[ -f "$POC_STATE_DIR/state/seed-state.json" ]]; then
  printf '  seed-state.json : present, %s octets, permissions %s\n' \
    "$(stat -c %s "$POC_STATE_DIR/state/seed-state.json")" \
    "$(stat -c %a "$POC_STATE_DIR/state/seed-state.json")"
  printf '  cles presentes : %s\n' \
    "$(python3 -c "import json;print(', '.join(sorted(json.load(open('$POC_STATE_DIR/state/seed-state.json')).keys())))" 2>&1)"
else
  printf '  seed-state.json : absent\n'
fi

printf '\n== Inventaire termine, aucune ecriture effectuee ==\n'
