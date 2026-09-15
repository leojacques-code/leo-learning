#!/usr/bin/env python3
"""
Espace de travail partagé Triactis, et recette depuis un second compte.

Exécuté SUR la VM par oracle/run.sh, après l'amorçage.

CE QU'IL FAIT
  1. rattache les comptes du domaine du cabinet à l'organisation qui porte les
     modèles de démonstration, avec le rôle MEMBER ;
  2. nomme cette organisation et son équipe « Triactis » ;
  3. prouve, depuis un second compte et par l'API, qu'il voit les modèles,
     qu'il peut en créer un document, que le courriel part, et que le
     destinataire signe sans compte Documenso.

CE QU'IL NE FAIT PAS
  Il ne déplace aucun modèle, ne supprime rien, ne touche à aucun mot de passe,
  ne modifie aucun document existant, et laisse intacts les espaces personnels
  des comptes rattachés, y compris leurs propres modèles.

CONFIDENTIALITÉ. Les journaux partent dans un job GitHub Actions public. Rien
ici n'écrit d'adresse complète, de mot de passe, de jeton ni de lien de
signature sur la sortie standard : les comptes sont désignés par leur
empreinte courte et leur domaine.
"""

import hashlib
import json
import pathlib
import secrets
import string
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from seed import (  # noqa: E402  (le chemin doit être posé avant l'import)
    Http, _prefill_for, _use_template, log, psql, wait_for_mail,
)

STATE = pathlib.Path("/opt/documenso-poc/state/seed-state.json")
CABINET_DOMAIN = "triactis.com"
WORKSPACE_NAME = "Triactis"


