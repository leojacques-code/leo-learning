#!/usr/bin/env python3
"""
Génère les trois modèles de démonstration Triactis et leurs coordonnées de
champs.

    demo/generated/NDA_CEDANT.pdf
    demo/generated/NDA_ACQUEREUR.pdf
    demo/generated/MANDAT_MA.pdf
    demo/generated/templates.json

CONTENU INTÉGRALEMENT FICTIF. Aucune clause n'est reprise d'un document réel
du cabinet, aucun nom de client, aucune donnée financière. Ces documents
servent uniquement de support de démonstration.

POURQUOI UN GÉNÉRATEUR ET PAS DES PDF VERSIONNÉS
Parce que c'est le générateur qui connaît la position exacte des cadres de
signature. Il émet donc, avec chaque PDF, les coordonnées des champs en
POURCENTAGE de page, dans le repère attendu par Documenso (origine en haut à
gauche). Les champs sont ainsi posés une fois pour toutes par l'API, sans
placement manuel dans l'éditeur et sans deviner des coordonnées.

Aucune dépendance externe : Python 3 suffit. Le PDF est écrit directement.
"""

import json
import pathlib
import sys

A4_W, A4_H = 595.28, 841.89
MARGIN = 62
ACCENT = (0.42, 0.33, 0.13)  # ton sable sombre, sobre à l'impression


def esc(text: str) -> bytes:
    """Encode en WinAnsi et échappe les caractères réservés d'une chaîne PDF."""
    raw = text.encode("cp1252", errors="replace")
    out = bytearray()
    for byte in raw:
        if byte in (0x28, 0x29, 0x5C):  # ( ) \\
            out.append(0x5C)
        out.append(byte)
    return bytes(out)


def wrap(text: str, width: int = 94) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        if len(cur) + len(word) + 1 > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines


class Page:
    """Accumule des opérateurs PDF en suivant une position verticale."""

    def __init__(self) -> None:
        self.ops: list[bytes] = []
        self.y = A4_H - MARGIN

    # -- primitives de texte ------------------------------------------------
    def text(self, s: str, size: int = 10, bold: bool = False, indent: int = 0,
             color: tuple[float, float, float] = (0, 0, 0)) -> None:
        font = b"/F2" if bold else b"/F1"
        self.ops.append(
            b"BT %.3f %.3f %.3f rg " % color + font + b" %d Tf 1 0 0 1 %.2f %.2f Tm (" % (
                size, MARGIN + indent, self.y)
            + esc(s) + b") Tj ET"
        )
        self.y -= size + 4

    def para(self, s: str, size: int = 10) -> None:
        for line in wrap(s):
            self.text(line, size)

    def heading(self, s: str) -> None:
        self.space(6)
        self.text(s, 11, bold=True, color=ACCENT)
        self.space(2)

    def space(self, h: int = 10) -> None:
        self.y -= h

    def rule(self, weight: float = 0.6) -> None:
        self.ops.append(
            b"%.2f w 0.72 0.70 0.66 RG %.2f %.2f m %.2f %.2f l S"
            % (weight, MARGIN, self.y, A4_W - MARGIN, self.y)
        )
        self.y -= 14

    def band(self, height: float = 26) -> None:
        """Bandeau plein pleine largeur, repère visuel de titre."""
        top = self.y + 10
        self.ops.append(
            b"%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f"
            % (ACCENT + (0.0, top - height, A4_W, height))
        )
        self.y -= height - 8

    # -- champ ---------------------------------------------------------------
    def field_box(self, label: str, width: float, height: float,
                  hint: str = "") -> tuple[float, float, float, float]:
        """
        Dessine un cadre légendé et renvoie son rectangle en pourcentage de
        page, dans le repère de Documenso : origine en haut à gauche,
        (x, y, largeur, hauteur).
        """
        self.text(label, 9, bold=True, color=(0.35, 0.34, 0.31))
        box_top = self.y + 6
        box_bottom = box_top - height
        self.ops.append(
            b"0.7 w 0.62 0.60 0.56 RG %.2f %.2f %.2f %.2f re S"
            % (MARGIN, box_bottom, width, height)
        )
        if hint:
            self.ops.append(
                b"BT 0.66 0.64 0.60 rg /F1 8 Tf 1 0 0 1 %.2f %.2f Tm ("
                % (MARGIN + 6, box_bottom + 6) + esc(hint) + b") Tj ET"
            )
        self.y = box_bottom - 14

        return (
            round(MARGIN / A4_W * 100, 3),
            round((A4_H - box_top) / A4_H * 100, 3),
            round(width / A4_W * 100, 3),
            round(height / A4_H * 100, 3),
        )

    def stream(self) -> bytes:
        return b"\n".join(self.ops)


# ---------------------------------------------------------------------------
# Corps des documents
# ---------------------------------------------------------------------------

