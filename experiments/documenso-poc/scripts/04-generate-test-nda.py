#!/usr/bin/env python3
"""
Génère test-templates/NDA_TEST_TRIACTIS.pdf : un NDA de test entièrement fictif.

Aucune dépendance externe : le PDF est écrit directement, ce qui évite
d'imposer reportlab ou LibreOffice sur le poste. Python 3 suffit.

CONTENU INTÉGRALEMENT FICTIF. Ce document ne reprend aucun NDA réel du
cabinet, aucun nom de client, aucune donnée financière. Il sert uniquement à
valider le parcours de signature du POC. Le jeu de données est celui fixé
pour le POC : Projet Alpha, TEST CAPITAL SAS, Jean Dupont, Président.
"""

import pathlib
import sys

A4_W, A4_H = 595.28, 841.89
MARGIN = 62


def esc(text: str) -> bytes:
    """Encode en WinAnsi et échappe les caractères réservés d'une chaîne PDF."""
    raw = text.encode("cp1252", errors="replace")
    out = bytearray()
    for byte in raw:
        if byte in (0x28, 0x29, 0x5C):  # ( ) \
            out.append(0x5C)
        out.append(byte)
    return bytes(out)


class Page:
    """Accumule des opérateurs de texte, en suivant une position verticale."""

    def __init__(self) -> None:
        self.ops: list[bytes] = []
        self.y = A4_H - MARGIN

    def text(self, s: str, size: int = 10, bold: bool = False, indent: int = 0) -> None:
        font = b"/F2" if bold else b"/F1"
        x = MARGIN + indent
        self.ops.append(
            b"BT " + font + b" %d Tf 1 0 0 1 %.2f %.2f Tm (" % (size, x, self.y)
            + esc(s) + b") Tj ET"
        )
        self.y -= size + 4

    def space(self, h: int = 10) -> None:
        self.y -= h

    def rule(self) -> None:
        self.ops.append(
            b"0.6 w 0.5 0.5 0.5 RG %.2f %.2f m %.2f %.2f l S"
            % (MARGIN, self.y, A4_W - MARGIN, self.y)
        )
        self.y -= 14

    def box(self, w: float, h: float) -> None:
        """Encadré vide, repère visuel pour poser un champ dans Documenso."""
        self.ops.append(
            b"0.8 w 0.45 0.45 0.45 RG %.2f %.2f %.2f %.2f re S"
            % (MARGIN, self.y - h + 10, w, h)
        )
        self.y -= h + 6

    def stream(self) -> bytes:
        return b"\n".join(self.ops)