def fail(msg):
    print(f"[workspace] ERREUR : {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def note(msg):
    print(f"[workspace] {msg}", flush=True)


def ident(prefix):
    """Identifiant de la même forme que ceux générés par Documenso."""
    return prefix + "".join(secrets.choice(string.ascii_lowercase) for _ in range(16))


def ref(email):
    """Empreinte courte : suit un compte d'une ligne à l'autre sans le nommer."""
    return hashlib.md5(email.lower().encode()).hexdigest()[:6]


# ---------------------------------------------------------------------------
# Rattachement
# ---------------------------------------------------------------------------

def share_workspace(team_id):
    org_id = psql(f'SELECT "organisationId" FROM "Team" WHERE id = {team_id};')
    if not org_id:
        fail(f"organisation introuvable pour l'équipe {team_id}")

    # Le groupe interne par lequel passe un membre ordinaire. Il est déjà
    # relié à l'équipe : lui rattacher un compte suffit à lui ouvrir l'équipe.
    member_group = psql(
        'SELECT id FROM "OrganisationGroup" '
        f"WHERE \"organisationId\" = '{org_id}' "
        "AND type = 'INTERNAL_ORGANISATION' AND \"organisationRole\" = 'MEMBER' LIMIT 1;"
    )
    if not member_group:
        fail("groupe INTERNAL_ORGANISATION / MEMBER introuvable dans cette organisation")

    team_role = psql(
        'SELECT "teamRole" FROM "TeamGroup" '
        f"WHERE \"organisationGroupId\" = '{member_group}' AND \"teamId\" = {team_id};"
    )
    if not team_role:
        fail("ce groupe n'est relié à aucune équipe : le rattachement ne donnerait rien")
    note(f"organisation {org_id}, équipe {team_id}, groupe membre → rôle d'équipe {team_role}")

    rows = psql(
        'SELECT u.id, u.email FROM "User" u '
        f"WHERE lower(split_part(u.email, '@', 2)) = '{CABINET_DOMAIN}' "
        'AND NOT EXISTS (SELECT 1 FROM "OrganisationMember" m '
        f"WHERE m.\"userId\" = u.id AND m.\"organisationId\" = '{org_id}');"
    )
    pending = [r.split("|", 1) for r in rows.splitlines() if "|" in r]

    if not pending:
        note(f"aucun compte @{CABINET_DOMAIN} à rattacher : déjà fait")
    for user_id, email in pending:
        member_id = ident("member_")
        statements = [
            "BEGIN;",
            'INSERT INTO "OrganisationMember" '
            '(id, "createdAt", "updatedAt", "userId", "organisationId") '
            f"VALUES ('{member_id}', NOW(), NOW(), {user_id}, '{org_id}');",
            'INSERT INTO "OrganisationGroupMember" (id, "groupId", "organisationMemberId") '
            f"VALUES ('{ident('group_member_')}', '{member_group}', '{member_id}');",
            "COMMIT;",
        ]
        if psql(" ".join(statements)) is None:
            fail(f"rattachement du compte {ref(email)} refusé")
        note(f"compte {ref(email)}@{CABINET_DOMAIN} rattaché comme MEMBER")

    # Nommage, seulement si l'espace porte encore son nom par défaut : on ne
    # renomme jamais un espace que quelqu'un aurait déjà nommé lui-même.
    psql(
        f"UPDATE \"Organisation\" SET name = '{WORKSPACE_NAME}', \"updatedAt\" = NOW() "
        f"WHERE id = '{org_id}' AND name = 'Personal Organisation';"
    )
    psql(
        f"UPDATE \"Team\" SET name = '{WORKSPACE_NAME}' "
        f"WHERE id = {team_id} AND name = 'Personal Team';"
    )

    return org_id


def prove_membership(team_id):
    """Relit en base qui atteint l'équipe, et par quel rôle."""
    rows = psql(
        'SELECT u.id, split_part(u.email, \'@\', 2), tg."teamRole", u.email '
        'FROM "User" u '
        'JOIN "OrganisationMember" m ON m."userId" = u.id '
        'JOIN "OrganisationGroupMember" gm ON gm."organisationMemberId" = m.id '
        'JOIN "OrganisationGroup" g ON g.id = gm."groupId" '
        'JOIN "TeamGroup" tg ON tg."organisationGroupId" = g.id '
        f'WHERE tg."teamId" = {team_id} ORDER BY u.id;'
    )
    members = []
    for row in rows.splitlines():
        parts = row.split("|")
        if len(parts) < 4:
            continue
        members.append({"userId": int(parts[0]), "domain": parts[1],
                        "teamRole": parts[2], "ref": ref(parts[3])})
    note(f"membres de l'équipe {team_id} :")
    for m in members:
        note(f"  compte {m['ref']}@{m['domain']} · rôle {m['teamRole']}")
    return members


# ---------------------------------------------------------------------------
# Recette depuis le second compte
# ---------------------------------------------------------------------------

def temp_token(user_id, team_id):
    """
    Jeton d'API temporaire au nom du second compte.

    Documenso stocke le SHA-512 hexadécimal du jeton, jamais le jeton lui-même.
    Il est détruit à la fin de la recette. Le mot de passe du compte n'est ni
    lu, ni modifié : c'est précisément ce qu'on cherche à éviter.
    """
    token = "api_" + secrets.token_hex(24)
    digest = hashlib.sha512(token.encode()).hexdigest()
    row = psql(
        'INSERT INTO "ApiToken" (name, token, "userId", "teamId", "createdAt") '
        f"VALUES ('Recette second compte (temporaire)', '{digest}', {user_id}, {team_id}, NOW()) "
        "RETURNING id;"
    )
    if not row.strip().isdigit():
        fail("création du jeton temporaire impossible")
    return token, int(row.strip())


def drop_token(token_id):
    psql(f'DELETE FROM "ApiToken" WHERE id = {token_id};')
    note("jeton temporaire du second compte détruit")


def second_account_test(state, members, team_id):
    poc_user = int(psql(
        'SELECT o."ownerUserId" FROM "Team" t '
        'JOIN "Organisation" o ON o.id = t."organisationId" '
        f"WHERE t.id = {team_id};"
    ) or 0)
    others = [m for m in members if m["userId"] != poc_user
              and m["domain"].lower() == CABINET_DOMAIN]
    if not others:
        note("aucun second compte du cabinet dans l'équipe : recette non applicable")
        return {"applicable": False}

    target = others[0]
    note(f"recette depuis le compte {target['ref']}@{target['domain']} (rôle {target['teamRole']})")

    token, token_id = temp_token(target["userId"], team_id)
    result = {"applicable": True, "ref": target["ref"], "teamRole": target["teamRole"]}
    try:
        http = Http("http://127.0.0.1:3000")
        http.token = token
        http.team_id = team_id

        status, out = http.v2("GET", "/template?perPage=50")
        if status >= 400:
            fail(f"le second compte ne peut pas lister les modèles (HTTP {status})")
        titles = [t.get("title", "") for t in (out or {}).get("data", [])]
        result["templatesVisible"] = titles
        note(f"modèles visibles depuis ce compte : {len(titles)}")
        for t in titles:
            note(f"  · {t}")

        tpl = (state.get("templates") or {}).get("nda_acquereur")
        if not tpl:
            fail("modèle NDA Acquéreur absent de l'état d'amorçage")
        if tpl["title"] not in titles:
            fail("le second compte ne voit pas le modèle NDA Acquéreur")
        result["seesNdaAcquereur"] = True

        prefill = _prefill_for(http, tpl, {"societe": "GAMMA PATRIMOINE SAS",
                                           "fonction": "Directeur general"})
        status, out = _use_template(
            http, tpl,
            [{"id": tpl["recipients"][0]["id"], "email": "claire.durand@example.test",
              "name": "Claire Durand"}],
            prefill, "DEAL-DEMO-004",
            "Projet Gamma - NDA Acquereur - GAMMA PATRIMOINE SAS", True,
        )
        if status >= 400 or not isinstance(out, dict):
            fail(f"création du document depuis le second compte refusée (HTTP {status}) : "
                 f"{json.dumps(out)[:400]}")
        envelope_id = out["id"]
        recipients = out.get("recipients", [])
        signing_token = (recipients[0].get("signingUrl") or "").rstrip("/").split("/")[-1]
        result["documentCreated"] = True
        note("document créé depuis le modèle partagé, par le second compte")

        owner = psql(f"SELECT \"userId\", \"teamId\" FROM \"Envelope\" WHERE id = '{envelope_id}';")
        result["documentOwner"] = owner
        note(f"document attribué à userId|teamId = {owner}")

        mail = wait_for_mail("claire.durand@example.test")
        result["mailReceived"] = bool(mail)
        note("courriel d'invitation : " + ("reçu dans Mailpit" if mail else "NON reçu"))

        # Le destinataire signe sans compte Documenso : jeton de destinataire.
        status, detail = http.v2("GET", f"/envelope/{envelope_id}")
        document_id = None
        sid = (detail or {}).get("secondaryId") or ""
        if "_" in sid and sid.rsplit("_", 1)[-1].isdigit():
            document_id = int(sid.rsplit("_", 1)[-1])

        signed = 0
        for field in (detail or {}).get("fields", []):
            if field.get("recipientId") != recipients[0]["id"]:
                continue
            ftype = field["type"]
            if ftype == "DATE":
                value = {"type": "DATE", "value": True}
            elif ftype == "EMAIL":
                value = {"type": "EMAIL", "value": "claire.durand@example.test"}
            elif ftype == "NAME":
                value = {"type": "NAME", "value": "Claire Durand"}
            elif ftype == "SIGNATURE":
                value = {"type": "SIGNATURE", "value": "Claire Durand"}
            elif ftype == "TEXT":
                meta = field.get("fieldMeta") or {}
                label = (meta.get("label") or "").lower()
                value = {"type": "TEXT", "value": "GAMMA PATRIMOINE SAS"
                         if "societ" in label else "Directeur general"}
            else:
                continue
            status, _ = http.trpc("envelope.field.sign", {
                "token": signing_token, "fieldId": field["id"], "fieldValue": value})
            if status < 400:
                signed += 1
        result["fieldsSigned"] = signed
        note(f"{signed} champs signés par le destinataire, sans compte Documenso")

        if document_id:
            http.trpc("recipient.completeDocumentWithToken",
                      {"token": signing_token, "documentId": document_id})

        final = ""
        for _ in range(45):
            status, detail = http.v2("GET", f"/envelope/{envelope_id}")
            final = (detail or {}).get("status", "")
            if final == "COMPLETED":
                break
            time.sleep(4)
        result["finalStatus"] = final
        note(f"statut final du document créé par le second compte : {final}")
    finally:
        drop_token(token_id)

    return result


# ---------------------------------------------------------------------------

def main():
    if not STATE.exists():
        fail("état d'amorçage absent : rien à partager")
    state = json.loads(STATE.read_text())
    team_id = state.get("team_id")
    if not isinstance(team_id, int):
        fail("identifiant d'équipe absent de l'état d'amorçage")

    share_workspace(team_id)
    members = prove_membership(team_id)
    outcome = second_account_test(state, members, team_id)

    state["workspace"] = {
        "teamId": team_id,
        "name": WORKSPACE_NAME,
        "members": members,
        "secondAccountTest": outcome,
    }
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    STATE.chmod(0o600)
    log("espace partagé à jour")
    return 0


if __name__ == "__main__":
    sys.exit(main())
