#!/usr/bin/env python3
"""
Rend le Caddyfile depuis oracle/Caddyfile.tpl.

Les valeurs arrivent par l'environnement et non par interpolation shell : les
hashes bcrypt commencent par un motif de la forme 2a suivi d'un séparateur
dollar, qu'un heredoc développé corromprait en tentant d'y voir des variables.

Usage : render-caddyfile.py <gabarit> <destination>
"""

import os
import pathlib
import re
import sys

SUBS = {
    "APP_HOST": "TPL_APP_HOST",
    "MAIL_HOST": "TPL_MAIL_HOST",
    "DEMO_HOST": "TPL_DEMO_HOST",
    "AUTH_USER": "TPL_AUTH_USER",
    "MAIL_AUTH_HASH": "TPL_MAIL_HASH",
    "DEMO_AUTH_HASH": "TPL_DEMO_HASH",
    # Vide en phase ouverte : c'est une valeur légitime, pas une omission.
    "APP_GUARD": "TPL_APP_GUARD",
}

OPTIONAL = {"APP_GUARD"}

# Un marqueur est strictement de la forme deux arobases, un nom en majuscules,
# deux arobases. Le contrôle final s'appuie sur cette forme : chercher « deux
# arobases » n'importe où ferait échouer le rendu sur un simple commentaire.
MARKER = re.compile(r"@@[A-Z_]+@@")


def main() -> int:
    template, destination = sys.argv[1], sys.argv[2]
    text = pathlib.Path(template).read_text(encoding="utf-8")

    for name, variable in SUBS.items():
        value = os.environ.get(variable, "")
        if not value and name not in OPTIONAL:
            sys.exit(f"variable {variable} absente de l'environnement")
        text = text.replace(f"@@{name}@@", value)

    left = sorted(set(MARKER.findall(text)))
    if left:
        sys.exit("marqueur(s) non substitué(s) dans le gabarit Caddy : " + ", ".join(left))

    pathlib.Path(destination).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