def wrap(text: str, width: int = 92) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def build() -> list[Page]:
    p1 = Page()
    p1.text("ACCORD DE CONFIDENTIALITÉ", 16, bold=True)
    p1.text("DOCUMENT DE TEST — AUCUNE VALEUR JURIDIQUE", 9, bold=True)
    p1.space(4)
    p1.rule()

    p1.text("Entre les soussignés :", 10, bold=True)
    p1.space(4)
    for line in wrap(
        "TEST CAPITAL SAS, société par actions simplifiée fictive au capital de "
        "100 000 euros, dont le siège social est situé 1 rue de l'Exemple, 75001 Paris, "
        "immatriculée sous le numéro fictif 000 000 000 RCS Paris, représentée par "
        "Monsieur Jean Dupont en qualité de Président,"
    ):
        p1.text(line)
    p1.space(2)
    p1.text("ci-après dénommée « la Partie Divulgatrice »,", 10, indent=8)
    p1.space(10)
    p1.text("Et :", 10, bold=True)
    p1.space(4)
    for line in wrap(
        "La personne physique ou morale dont l'identité est renseignée en dernière page "
        "du présent accord,"
    ):
        p1.text(line)
    p1.space(2)
    p1.text("ci-après dénommée « la Partie Réceptrice »,", 10, indent=8)
    p1.space(14)

    p1.text("Article 1 — Objet", 11, bold=True)
    p1.space(2)
    for line in wrap(
        "Les Parties envisagent d'échanger des informations dans le cadre d'une opération "
        "désignée sous le nom de code « Projet Alpha ». Le présent accord a pour objet de "
        "définir les conditions dans lesquelles ces informations seront traitées."
    ):
        p1.text(line)
    p1.space(10)

    p1.text("Article 2 — Informations confidentielles", 11, bold=True)
    p1.space(2)
    for line in wrap(
        "Sont réputées confidentielles toutes les informations, quel qu'en soit le support, "
        "communiquées par la Partie Divulgatrice au titre du Projet Alpha, à l'exception de "
        "celles déjà publiques ou légitimement détenues par la Partie Réceptrice avant leur "
        "communication."
    ):
        p1.text(line)
    p1.space(10)

    p1.text("Article 3 — Engagements de la Partie Réceptrice", 11, bold=True)
    p1.space(2)
    for line in wrap(
        "La Partie Réceptrice s'engage à préserver la confidentialité des informations reçues, "
        "à ne les utiliser qu'aux fins du Projet Alpha, et à n'en communiquer la teneur qu'aux "
        "membres de son personnel dont l'intervention est nécessaire, sous réserve que "
        "ceux-ci soient tenus d'une obligation équivalente."
    ):
        p1.text(line)
    p1.space(10)

    p1.text("Article 4 — Durée", 11, bold=True)
    p1.space(2)
    for line in wrap(
        "Les engagements souscrits demeurent en vigueur pendant une durée de deux (2) années "
        "à compter de la date de signature, indépendamment de la suite donnée au Projet Alpha."
    ):
        p1.text(line)

    p2 = Page()
    p2.text("Article 5 — Loi applicable", 11, bold=True)
    p2.space(2)
    for line in wrap(
        "Le présent accord fictif est soumis au droit français. Ce document étant un support "
        "de test technique, aucune juridiction n'est valablement désignée et aucune des "
        "stipulations qui précèdent ne produit d'effet."
    ):
        p2.text(line)
    p2.space(16)
    p2.rule()
    p2.space(6)

    p2.text("IDENTIFICATION ET SIGNATURE DE LA PARTIE RÉCEPTRICE", 11, bold=True)
    p2.space(4)
    for line in wrap(
        "Les cadres ci-dessous servent de repères pour positionner les champs dans "
        "l'interface Documenso. Le placement se fait à la main : ils ne sont pas des "
        "champs de formulaire actifs."
    ):
        p2.text(line, 9)
    p2.space(12)

    for label in ("Nom", "Prénom", "Société", "Fonction", "Date"):
        p2.text(f"{label} :", 10, bold=True)
        p2.box(260, 22)
        p2.space(4)

    p2.space(6)
    p2.text("Signature :", 10, bold=True)
    p2.box(260, 76)

    p2.space(20)
    p2.rule()
    p2.text(
        "Document de test généré pour le POC Documenso Triactis. Données fictives.",
        8,
    )
    p2.text(
        "Ne constitue pas un accord de confidentialité et n'engage personne.", 8
    )
    return [p1, p2]


def write_pdf(pages: list[Page], path: pathlib.Path) -> None:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    # Numérotation réservée à l'avance : catalogue, arbre de pages, polices.
    n_catalog, n_pages = 1, 2
    n_font_regular, n_font_bold = 3, 4
    objects.extend([b""] * 4)

    kids: list[int] = []
    for page in pages:
        stream = page.stream()
        n_content = add(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
        n_page = add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
            % (n_pages, A4_W, A4_H, n_font_regular, n_font_bold, n_content)
        )
        kids.append(n_page)

    objects[n_catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % n_pages
    objects[n_pages - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
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
    out += (
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, n_catalog, xref_at)
    )

    path.write_bytes(bytes(out))


def main() -> int:
    poc_dir = pathlib.Path(__file__).resolve().parent.parent
    target = poc_dir / "test-templates" / "NDA_TEST_TRIACTIS.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        print(f"Refus : {target} existe déjà. Le supprimer pour régénérer.")
        return 1

    write_pdf(build(), target)
    print(f"Généré : {target} ({target.stat().st_size} octets, 2 pages)")
    print("Contenu intégralement fictif. Aucune valeur juridique.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