DISCLAIMER = "Document de demonstration. Contenu fictif, sans valeur juridique."


def cover(page: Page, kicker: str, title: str, subtitle: str) -> None:
    page.band()
    page.ops.append(
        b"BT 1 1 1 rg /F2 13 Tf 1 0 0 1 %.2f %.2f Tm (" % (MARGIN, page.y + 6)
        + esc(kicker) + b") Tj ET"
    )
    page.y -= 26
    page.text(title, 17, bold=True)
    page.text(subtitle, 9, color=(0.42, 0.40, 0.37))
    page.space(4)
    page.rule()


def signature_block(page: Page, party: str, with_email: bool = False) -> dict:
    """Bloc d'identification et de signature, commun aux trois modèles."""
    page.space(8)
    page.rule(1.0)
    page.text(party, 11, bold=True, color=ACCENT)
    page.space(2)
    page.text(
        "Les informations ci-dessous sont renseignees automatiquement depuis le dossier.",
        8, color=(0.45, 0.44, 0.41),
    )
    page.space(10)

    rects = {
        "NAME": page.field_box("Nom et prenom", 250, 24, "MV_PRENOM MV_NOM"),
        "COMPANY": page.field_box("Societe", 250, 24, "MV_SOCIETE"),
        "ROLE": page.field_box("Fonction", 250, 24, "MV_FONCTION"),
    }
    if with_email:
        rects["EMAIL"] = page.field_box("Adresse electronique", 250, 24, "MV_EMAIL")
    rects["DATE"] = page.field_box("Date de signature", 160, 24, "JJ/MM/AAAA")
    page.space(4)
    rects["SIGNATURE"] = page.field_box("Signature", 250, 70, "signature manuscrite")
    return rects


def build_nda(role: str) -> tuple[list[Page], dict]:
    """NDA cedant ou acquereur. Deux pages, bloc de signature en page 2."""
    is_seller = role == "cedant"
    counterparty = "le Cedant" if is_seller else "l'Acquereur potentiel"

    p1 = Page()
    cover(
        p1,
        "TRIACTIS - DEMONSTRATION",
        "Engagement de confidentialite" + (" - Cedant" if is_seller else " - Acquereur"),
        DISCLAIMER,
    )

    p1.text("Dossier : MV_PROJET", 10, bold=True)
    p1.text("Reference interne : MV_DOSSIER", 9, color=(0.42, 0.40, 0.37))
    p1.space(12)

    p1.text("Entre les soussignes :", 10, bold=True)
    p1.space(4)
    p1.para(
        "TRIACTIS DEMONSTRATION, societe fictive creee pour les besoins de la presente "
        "demonstration, agissant en qualite de conseil en cession d'entreprise, ci-apres "
        "designee " + chr(171) + " le Conseil " + chr(187) + ","
    )
    p1.space(8)
    p1.text("Et :", 10, bold=True)
    p1.space(4)
    p1.para(
        "La personne dont l'identite figure au bloc de signature du present document, "
        "ci-apres designee " + chr(171) + " " + counterparty + " " + chr(187) + "."
    )

    p1.heading("Article 1 - Objet")
    p1.para(
        "Les parties sont amenees a echanger des informations dans le cadre d'une operation "
        "de cession designee sous le nom de code MV_PROJET. Le present engagement definit les "
        "conditions dans lesquelles ces informations sont traitees."
    )

    p1.heading("Article 2 - Informations confidentielles")
    p1.para(
        "Sont reputees confidentielles toutes les informations, quel qu'en soit le support, "
        "communiquees au titre de l'operation, a l'exception de celles deja publiques ou "
        "legitimement detenues avant leur communication."
    )

    p1.heading("Article 3 - Engagements")
    if is_seller:
        p1.para(
            "Le Cedant s'engage a ne pas divulguer l'existence du mandat ni l'identite des "
            "contreparties approchees, et a diriger vers le Conseil toute sollicitation recue "
            "pendant la duree de l'operation."
        )
    else:
        p1.para(
            "L'Acquereur potentiel s'engage a preserver la confidentialite des informations "
            "recues, a ne les utiliser qu'aux fins de l'etude de l'operation, et a n'en "
            "communiquer la teneur qu'aux membres de son equipe dont l'intervention est "
            "necessaire, sous reserve qu'ils soient tenus d'une obligation equivalente."
        )

    p1.heading("Article 4 - Duree")
    p1.para(
        "Les engagements souscrits demeurent en vigueur pendant une duree de deux (2) annees "
        "a compter de la date de signature, independamment de la suite donnee a l'operation."
    )

    p2 = Page()
    p2.heading("Article 5 - Loi applicable")
    p2.para(
        "Le present document de demonstration est presente comme soumis au droit francais. "
        "S'agissant d'un support de demonstration technique, aucune juridiction n'est "
        "valablement designee et aucune des stipulations qui precedent ne produit d'effet."
    )
    p2.space(10)
    p2.para(
        "Ce document est genere automatiquement depuis un modele. Les elements fixes ne sont "
        "jamais ressaisis : seules varient les donnees propres au dossier et au destinataire.",
        9,
    )

    party = "Identification et signature du Cedant" if is_seller \
        else "Identification et signature de l'Acquereur potentiel"
    rects = signature_block(p2, party, with_email=not is_seller)

    p2.space(10)
    p2.rule()
    p2.text(DISCLAIMER, 8, color=(0.45, 0.44, 0.41))

    fields = [
        {"type": "NAME", "page": 2, "recipient": 1, **rect_to_dict(rects["NAME"])},
        {"type": "TEXT", "page": 2, "recipient": 1, "label": "Societe",
         "placeholder": "MV_SOCIETE", **rect_to_dict(rects["COMPANY"])},
        {"type": "TEXT", "page": 2, "recipient": 1, "label": "Fonction",
         "placeholder": "MV_FONCTION", **rect_to_dict(rects["ROLE"])},
    ]
    if "EMAIL" in rects:
        fields.append({"type": "EMAIL", "page": 2, "recipient": 1, **rect_to_dict(rects["EMAIL"])})
    fields += [
        {"type": "DATE", "page": 2, "recipient": 1, **rect_to_dict(rects["DATE"])},
        {"type": "SIGNATURE", "page": 2, "recipient": 1, **rect_to_dict(rects["SIGNATURE"])},
    ]
    return [p1, p2], {"fields": fields}


