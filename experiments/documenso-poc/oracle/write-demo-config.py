#!/usr/bin/env python3
"""
Écrit /opt/documenso-poc/demo/config.json, lu par la page de démonstration.

Ce fichier ne contient QUE le chemin du lien direct, qui est précisément fait
pour être partagé. Aucun jeton d'API, aucun mot de passe, aucun jeton de
signature nominatif n'y entre : la page est servie à un navigateur, et tout ce
qu'elle reçoit est lisible par qui l'ouvre.
"""

import json
import pathlib

STATE = pathlib.Path("/opt/documenso-poc/state/seed-state.json")
OUT = pathlib.Path("/opt/documenso-poc/demo/config.json")

data = json.loads(STATE.read_text()) if STATE.exists() else {}
config = {"directLinkPath": (data.get("direct_link") or {}).get("path")}

OUT.write_text(json.dumps(config))
OUT.chmod(0o644)

print(f"[run] demo/config.json écrit (lien direct : "
      f"{'oui' if config['directLinkPath'] else 'non'})")
