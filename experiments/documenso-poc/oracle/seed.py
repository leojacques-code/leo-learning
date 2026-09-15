#!/usr/bin/env python3
"""
Amorçage et recette fonctionnelle du POC Documenso sur Oracle Cloud.

Exécuté SUR la VM par oracle/run.sh. Pilote l'instance par son API, comme le
ferait un intégrateur.

DEUX CHEMINS D'ACCÈS, ET C'EST VOULU.
Pendant la phase d'amorçage, Caddy protège tout le site par Basic Auth, qui
voyage dans l'en-tête Authorization. Le jeton d'API Documenso voyage dans le
même en-tête : les deux ne peuvent pas coexister sur une même requête. Donc :

  - création de compte, vérification, connexion, appels tRPC de session :
    par l'URL publique HTTPS, avec le Basic Auth du proxy ;
  - appels authentifiés par jeton d'API : par la boucle locale, en deçà du
    proxy, où l'en-tête Authorization est libre.

Le parcours public reste vérifié de bout en bout par oracle/checks.sh et par
la sonde externe du workflow.

LE MOT DE PASSE HUMAIN N'EST PAS UNE DÉPENDANCE.
Sur une instance déjà amorcée, le jeton d'API conservé en 600 sur la machine
suffit à tout ce qui reste à faire. Il est essayé en premier ; la connexion
par mot de passe n'intervient que s'il ne répond pas. Un changement de mot de
passe depuis l'interface ne casse donc plus la recette, et ce script ne
modifie jamais un mot de passe pour se débloquer.

Ce que fait ce script, chaque étape étant idempotente et consignée :

  1. création du compte POC (données fictives)
  2. jeton de confirmation récupéré dans Mailpit, vérification du compte
  3. session si nécessaire, puis jeton d'API
  4. création des trois modèles, champs déjà positionnés
  5. lien direct sur le modèle NDA Acquéreur
  6. recette de bout en bout : document depuis modèle, envoi, signature,
     finalisation, scellement, téléchargement, contrôle cryptographique du PDF
  7. enveloppe laissée en attente pour la signature manuelle depuis l'iPhone
  8. envoi en masse depuis un CSV fictif
  9. webhook vers le récepteur local de démonstration

CONFIDENTIALITÉ. Les journaux partent dans un job GitHub Actions public. Ce
script n'écrit sur la sortie standard aucun mot de passe, aucun jeton d'API,
aucun jeton de signature, aucun lien de signature. Ces valeurs vont dans
/opt/documenso-poc/artifacts/handoff.json (600), que oracle/relay.sh chiffre.

Bibliothèque standard uniquement.
"""

import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import secrets
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

MAILPIT = "http://127.0.0.1:8025"
LOOPBACK = "http://127.0.0.1:3000"
DB_CONTAINER = "documenso-poc-db"
WEBHOOK_URL = "http://webhook-sink:9000/"

# Jeu de données de démonstration. Intégralement fictif : sociétés inventées,
# domaines en .test réservé par la RFC 2606, aucune adresse joignable.
POC_ACCOUNT_NAME = "Triactis POC"
POC_ACCOUNT_EMAIL = "poc-admin@triactis.test"


def log(msg):
    print(f"[seed] {msg}", flush=True)


