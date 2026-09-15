# Résultats du test de bout en bout

Date : 2026-09-11 · Documenso v2.18.0 · commit upstream `5603a9e`

---

## Verdict

```
DOCUMENSO POC LOCAL

Status : GO AVEC RÉSERVES
```

Le parcours complet a été exécuté : création de compte, import PDF, placement
de champs, envoi, ouverture côté signataire, signature, finalisation,
génération et téléchargement du PDF signé, persistance après redémarrage.

Deux réserves, détaillées plus bas : le rendu d'un champ trop étroit tronque
son contenu, et une erreur JavaScript a été observée sur le pavé de signature
en largeur mobile.

---

## Conditions du test

Test mené dans un conteneur Linux, **pas via le `compose.yml` livré** : les
CDN d'images Docker étaient inaccessibles depuis l'environnement d'audit
(403 sur Docker Hub comme sur ghcr.io). Documenso a donc été construit depuis
les sources, à la même version et avec la même configuration que celle du
`compose.yml`.

| Paramètre | Valeur au test | Valeur dans `compose.yml` |
| --- | --- | --- |
| Documenso | v2.18.0 (sources) | v2.18.0 (image officielle) |
| Node | 24.21.0 | fourni par l'image |
| PostgreSQL | 16.13 | 15 |
| Stockage PDF | `database` | `database` |
| Jobs | `local` | `local` |
| Signature | `local`, `.p12` auto-signé | idem |
| SMTP | collecteur local port 1025 | Mailpit port 1025 |

Écarts : PostgreSQL 16 au lieu de 15 (Documenso exige 14+, les deux
conviennent) et un collecteur SMTP Python au lieu de Mailpit (même rôle, même
port). Le reste est identique.

---

## Parcours exécuté

| # | Étape | Résultat | Preuve |
| --: | --- | --- | --- |
| 1 | Ouverture de l'application | ✅ | `/api/health` → `database: ok`, `certificate: ok` |
| 2 | Migrations Prisma | ✅ | « All migrations have been successfully applied », 52 tables |
| 3 | Création de compte | ✅ | `User` id 3, `jean.dupont@test-capital.test` |
| 4 | Mail de confirmation | ✅ | mail 1 reçu (17 341 o), objet « Please confirm your email » |
| 5 | Vérification de l'email | ✅ | `emailVerified` non nul |
| 6 | Connexion, dashboard | ✅ | `/t/personal_…/documents` |
| 7 | Import du PDF | ✅ | `Envelope` DRAFT, `DocumentData` type `BYTES_64`, 7 536 o |
| 8 | Ajout d'un signataire | ✅ | `Recipient` `signataire@test-capital.test`, NOT_SIGNED |
| 9 | Placement des champs | ✅ | 3 `Field` en base : NAME, DATE, SIGNATURE, page 2 |
| 10 | Envoi | ✅ | statut PENDING, job `send.signing.requested.email` COMPLETED |
| 11 | Mail d'invitation | ✅ | mail 2 (17 467 o), objet « Please sign this document » |
| 12 | Ouverture côté signataire, hors session | ✅ | `/sign/0nuLQr…` en contexte anonyme |
| 13 | Saisie et signature | ✅ | « 0 Fields Remaining » |
| 14 | Finalisation | ✅ | `Recipient` SIGNED, `Envelope` COMPLETED |
| 15 | **Scellement du PDF** | ✅ | job `internal.seal-document` **COMPLETED** |
| 16 | Mails de complétion | ✅ | mails 3, 4, 5 dont deux avec le PDF joint (331 Ko) |
| 17 | Téléchargement | ✅ | `200 application/pdf`, 228 212 o |
| 18 | Persistance après redémarrage | ✅ | compte, enveloppe, PDF et champs intacts, session conservée |
| 19 | Largeur mobile | ⚠️ | mise en page correcte, une réserve (voir plus bas) |

Aucune erreur HTTP 5xx observée sur l'ensemble du parcours.

---

## Le PDF final signé

Contrôle du fichier extrait de PostgreSQL :

