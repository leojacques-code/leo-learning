# Templates de test

Déposer ici les templates fictifs de test.

## Règles

**PDF uniquement pour le premier POC.** Pas de DOCX : la conversion exigerait
Gotenberg ou LibreOffice, donc un service de plus et davantage de mémoire. Le
DOCX sera testé après validation du parcours PDF.

**Données fictives exclusivement.** Le jeu de test retenu est :

| Champ | Valeur |
| --- | --- |
| Projet | Projet Alpha |
| Société | TEST CAPITAL SAS |
| Signataire | Jean Dupont |
| Fonction | Président |
| Email | une adresse de test |

**Formellement interdit dans ce dossier :** dossiers M&A réels, noms de clients,
informations financières, coordonnées de prospects, documents confidentiels,
NDA réels non anonymisés.

Le contenu de ce dossier est ignoré par Git (voir `../.gitignore`) : seul ce
README est versionné. Aucun document, même fictif, ne part sur GitHub.

## Premier document attendu

Un fichier nommé `NDA_TEST_TRIACTIS.pdf`, intégralement fictif.

Champs à placer une fois le document importé dans Documenso :

- Nom
- Prénom
- Société
- Fonction
- Date
- Signature

Le placement des champs se fait **à la main dans l'interface Documenso**. Il
n'est pas automatisé : deviner des coordonnées sur un PDF dont la mise en page
n'est pas connue produirait des champs mal positionnés.