def build_mandat() -> tuple[list[Page], dict]:
    """Lettre de mission, deux signataires avec ordre de signature."""
    p1 = Page()
    cover(
        p1,
        "TRIACTIS - DEMONSTRATION",
        "Lettre de mission - cession d'entreprise",
        DISCLAIMER,
    )

    p1.text("Dossier : MV_PROJET", 10, bold=True)
    p1.text("Reference interne : MV_DOSSIER", 9, color=(0.42, 0.40, 0.37))
    p1.space(12)

    p1.para(
        "La presente lettre de mission fictive formalise les conditions dans lesquelles "
        "TRIACTIS DEMONSTRATION accompagnerait MV_SOCIETE dans le cadre d'un projet de cession."
    )

    p1.heading("Article 1 - Perimetre de la mission")
    p1.para(
        "Preparation des supports de presentation, identification et approche des contreparties, "
        "organisation des echanges, assistance a la negociation et suivi jusqu'a la signature "
        "des actes."
    )

    p1.heading("Article 2 - Duree")
    p1.para(
        "La mission est conclue pour une duree de douze (12) mois a compter de sa signature, "
        "renouvelable par accord ecrit des parties."
    )

    p1.heading("Article 3 - Honoraires")
    p1.para(
        "Les honoraires de demonstration sont exprimes ici sous forme de barema fictif et ne "
        "refletent aucune grille tarifaire reelle du cabinet. Aucun montant reel ne figure "
        "dans ce document."
    )

    p1.heading("Article 4 - Confidentialite")
    p1.para(
        "Chacune des parties s'engage a preserver la confidentialite des informations echangees "
        "au titre de la mission, pendant toute sa duree et deux annees apres son terme."
    )

    p2 = Page()
    p2.heading("Article 5 - Loi applicable")
    p2.para(
        "Le present document de demonstration est presente comme soumis au droit francais. "
        "Support de demonstration technique : aucune stipulation ne produit d'effet."
    )
    p2.space(8)
    p2.para(
        "Ce modele porte DEUX signataires, dans un ordre impose : le client signe d'abord, le "
        "representant du cabinet ensuite. Le second destinataire n'est sollicite qu'une fois le "
        "premier passe.",
        9,
    )

    client = signature_block(p2, "1. Signature du client", with_email=False)
    firm = signature_block(p2, "2. Signature du representant TRIACTIS", with_email=False)

    p2.space(6)
    p2.rule()
    p2.text(DISCLAIMER, 8, color=(0.45, 0.44, 0.41))

    fields = []
    for recipient, rects in ((1, client), (2, firm)):
        fields += [
            {"type": "NAME", "page": 2, "recipient": recipient, **rect_to_dict(rects["NAME"])},
            {"type": "TEXT", "page": 2, "recipient": recipient, "label": "Societe",
             "placeholder": "MV_SOCIETE", **rect_to_dict(rects["COMPANY"])},
            {"type": "TEXT", "page": 2, "recipient": recipient, "label": "Fonction",
             "placeholder": "MV_FONCTION", **rect_to_dict(rects["ROLE"])},
            {"type": "DATE", "page": 2, "recipient": recipient, **rect_to_dict(rects["DATE"])},
            {"type": "SIGNATURE", "page": 2, "recipient": recipient,
             **rect_to_dict(rects["SIGNATURE"])},
        ]
    return [p1, p2], {"fields": fields}