| Contrôle | Résultat |
| --- | --- |
| Taille | 228 212 octets (contre 7 536 à l'import) |
| Pages | 3 : les 2 pages d'origine plus une page « Signing Certificate » |
| `/Sig` | présent |
| `/ByteRange` | `[0 202881 227459 753]` |
| `/SubFilter` | `/ETSI.CAdES.detached` (PAdES) |
| `/Filter` | `/Adobe.PPKLite` |
| `/AcroForm` | présent |

Identité du certificat effectivement embarqué dans la signature, lue avec
`openssl pkcs7` sur le blob PKCS#7 extrait du PDF :

```
subject = O = Triactis POC, CN = Documenso Test Signing Certificate
issuer  = O = Triactis POC, CN = Documenso Test Signing Certificate
```

C'est bien le certificat auto-signé généré par
`scripts/01-generate-certificate.sh`. Auto-émis, donc : **POC technique
uniquement, aucune valeur eIDAS, QES ou AES.**

La page ajoutée par Documenso porte l'identifiant de l'enveloppe, les
événements du signataire, le détail de la signature et le niveau
d'authentification.

---

## Réserve 1 : champ trop étroit, contenu tronqué

La base contient bien `Jean Dupont` dans le champ NAME. Le PDF scellé n'affiche
que `Jean`.

Cause : le champ avait une largeur de 11,3 % de la page, insuffisante pour le
texte, et Documenso ne fait ni retour à la ligne ni réduction automatique.

Cette largeur vient du placement **automatisé** effectué pour ce test : un clic
crée un champ à la taille par défaut. En posant les champs à la main dans
l'interface, on les dimensionne sur le cadre du document et le problème ne se
pose pas.

À retenir pour l'usage réel : **vérifier la largeur des champs destinés à
recevoir un nom ou une raison sociale longue**, et relire le PDF final avant
diffusion. C'est un contrôle de mise en page, pas un défaut bloquant.

---

## Réserve 2 : erreur JavaScript sur le pavé de signature en mobile

En largeur mobile (390 px, profil iPhone 13), la console a émis :

```
Failed to execute 'getImageData' on 'CanvasRenderingContext2D':
The source width is 0.
```

Le tracé a malgré tout été capturé et affiché correctement, et la validation a
fonctionné. L'erreur n'a pas empêché l'opération, mais elle n'a pas été
reproduite assez de fois pour savoir si elle est systématique ou liée à la
simulation de tracé par automatisation.

**À vérifier à la main sur un vrai téléphone** avant d'envisager un usage
réel : c'est le seul point du parcours que l'automatisation ne permet pas de
trancher.

---

## Mobile : ce qui est confirmé

| Élément | État |
| --- | --- |
| Aucun débordement horizontal (390 px) | ✅ mesuré : `scrollWidth` = `clientWidth` = 390 |
| Document lisible | ✅ |
| Barre latérale transformée en tiroir bas | ✅ |
| Nom et pavé de signature accessibles | ✅ |
| Tracé de la signature | ✅ net, avec Undo, Clear et sélecteur de couleur |
| Boutons Next / Cancel | ✅ pleine largeur, tactiles |
| Parcours mobile mené jusqu'à la finalisation | ⬜ non : l'insertion du champ dans le document n'a pas pu être pilotée par coordonnées |

Le mécanisme d'insertion est identique à celui du bureau, où il a été validé.
Il reste à confirmer à la main sur un vrai téléphone.

---

## Confirmation empirique de l'analyse Vercel

Les journaux de démarrage montrent ce que `VERCEL_POC_NOTES.md` annonçait par
lecture du code :

```
[JOBS]: Registered cron job internal.seal-document-sweep (*/15 * * * *)
[JOBS]: Registered cron job internal.expire-recipients-sweep (*/15 * * * *)
[JOBS]: Registered cron job internal.send-signing-reminders-sweep (*/15 * * * *)
[JOBS]: Started cron poller for 6 job(s)
```

Ces crons tournent en mémoire du processus et se sont exécutés pendant le test
(`internal.seal-document-sweep` COMPLETED). Le scellement du PDF final est bien
passé par la file de jobs (`internal.seal-document` COMPLETED).

Sur Vercel, ce planificateur ne survit pas au gel de l'instance et le dispatch
repose sur un auto-appel HTTP non attendu. Le test confirme que ces deux
mécanismes sont bien sur le chemin critique du PDF final : le renoncement à
Vercel était fondé.

---

## Données utilisées

Exclusivement fictives, conformes au jeu de test fixé :

| Élément | Valeur |
| --- | --- |
| Projet | Projet Alpha |
| Société | TEST CAPITAL SAS (fictive) |
| Compte | Jean Dupont, `jean.dupont@test-capital.test` |
| Signataire | Jean Dupont, `signataire@test-capital.test` |
| Document | `NDA_TEST_TRIACTIS.pdf`, généré par `scripts/04-generate-test-nda.py` |

Aucun dossier réel, aucun nom de client, aucune donnée financière, aucun NDA
du cabinet. Aucun mail n'est sorti de la machine : tous ont été captés par le
collecteur local.

---

## Coût

```
Documenso   : 0 €
PostgreSQL  : 0 €
Email       : 0 €
Jobs        : 0 €
Hébergement : 0 €
TOTAL       : 0 €
```

Aucun compte tiers créé, aucune ressource payante.

---

## Ce qu'il reste à faire

1. Rejouer le parcours via le `compose.yml` livré, sur un poste où les images
   Docker sont téléchargeables. C'est le seul écart entre ce qui est testé et
   ce qui est livré.
2. Reprendre la signature mobile à la main sur un vrai téléphone, pour trancher
   la réserve 2.
3. Décider si le placement manuel des champs sur les templates réels du cabinet
   est acceptable en charge de travail, ou s'il faut évaluer la fonction
   « Detect with AI » repérée dans l'éditeur.