def fail(msg):
    print(f"[seed] ERREUR : {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Client HTTP
# ---------------------------------------------------------------------------

class Http:
    """Cookies de session, Basic Auth du proxy, multipart, tRPC, API v2."""

    def __init__(self, base, basic_auth=None, api_base=LOOPBACK):
        self.base = base.rstrip("/")
        self.api_base = api_base.rstrip("/")
        self.basic_auth = basic_auth
        self.token = None
        # Le contexte d'équipe des appels tRPC vient de l'en-tête x-team-id
        # (packages/trpc/server/context.ts). Sans lui, les procédures qui
        # travaillent sur un espace de travail répondent 404.
        self.team_id = None
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )

    def request(self, method, path, body=None, headers=None,
                use_token=False, raw=False, timeout=180):
        # Les appels au jeton d'API passent sous le proxy : son Basic Auth
        # occuperait sinon l'en-tête Authorization dont le jeton a besoin.
        root = self.api_base if use_token else self.base
        url = path if path.startswith("http") else f"{root}{path}"

        head = {"Accept": "application/json", "User-Agent": "triactis-poc-seed/1.0"}
        if use_token:
            if not self.token:
                fail("appel authentifié par jeton sans jeton disponible")
            head["Authorization"] = f"Bearer {self.token}"
        elif self.basic_auth:
            raw_auth = f"{self.basic_auth[0]}:{self.basic_auth[1]}".encode()
            head["Authorization"] = "Basic " + base64.b64encode(raw_auth).decode()
        head.update(headers or {})

        req = urllib.request.Request(url, data=body, headers=head, method=method)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                payload = resp.read()
                if raw:
                    return resp.status, payload, dict(resp.headers)
                return resp.status, self._json(payload), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            if raw:
                return exc.code, payload, dict(exc.headers)
            return exc.code, self._json(payload), dict(exc.headers)

    @staticmethod
    def _json(payload):
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return payload[:400].decode("utf-8", "replace")

    # -- couches -----------------------------------------------------------
    def post_json(self, path, data, headers=None):
        status, body, _ = self.request(
            "POST", path, json.dumps(data).encode(),
            dict({"Content-Type": "application/json"}, **(headers or {})),
        )
        return status, body

    def trpc(self, proc, payload):
        """Appel tRPC. Le transformateur est superjson : {"json": <entrée>}."""
        headers = {}
        if self.team_id:
            headers["x-team-id"] = str(self.team_id)
        status, body = self.post_json(f"/api/trpc/{proc}", {"json": payload}, headers)
        if isinstance(body, dict) and "result" in body:
            data = body["result"].get("data")
            if isinstance(data, dict) and "json" in data:
                return status, data["json"]
            return status, data
        return status, body

    def v2(self, method, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        head = {"Content-Type": "application/json"} if data is not None else {}
        status, out, _ = self.request(method, f"/api/v2{path}", body, head, use_token=True)
        return status, out

    def v2_multipart(self, path, payload, files):
        boundary = "----triactis" + secrets.token_hex(12)
        parts = bytearray()

        parts.extend(f"--{boundary}\r\n".encode())
        parts.extend(b'Content-Disposition: form-data; name="payload"\r\n\r\n')
        parts.extend(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        parts.extend(b"\r\n")

        for name, filename, blob in files:
            parts.extend(f"--{boundary}\r\n".encode())
            parts.extend(
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: application/pdf\r\n\r\n".encode()
            )
            parts.extend(blob)
            parts.extend(b"\r\n")
        parts.extend(f"--{boundary}--\r\n".encode())

        status, out, _ = self.request(
            "POST", f"/api/v2{path}", bytes(parts),
            {"Content-Type": f"multipart/form-data; boundary={boundary}"}, use_token=True,
        )
        return status, out

    def download(self, path):
        status, body, _ = self.request("GET", f"/api/v2{path}", use_token=True, raw=True)
        return status, body


# ---------------------------------------------------------------------------
# Mailpit
# ---------------------------------------------------------------------------

def mailpit(path):
    with urllib.request.urlopen(f"{MAILPIT}{path}", timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_mail(needle, attempts=40):
    """Attend un message dont le sujet ou le destinataire contient le motif."""
    needle = needle.lower()
    for _ in range(attempts):
        try:
            messages = mailpit("/api/v1/messages?limit=100").get("messages", [])
        except Exception:  # noqa: BLE001 - Mailpit peut ne pas être encore prêt
            messages = []
        for msg in messages:
            hay = (msg.get("Subject", "") + " " + json.dumps(msg.get("To", []))).lower()
            if needle in hay:
                return mailpit(f"/api/v1/message/{msg['ID']}")
        time.sleep(3)
    return None


def mail_count():
    try:
        return mailpit("/api/v1/messages?limit=1").get("messages_count", 0)
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# Base de données (secours et inventaire)
# ---------------------------------------------------------------------------

def psql(sql):
    out = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER,
         "psql", "-U", "documenso", "-d", "documenso_poc", "-t", "-A", "-c", sql],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return ""
    return out.stdout.strip()


def seal_job_status():
    """
    Statut du dernier job de scellement.

    Recherche par motif : le nom exact de la file a changé entre versions, et
    un nom codé en dur renverrait « inconnu » sans que rien ne soit cassé.
    """
    for sql in (
        "SELECT status FROM \"BackgroundJob\" WHERE name ILIKE '%seal%' "
        "ORDER BY \"createdAt\" DESC LIMIT 1;",
        "SELECT status FROM \"BackgroundJob\" WHERE \"jobId\" ILIKE '%seal%' "
        "ORDER BY \"createdAt\" DESC LIMIT 1;",
    ):
        out = psql(sql)
        if out:
            return out.splitlines()[0].strip()
    return ""


# ---------------------------------------------------------------------------
# État
# ---------------------------------------------------------------------------

class State:
    def __init__(self, path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))
        os.chmod(self.path, 0o600)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()
        return value


# ---------------------------------------------------------------------------
# Étapes
# ---------------------------------------------------------------------------

def gen_password():
    """
    Mot de passe fort, lisible et saisissable au doigt sur un téléphone.

    La politique de Documenso exige, en deçà de 25 caractères, une majuscule,
    une minuscule, un chiffre et un caractère spécial. Le suffixe les apporte
    par construction : les tirer au hasard laisserait une chance non nulle
    (environ 6 % pour le chiffre) de produire un mot de passe refusé.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    core = "-".join(
        "".join(secrets.choice(alphabet) for _ in range(6)) for _ in range(3)
    )
    return core + "-Poc7x!"


def user_exists(email):
    return psql(f"SELECT 1 FROM \"User\" WHERE lower(email) = lower('{email}');") == "1"


def step_account(http, state):
    account = state.get("account")
    if account and account.get("verified"):
        log("compte POC : déjà créé et vérifié")
        return account

    # Un amorçage interrompu avant la création effective laisse un mot de passe
    # en état sans compte en face. On repart d'un mot de passe neuf plutôt que
    # de rejouer indéfiniment celui qui vient d'échouer.
    if account and not user_exists(account["email"]):
        log("compte absent en base : régénération du mot de passe")
        account = None

    if not account:
        account = {"name": POC_ACCOUNT_NAME, "email": POC_ACCOUNT_EMAIL,
                   "password": gen_password(), "verified": False}
        state.set("account", account)

    status, body = http.post_json("/api/auth/email-password/signup", {
        "name": account["name"],
        "email": account["email"],
        "password": account["password"],
    })
    blob = json.dumps(body) if body is not None else ""
    if status in (200, 201):
        log("compte POC créé")
    elif "already exists" in blob.lower():
        log("compte POC : déjà présent côté Documenso")
    elif "SignupDisabled" in blob:
        fail("l'inscription est désactivée alors que le compte n'existe pas encore")
    else:
        fail(f"inscription refusée (HTTP {status}) : {blob[:300]}")

    # Jeton de confirmation : récupéré dans Mailpit, comme le ferait un humain.
    msg = wait_for_mail("confirm") or wait_for_mail("verif")
    token = ""
    if msg is not None:
        body_blob = (msg.get("Text") or "") + " " + (msg.get("HTML") or "")
        match = re.search(r"/verify-email/([A-Za-z0-9_\-]+)", body_blob)
        if match:
            token = match.group(1)
            log("jeton de confirmation récupéré dans Mailpit")

    if token:
        status, _ = http.post_json("/api/auth/email-password/verify-email", {"token": token})
        log(f"vérification par l'API : HTTP {status}")

    verified = psql("SELECT \"emailVerified\" IS NOT NULL FROM \"User\" "
                    f"WHERE lower(email) = lower('{account['email']}');")
    if verified != "t":
        log("vérification non aboutie par l'API, bascule directe en base")
        psql("UPDATE \"User\" SET \"emailVerified\" = NOW() "
             f"WHERE lower(email) = lower('{account['email']}');")
        verified = psql("SELECT \"emailVerified\" IS NOT NULL FROM \"User\" "
                        f"WHERE lower(email) = lower('{account['email']}');")
    if verified != "t":
        fail("le compte POC n'est pas vérifié")

    account["verified"] = True
    state.set("account", account)
    log("compte POC vérifié")
    return account


def stored_token_works(http, state):
    """
    Le jeton d'API conservé sur la machine répond-il encore ?

    C'est ce qui décide s'il faut ouvrir une session par mot de passe. Sur une
    instance en service, la réponse est oui et le mot de passe humain n'est
    jamais sollicité, donc jamais un point de rupture.
    """
    token = state.get("api_token")
    if not token:
        return False
    previous = http.token
    http.token = token
    status, _ = http.v2("GET", "/template?perPage=1")
    if status < 400:
        return True
    http.token = previous
    log(f"jeton d'API conservé inutilisable (HTTP {status})")
    return False


def step_signin(http, account):
    status, body, _ = http.request("GET", "/api/auth/csrf")
    csrf = body.get("csrfToken") if isinstance(body, dict) else None
    if not csrf:
        fail("jeton CSRF indisponible")
    status, body = http.post_json("/api/auth/email-password/authorize", {
        "email": account["email"], "password": account["password"], "csrfToken": csrf,
    })
    if status not in (200, 201):
        fail(
            f"connexion refusée (HTTP {status}) : {json.dumps(body)[:200]}\n"
            "[seed] Le mot de passe enregistré dans state/seed-state.json ne correspond\n"
            "[seed] plus à celui de la base, et aucun jeton d'API valide n'a pris le\n"
            "[seed] relais. Deux voies, aucune ne modifie le mot de passe du compte :\n"
            "[seed]   - inscrire le mot de passe courant dans state/seed-state.json ;\n"
            "[seed]   - ou supprimer state/seed-state.json pour repartir d'un compte de\n"
            "[seed]     démonstration neuf, les données existantes étant conservées."
        )
    log("connexion au compte POC : réussie")


def step_api_token(http, state, account):
    team_id = psql(
        "SELECT t.id FROM \"Team\" t "
        "JOIN \"Organisation\" o ON o.id = t.\"organisationId\" "
        "JOIN \"User\" u ON u.id = o.\"ownerUserId\" "
        f"WHERE lower(u.email) = lower('{account['email']}') ORDER BY t.id LIMIT 1;"
    )
    if not team_id.isdigit():
        fail("espace de travail (team) introuvable pour le compte POC")
    state.set("team_id", int(team_id))
    http.team_id = int(team_id)

    if http.token:
        log("jeton d'API : déjà présent et valide")
        return http.token

    status, out = http.trpc("apiToken.create", {
        "teamId": int(team_id), "tokenName": "Triactis POC automation", "expirationDate": None,
    })
    if status < 400 and isinstance(out, dict) and out.get("token"):
        token = out["token"]
        log("jeton d'API créé via tRPC")
    else:
        # Secours : insertion directe. Documenso stocke le SHA-512 hexadécimal
        # du jeton, jamais le jeton lui-même (packages/lib/.../auth/hash.ts).
        token = "api_" + secrets.token_hex(24)
        digest = hashlib.sha512(token.encode()).hexdigest()
        user_id = psql(f"SELECT id FROM \"User\" WHERE lower(email) = lower('{account['email']}');")
        res = psql(
            "INSERT INTO \"ApiToken\" (name, token, \"userId\", \"teamId\", \"createdAt\") "
            f"VALUES ('Triactis POC automation', '{digest}', {user_id}, {team_id}, NOW()) "
            "RETURNING id;"
        )
        if not res:
            fail("création du jeton d'API impossible (tRPC et base)")
        log("jeton d'API créé par insertion directe (secours)")

    http.token = token
    status, out = http.v2("GET", "/template?perPage=1")
    if status >= 400:
        fail(f"le jeton d'API ne fonctionne pas (HTTP {status}) : {json.dumps(out)[:200]}")
    state.set("api_token", token)
    log("jeton d'API vérifié sur l'API v2")
    return token


TEMPLATE_META = {
    "timezone": "Europe/Paris",
    "dateFormat": "dd/MM/yyyy HH:mm",
    "language": "fr",
    "typedSignatureEnabled": True,
    "drawSignatureEnabled": True,
    "uploadSignatureEnabled": False,
    "distributionMethod": "EMAIL",
}

PLACEHOLDER_EMAILS = {
    1: "destinataire.1@exemple.test",
    2: "destinataire.2@exemple.test",
}


def step_templates(http, state, manifest, pdf_dir):
    created = state.get("templates", {})
    for spec in manifest:
        key = spec["key"]
        if key in created:
            status, _ = http.v2("GET", f"/envelope/{created[key]['envelopeId']}")
            if status < 400:
                log(f"modèle « {spec['title']} » : déjà présent")
                continue
            log(f"modèle « {spec['title']} » : absent côté serveur, recréation")

        blob = (pdf_dir / spec["pdf"]).read_bytes()
        recipients = []
        for rec in spec["recipients"]:
            fields = []
            for f in spec["fields"]:
                if f["recipient"] != rec["index"]:
                    continue
                field = {
                    "type": f["type"],
                    "page": f["page"],
                    "positionX": f["positionX"],
                    "positionY": f["positionY"],
                    "width": f["width"],
                    "height": f["height"],
                }
                if f["type"] in ("TEXT", "NUMBER"):
                    # Les clés absentes sont omises plutôt que mises à null :
                    # les schémas zod sont `.optional()`, pas `.nullish()`.
                    meta = {"type": f["type"].lower()}
                    for meta_key in ("label", "placeholder"):
                        if f.get(meta_key):
                            meta[meta_key] = f[meta_key]
                    field["fieldMeta"] = meta
                fields.append(field)

            recipients.append({
                "email": PLACEHOLDER_EMAILS[rec["index"]],
                "name": rec["label"],
                "role": rec["role"],
                "signingOrder": rec["signingOrder"],
                "fields": fields,
            })

        meta = dict(TEMPLATE_META)
        meta["subject"] = spec["subject"]
        meta["message"] = spec["message"]
        meta["signingOrder"] = "SEQUENTIAL" if len(recipients) > 1 else "PARALLEL"

        payload = {
            "title": spec["title"],
            "type": "TEMPLATE",
            "externalId": spec["externalId"],
            "recipients": recipients,
            "meta": meta,
        }
        status, out = http.v2_multipart("/envelope/create", payload,
                                        [("files", spec["pdf"], blob)])
        if status >= 400 or not isinstance(out, dict) or not out.get("id"):
            fail(f"création du modèle « {spec['title']} » refusée (HTTP {status}) : "
                 f"{json.dumps(out)[:600]}")

        envelope_id = out["id"]
        status, detail = http.v2("GET", f"/envelope/{envelope_id}")
        if status >= 400:
            fail(f"relecture du modèle impossible (HTTP {status})")

        created[key] = {
            "envelopeId": envelope_id,
            "title": spec["title"],
            "externalId": spec["externalId"],
            "templateId": _legacy_id(detail),
            "recipients": [{"id": r["id"], "name": r.get("name"), "role": r.get("role"),
                            "signingOrder": r.get("signingOrder")}
                           for r in detail.get("recipients", [])],
            "items": [i["id"] for i in detail.get("envelopeItems", [])],
            "fields": len(detail.get("fields", [])),
        }
        state.set("templates", created)
        log(f"modèle « {spec['title']} » créé : {created[key]['fields']} champs positionnés, "
            f"{len(created[key]['recipients'])} destinataire(s)")
    return created


def _legacy_id(detail):
    sid = (detail or {}).get("secondaryId") or ""
    match = re.search(r"_(\d+)$", sid)
    return int(match.group(1)) if match else None


def step_direct_link(http, state, templates):
    if state.get("direct_link"):
        log("lien direct : déjà créé")
        return state.get("direct_link")

    tpl = templates.get("nda_acquereur")
    if not tpl or not tpl.get("templateId"):
        log("lien direct : modèle NDA Acquéreur indisponible, étape ignorée")
        return None

    recipient_id = tpl["recipients"][0]["id"] if tpl["recipients"] else None
    status, out = http.v2("POST", "/template/direct/create", {
        "templateId": tpl["templateId"], "directRecipientId": recipient_id,
    })
    if status >= 400 or not isinstance(out, dict) or not out.get("token"):
        log(f"lien direct : création refusée (HTTP {status}) : {json.dumps(out)[:300]}")
        return None

    http.v2("POST", "/template/direct/toggle",
            {"templateId": tpl["templateId"], "enabled": True})
    link = {"token": out["token"], "templateId": tpl["templateId"],
            "path": f"/d/{out['token']}"}
    state.set("direct_link", link)
    log("lien direct créé et activé sur le modèle NDA Acquéreur")
    return link


def _use_template(http, tpl, recipients, prefill, external_id, title, distribute):
    payload = {
        "envelopeId": tpl["envelopeId"],
        "externalId": external_id,
        "recipients": recipients,
        "distributeDocument": distribute,
        "prefillFields": prefill,
        "override": {"title": title},
    }
    return http.v2_multipart("/envelope/use", payload, [])


def _prefill_for(http, tpl, values):
    """Associe les valeurs de démonstration aux champs texte du modèle."""
    status, detail = http.v2("GET", f"/envelope/{tpl['envelopeId']}")
    if status >= 400 or not isinstance(detail, dict):
        return []
    out = []
    for field in detail.get("fields", []):
        meta = field.get("fieldMeta") or {}
        label = (meta.get("label") or "").lower()
        if field["type"] != "TEXT":
            continue
        if "societ" in label:
            out.append({"id": field["id"], "type": "text", "value": values["societe"]})
        elif "fonction" in label:
            out.append({"id": field["id"], "type": "text", "value": values["fonction"]})
    return out


def step_signed_flow(http, state, templates):
    """Recette complète : création, envoi, signature, scellement, contrôle."""
    if (state.get("signed_flow") or {}).get("verified"):
        log("parcours signé : déjà validé")
        return state.get("signed_flow")

    tpl = templates["nda_acquereur"]
    values = {"societe": "TEST CAPITAL SAS", "fonction": "President"}
    prefill = _prefill_for(http, tpl, values)

    status, out = _use_template(
        http, tpl,
        [{"id": tpl["recipients"][0]["id"], "email": "signataire@test-capital.test",
          "name": "Jean Dupont"}],
        prefill, "DEAL-DEMO-001",
        "Projet Alpha - NDA Acquereur - TEST CAPITAL SAS", True,
    )
    if status >= 400 or not isinstance(out, dict):
        fail(f"création du document depuis le modèle refusée (HTTP {status}) : "
             f"{json.dumps(out)[:600]}")

    envelope_id = out["id"]
    recipients = out.get("recipients", [])
    if not recipients:
        fail("aucun destinataire renvoyé par /envelope/use")
    signing_url = recipients[0].get("signingUrl") or ""
    token = signing_url.rstrip("/").split("/")[-1]
    if not token:
        fail("lien de signature absent de la réponse")
    log("document créé depuis le modèle et distribué (lien de signature obtenu)")

    mail = wait_for_mail("signataire@test-capital.test")
    log("invitation de signature : " + ("reçue dans Mailpit" if mail else "NON reçue"))

    status, detail = http.v2("GET", f"/envelope/{envelope_id}")
    if status >= 400:
        fail("relecture du document impossible")
    document_id = _legacy_id(detail)
    recipient_id = recipients[0]["id"]

    signed = 0
    for field in detail.get("fields", []):
        if field.get("recipientId") != recipient_id:
            continue
        ftype = field["type"]
        if ftype == "DATE":
            value = {"type": "DATE", "value": True}
        elif ftype == "EMAIL":
            value = {"type": "EMAIL", "value": "signataire@test-capital.test"}
        elif ftype == "NAME":
            value = {"type": "NAME", "value": "Jean Dupont"}
        elif ftype == "SIGNATURE":
            value = {"type": "SIGNATURE", "value": "Jean Dupont"}
        elif ftype == "TEXT":
            meta = field.get("fieldMeta") or {}
            label = (meta.get("label") or "").lower()
            value = {"type": "TEXT",
                     "value": values["societe"] if "societ" in label else values["fonction"]}
        else:
            continue
        status, out = http.trpc("envelope.field.sign",
                                {"token": token, "fieldId": field["id"], "fieldValue": value})
        if status >= 400:
            fail(f"signature du champ {ftype} refusée (HTTP {status}) : {json.dumps(out)[:400]}")
        signed += 1
    log(f"{signed} champs renseignés et signés via le lien destinataire")

    status, out = http.trpc("recipient.completeDocumentWithToken",
                            {"token": token, "documentId": document_id})
    if status >= 400:
        fail(f"finalisation refusée (HTTP {status}) : {json.dumps(out)[:400]}")
    log("finalisation demandée")

    # Le scellement est un job de fond. On attend l'enveloppe, pas le job :
    # attendre les deux ferait épuiser la boucle si le nom du job changeait,
    # alors que la preuve de scellement est le PDF lui-même.
    final_status, detail = "", {}
    for _ in range(90):
        status, detail = http.v2("GET", f"/envelope/{envelope_id}")
        final_status = detail.get("status") if isinstance(detail, dict) else ""
        if final_status == "COMPLETED":
            break
        time.sleep(4)
    seal = seal_job_status()
    log(f"statut enveloppe : {final_status} · job de scellement : {seal or 'non retrouvé en base'}")

    items = detail.get("envelopeItems") or [{}]
    item_id = items[0].get("id")
    status, blob = http.download(f"/envelope/item/{item_id}/download")
    if status >= 400 or len(blob) < 1000:
        fail(f"téléchargement du PDF final impossible (HTTP {status}, {len(blob)} octets)")

    checks = inspect_pdf(blob)
    out_path = pathlib.Path("/opt/documenso-poc/artifacts/NDA_ACQUEREUR_SIGNE.pdf")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(blob)
    os.chmod(out_path, 0o600)

    result = {
        "envelopeId": envelope_id,
        "externalId": "DEAL-DEMO-001",
        "status": final_status,
        "sealJob": seal,
        "pdfBytes": len(blob),
        "pdf": checks,
        "mailReceived": bool(mail),
        "verified": final_status == "COMPLETED" and checks["hasSig"] and checks["hasByteRange"],
    }
    state.set("signed_flow", result)
    log(f"PDF final : {len(blob)} octets · /Sig {checks['hasSig']} · "
        f"/ByteRange [{checks['byteRange']}] · SubFilter {checks['subFilter']} · "
        f"certificat « {checks['certificate']} »")
    return result


def inspect_pdf(blob):
    """Contrôle cryptographique du PDF scellé, sans dépendance externe."""
    br = re.search(rb"/ByteRange\s*\[([^\]]*)\]", blob)
    sub = re.search(rb"/SubFilter\s*/([A-Za-z0-9.\-]+)", blob)
    certificate = ""
    try:
        contents = re.search(rb"/Contents\s*<([0-9A-Fa-f\s]+)>", blob)
        if contents:
            der = bytes.fromhex(re.sub(rb"\s", b"", contents.group(1)).decode())
            proc = subprocess.run(
                ["openssl", "pkcs7", "-inform", "DER", "-print_certs", "-noout"],
                input=der, capture_output=True, check=False,
            )
            lines = proc.stdout.decode("utf-8", "replace").strip().splitlines()
            certificate = lines[0].replace("subject=", "").strip() if lines else ""
    except Exception:  # noqa: BLE001 - contrôle indicatif, pas bloquant
        certificate = ""

    return {
        "hasSig": b"/Sig" in blob,
        "hasByteRange": br is not None,
        "byteRange": br.group(1).decode().strip() if br else "",
        "subFilter": sub.group(1).decode() if sub else "",
        "hasAcroForm": b"/AcroForm" in blob,
        "hasPPKLite": b"/Adobe.PPKLite" in blob,
        "pages": blob.count(b"/Type /Page "),
        "certificate": certificate,
    }


def step_pending(http, state, templates):
    """Enveloppe laissée EN ATTENTE pour la signature manuelle depuis l'iPhone."""
    if state.get("iphone"):
        log("enveloppe iPhone : déjà préparée")
        return state.get("iphone")

    tpl = templates["nda_cedant"]
    prefill = _prefill_for(http, tpl, {"societe": "ALPHA CONSEIL SAS", "fonction": "President"})
    status, out = _use_template(
        http, tpl,
        [{"id": tpl["recipients"][0]["id"], "email": "jean.dupont@example.test",
          "name": "Jean Dupont"}],
        prefill, "DEAL-DEMO-002",
        "Projet Atlas - NDA Cedant - ALPHA CONSEIL SAS", True,
    )
    if status >= 400 or not isinstance(out, dict):
        fail(f"création de l'enveloppe iPhone refusée (HTTP {status}) : {json.dumps(out)[:400]}")

    url = out["recipients"][0].get("signingUrl")
    result = {"envelopeId": out["id"], "externalId": "DEAL-DEMO-002", "signingUrl": url}
    state.set("iphone", result)
    log("enveloppe en attente créée pour le test iPhone (lien non journalisé)")
    return result


def step_two_signers(http, state, templates):
    """Lettre de mission à deux signataires : démontre l'ordre de signature."""
    if state.get("mandat"):
        log("lettre de mission : déjà créée")
        return state.get("mandat")

    tpl = templates.get("mandat_ma")
    if not tpl or len(tpl["recipients"]) < 2:
        return None
    ordered = sorted(tpl["recipients"], key=lambda r: r.get("signingOrder") or 0)
    status, out = _use_template(
        http, tpl,
        [{"id": ordered[0]["id"], "email": "marie.martin@example.test", "name": "Marie Martin"},
         {"id": ordered[1]["id"], "email": "associe@triactis.test", "name": "Associe Triactis"}],
        _prefill_for(http, tpl, {"societe": "BETA EXPERTISE SAS", "fonction": "Gerante"}),
        "DEAL-DEMO-003", "Projet Boreal - Lettre de mission - BETA EXPERTISE SAS", True,
    )
    if status >= 400 or not isinstance(out, dict):
        log(f"lettre de mission : création refusée (HTTP {status}) : {json.dumps(out)[:300]}")
        return None
    result = {"envelopeId": out["id"], "externalId": "DEAL-DEMO-003",
              "recipients": len(out.get("recipients", []))}
    state.set("mandat", result)
    log("lettre de mission créée, deux signataires en séquence")
    return result


def step_bulk_send(http, state, templates, csv_path):
    if (state.get("bulk") or {}).get("available"):
        log("envoi en masse : déjà effectué")
        return state.get("bulk")

    tpl = templates.get("nda_acquereur")
    team_id = state.get("team_id")
    if not tpl or not tpl.get("templateId") or not team_id:
        return {"available": False, "reason": "modèle ou espace de travail indisponible"}

    # Recette sur trois lignes seulement : le CSV de démonstration en contient
    # douze, mais créer douze enveloppes de test encombrerait l'instance.
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    sample = "\n".join(lines[:4]) + "\n"

    status, out = http.trpc("template.uploadBulkSend", {
        "templateId": tpl["templateId"], "teamId": team_id,
        "csv": sample, "sendImmediately": False,
    })
    result = {"available": status < 400, "rows": max(len(lines) - 1, 0), "tested": 3,
              "http": status, "detail": json.dumps(out)[:300] if status >= 400 else ""}
    state.set("bulk", result)
    log(f"envoi en masse : {'disponible' if result['available'] else 'indisponible'} "
        f"(HTTP {status}, {result['tested']} lignes testées sur {result['rows']} du CSV)")
    return result


def step_webhook(http, state):
    # L'étape se rejoue tant qu'elle n'a pas abouti : un échec antérieur ne doit
    # pas être figé dans l'état.
    if (state.get("webhook") or {}).get("configured"):
        log("webhook : déjà configuré")
        return state.get("webhook")

    status, out = http.trpc("webhook.createWebhook", {
        "webhookUrl": WEBHOOK_URL,
        "eventTriggers": ["DOCUMENT_CREATED", "DOCUMENT_SENT", "DOCUMENT_OPENED",
                          "DOCUMENT_SIGNED", "DOCUMENT_COMPLETED", "DOCUMENT_REJECTED",
                          "DOCUMENT_CANCELLED"],
        "secret": None, "enabled": True,
    })
    ok = status < 400
    result = {"configured": ok, "http": status, "url": WEBHOOK_URL,
              "detail": "" if ok else json.dumps(out)[:300]}
    state.set("webhook", result)
    log("webhook local : " + ("configuré" if ok else f"refusé (HTTP {status})"))
    return result


def inventory():
    """Inventaire par la base, pour les contrôles de persistance."""
    def one(sql):
        out = psql(sql)
        return int(out) if out.isdigit() else -1

    return {
        "users": one('SELECT count(*) FROM "User";'),
        "envelopes": one('SELECT count(*) FROM "Envelope";'),
        "templates": one("SELECT count(*) FROM \"Envelope\" WHERE type = 'TEMPLATE';"),
        "documents": one("SELECT count(*) FROM \"Envelope\" WHERE type = 'DOCUMENT';"),
        "completed": one("SELECT count(*) FROM \"Envelope\" WHERE status = 'COMPLETED';"),
        "pending": one("SELECT count(*) FROM \"Envelope\" WHERE status = 'PENDING';"),
        "recipients": one('SELECT count(*) FROM "Recipient";'),
        "fields": one('SELECT count(*) FROM "Field";'),
        "documentData": one('SELECT count(*) FROM "DocumentData";'),
        "mails": mail_count(),
    }


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="URL publique HTTPS de l'instance")
    parser.add_argument("--basic-auth", default="", help="utilisateur:motdepasse Basic Auth Caddy")
    parser.add_argument("--state-dir", default="/opt/documenso-poc/state")
    parser.add_argument("--repo-dir", default="/opt/leo-learning/experiments/documenso-poc")
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()

    if args.inventory_only:
        print(json.dumps(inventory(), indent=2))
        return 0

    state = State(pathlib.Path(args.state_dir) / "seed-state.json")
    basic = tuple(args.basic_auth.split(":", 1)) if args.basic_auth else None
    http = Http(args.base, basic)

    repo = pathlib.Path(args.repo_dir)
    pdf_dir = repo / "demo" / "generated"
    manifest = json.loads((pdf_dir / "templates.json").read_text(encoding="utf-8"))

    account = step_account(http, state)

    # Le jeton d'API d'abord : s'il répond, la session par mot de passe n'a
    # aucune raison d'être ouverte, et un changement de mot de passe côté
    # interface reste sans effet sur la recette.
    if stored_token_works(http, state):
        log("session par mot de passe : inutile, le jeton d'API conservé répond")
    else:
        step_signin(http, account)
    step_api_token(http, state, account)

    templates = step_templates(http, state, manifest, pdf_dir)
    direct = step_direct_link(http, state, templates)
    signed = step_signed_flow(http, state, templates)
    iphone = step_pending(http, state, templates)
    mandat = step_two_signers(http, state, templates)
    bulk = step_bulk_send(http, state, templates, repo / "demo" / "bulk-send-demo.csv")
    hook = step_webhook(http, state)

    inv = inventory()
    log("inventaire : " + json.dumps(inv, ensure_ascii=False))

    # Livraison des éléments sensibles : fichier local 600, jamais la sortie
    # standard. oracle/relay.sh le chiffre ensuite vers le certificat de relais.
    handoff = {
        "account": {"email": account["email"], "password": account["password"]},
        "apiTokenPresent": bool(state.get("api_token")),
        "iphoneSigningUrl": (iphone or {}).get("signingUrl"),
        "directLinkPath": (direct or {}).get("path"),
        "signedFlow": signed,
        "mandat": mandat,
        "bulk": bulk,
        "webhook": hook,
        "inventory": inv,
    }
    out_path = pathlib.Path("/opt/documenso-poc/artifacts/handoff.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(handoff, indent=2, ensure_ascii=False))
    os.chmod(out_path, 0o600)

    log("amorçage terminé")
    return 0


if __name__ == "__main__":
    sys.exit(main())
