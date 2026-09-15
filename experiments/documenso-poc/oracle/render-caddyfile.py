#!/usr/bin/env python3
"""
Rend le Caddyfile depuis oracle/Caddyfile.tpl.

Les valeurs arrivent par l'environnement et non par interpolation shell : les
hashes bcrypt commencent par `$2a$...`, qu'un heredoc développé corromprait en
tentant d'y voir des variables.

Usage : render-caddyfile.py <gabarit> <destination>
"""

import os
import pathlib
import sys

SUBS = {
    "@@APP_HOST@@": "TPL_APP_HOST",
    "@@MAIL_HOST@@": "TPL_MAIL_HOST",
    "@@DEMO_HOST@@": "TPL_DEMO_HOST",
    "@@AUTH_USER@@": "TPL_AUTH_USER",
    "@@MAIL_AUTH_HASH@@": "TPL_MAIL_HASH",
    "@@DEMO_AUTH_HASH@@": "TPL_DEMO_HASH",
    "@@APP_GUARD@@": "TPL_APP_GUARD",
}


def main() -> int:
    template, destination = sys.argv[1], sys.argv[2]
    text = pathlib.Path(template).read_text(encoding="utf-8")

    for marker, variable in SUBS.items():
        # APP_GUARD est vide en phase ouverte : c'est une valeur légitime.
        value = os.environ.get(variable, "")
        if not value and variable != "TPL_APP_GUARD":
            sys.exit(f"variable {variable} absente de l'environnement")
        text = text.replace(marker, value)

    if "@@" in text:
        sys.exit("marqueur non substitué dans le gabarit Caddy")

    pathlib.Path(destination).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
