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
for k in NEXT_PUBLIC_DISABLE_SIGNUP NEXT_PRIVATE_ALLOWED_SIGNUP_DOMAINS; do
  v="$(docker inspect documenso-poc-app \
        --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
        | awk -F= -v key="$k" '$1 == key { sub(/^[^=]*=/, ""); print; exit }')"
  printf '  %s = %s\n' "$k" "${v:-<absent>}"
done

section "Comptes"
q "select id,
          substr(md5(lower(email)), 1, 6) as ref,
          split_part(email, '@', 2) as domaine,
          \"createdAt\"::date as cree_le
   from \"User\" order by id;"

section "Organisations et equipes"
q "select o.id as organisation, o.name as nom_org, o.\"ownerUserId\" as proprietaire,
          t.id as team, t.name as nom_team
   from \"Organisation\" o join \"Team\" t on t.\"organisationId\" = o.id
   order by t.id;"

section "Qui atteint quelle equipe, et avec quel role"
q "select tg.\"teamId\" as team,
          u.id as compte,
          substr(md5(lower(u.email)), 1, 6) as ref,
          split_part(u.email, '@', 2) as domaine,
          g.\"organisationRole\" as role_org,
          tg.\"teamRole\" as role_team
   from \"User\" u
   join \"OrganisationMember\" m on m.\"userId\" = u.id
   join \"OrganisationGroupMember\" gm on gm.\"organisationMemberId\" = m.id
   join \"OrganisationGroup\" g on g.id = gm.\"groupId\"
   join \"TeamGroup\" tg on tg.\"organisationGroupId\" = g.id
   order by tg.\"teamId\", u.id;"

section "Modeles"
q "select id, title, visibility, \"externalId\", \"teamId\", \"userId\"
   from \"Envelope\" where type = 'TEMPLATE' order by \"teamId\", id;"

section "Destinataires et champs par modele"
q "select e.id, left(e.title, 38) as titre,
          (select count(*) from \"Recipient\" r where r.\"envelopeId\" = e.id) as dest,
          (select count(*) from \"Field\" f where f.\"envelopeId\" = e.id) as champs
   from \"Envelope\" e where e.type = 'TEMPLATE' order by e.id;"

section "Enveloppes par type, statut et espace"
q "select type, status, \"teamId\", \"userId\", count(*) as n
   from \"Envelope\" group by 1,2,3,4 order by 1,2,3,4;"

section "Jetons d'API (jamais la valeur du jeton)"
q "select id, name, \"userId\", \"teamId\", expires from \"ApiToken\" order by id;"

section "Lien direct et webhooks"
q "select id, \"envelopeId\", enabled from \"TemplateDirectLink\" order by id;"
q "select id, enabled, \"userId\", \"teamId\" from \"Webhook\" order by id;"

section "Compte rendu de l'espace partage"
# Deja consigne par oracle/workspace.py dans l'etat d'amorcage. Ne contient ni
# adresse complete, ni jeton, ni lien de signature : uniquement des empreintes,
# des domaines, des roles et des statuts.
python3 - "$POC_STATE_DIR/state/seed-state.json" <<'PY' 2>&1 | sed 's/^/  /'
import json, sys
try:
    state = json.load(open(sys.argv[1]))
except Exception as exc:
    print(f"etat d'amorcage illisible : {exc}")
    raise SystemExit(0)
report = state.get("workspace")
if not report:
    print("aucun compte rendu : la mise en partage n'a pas encore tourne")
else:
    print(json.dumps(report, indent=2, ensure_ascii=False))
PY

section "Etat du fichier d'amorcage"
if [[ -f "$POC_STATE_DIR/state/seed-state.json" ]]; then
  printf '  seed-state.json : present, %s octets, permissions %s\n' \
    "$(stat -c %s "$POC_STATE_DIR/state/seed-state.json")" \
    "$(stat -c %a "$POC_STATE_DIR/state/seed-state.json")"
else
  printf '  seed-state.json : absent\n'
fi

printf '\n== Inventaire termine, aucune ecriture effectuee ==\n'