def rect_to_dict(rect: tuple[float, float, float, float]) -> dict:
    x, y, w, h = rect
    return {"positionX": x, "positionY": y, "width": w, "height": h}


# ---------------------------------------------------------------------------
# Écriture du PDF
# ---------------------------------------------------------------------------

def write_pdf(pages: list[Page], path: pathlib.Path) -> None:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    n_catalog, n_pages = 1, 2
    n_font_regular, n_font_bold = 3, 4
    objects.extend([b""] * 4)

    kids: list[int] = []
    for page in pages:
        stream = page.stream()
        n_content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
            % (n_pages, A4_W, A4_H, n_font_regular, n_font_bold, n_content)
        ))

    objects[n_catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % n_pages
    objects[n_pages - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), len(kids),
    )
    for num, base in ((n_font_regular, b"/Helvetica"), (n_font_bold, b"/Helvetica-Bold")):
        objects[num - 1] = (
            b"<< /Type /Font /Subtype /Type1 /BaseFont " + base
            + b" /Encoding /WinAnsiEncoding >>"
        )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, n_catalog, xref_at))

    path.write_bytes(bytes(out))


# ---------------------------------------------------------------------------

TEMPLATES = [
    {
        "key": "nda_acquereur",
        "file": "NDA_ACQUEREUR.pdf",
        "title": "NDA Acquereur - MV_PROJET",
        "externalId": "TPL-NDA-ACQUEREUR",
        "subject": "{document.name} - document a signer",
        "message": (
            "Bonjour {signer.name},\n\n"
            "Dans le cadre de l'operation en cours, nous vous invitons a prendre connaissance "
            "et a signer l'engagement de confidentialite ci-joint.\n\n"
            "Le document s'ouvre depuis le lien securise ci-dessous, y compris depuis un "
            "telephone.\n\n"
            "Cordialement,\nEquipe Triactis - demonstration"
        ),
        "recipients": [
            {"index": 1, "role": "SIGNER", "label": "Acquereur potentiel", "signingOrder": 1},
        ],
    },
    {
        "key": "nda_cedant",
        "file": "NDA_CEDANT.pdf",
        "title": "NDA Cedant - MV_PROJET",
        "externalId": "TPL-NDA-CEDANT",
        "subject": "{document.name} - document a signer",
        "message": (
            "Bonjour {signer.name},\n\n"
            "Vous trouverez ci-dessous l'engagement de confidentialite relatif a votre dossier.\n\n"
            "La signature se fait en ligne, en quelques secondes, depuis un ordinateur comme "
            "depuis un telephone.\n\n"
            "Cordialement,\nEquipe Triactis - demonstration"
        ),
        "recipients": [
            {"index": 1, "role": "SIGNER", "label": "Cedant", "signingOrder": 1},
        ],
    },
    {
        "key": "mandat_ma",
        "file": "MANDAT_MA.pdf",
        "title": "Lettre de mission M&A - MV_PROJET",
        "externalId": "TPL-MANDAT-MA",
        "subject": "{document.name} - signature de la lettre de mission",
        "message": (
            "Bonjour {signer.name},\n\n"
            "Veuillez trouver la lettre de mission relative au dossier. Elle est signee "
            "successivement par le client puis par le representant du cabinet.\n\n"
            "Cordialement,\nEquipe Triactis - demonstration"
        ),
        "recipients": [
            {"index": 1, "role": "SIGNER", "label": "Client", "signingOrder": 1},
            {"index": 2, "role": "SIGNER", "label": "Representant Triactis", "signingOrder": 2},
        ],
    },
]

BUILDERS = {
    "nda_acquereur": lambda: build_nda("acquereur"),
    "nda_cedant": lambda: build_nda("cedant"),
    "mandat_ma": build_mandat,
}


def main() -> int:
    poc_dir = pathlib.Path(__file__).resolve().parent.parent
    out_dir = poc_dir / "demo" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for spec in TEMPLATES:
        pages, extra = BUILDERS[spec["key"]]()
        target = out_dir / spec["file"]
        write_pdf(pages, target)
        entry = {k: v for k, v in spec.items()}
        entry["fields"] = extra["fields"]
        entry["pdf"] = spec["file"]
        entry["bytes"] = target.stat().st_size
        manifest.append(entry)
        print(f"genere : {target.name} ({entry['bytes']} octets, {len(pages)} pages, "
              f"{len(entry['fields'])} champs)")

    (out_dir / "templates.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"manifeste : {out_dir / 'templates.json'}")
    print("Contenu integralement fictif. Aucune valeur juridique.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
