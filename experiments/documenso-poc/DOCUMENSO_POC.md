# POC Documenso Triactis

Évaluation de Documenso comme alternative à DocuSign pour le cabinet.
Environnement expérimental. **Aucune donnée client réelle.**

Date : 2026-09-11 · Branche : `leolearning`

---

## Architecture

```
Poste de travail
   |
   +-- documenso-poc-app    Documenso v2.18.0    localhost:3000
   +-- documenso-poc-db     PostgreSQL 15        localhost:55432
   +-- documenso-poc-mail   Mailpit              localhost:8025
```

Les PDF sont stockés dans PostgreSQL. Aucun service de stockage externe.

**Pourquoi en local et non sur Vercel.** L'architecture de Documenso v2.18.0
est incompatible avec le modèle serverless : la génération du PDF final signé
passe par une file de jobs qui repose sur un processus permanent. Analyse
complète dans `VERCEL_POC_NOTES.md`.

---

## Version Documenso

| Élément | Valeur |
| --- | --- |
| Version | 2.18.0 |
| Image | `documenso/documenso:v2.18.0` (officielle, épinglée) |
| Commit upstream de référence | `5603a9e59da2ae770edcc822ac08a5e3df02ad82` |
| Licence | AGPL v3 |
| Modifications apportées à Documenso | **aucune** |

Aucun code source de Documenso n'est copié dans ce dépôt. On consomme l'image
officielle publiée par l'éditeur. Il n'y a donc ni fork, ni divergence à
maintenir, ni question de licence : une montée de version se fait en changeant
un numéro de tag dans `compose.yml`.

---

## URL

Ce document décrit le POC **local**, sur le poste. Une instance publique en
HTTPS existe par ailleurs, déployée sur Oracle Cloud depuis GitHub Actions :
voir `ORACLE_DEPLOYMENT.md`. Les deux cohabitent, `compose.yml` reste le socle
commun.

Différence à connaître : le POC local est mono-utilisateur par nature, alors
que l'instance publique a un **espace de travail partagé**, où les modèles
appartiennent à l'équipe et non à une personne. Voir `ORACLE_DEPLOYMENT.md`
§ 9, « Utilisation multi-utilisateurs ».

| Service | Adresse |
| --- | --- |
| Documenso | http://localhost:3000 |
| Boîte aux lettres | http://localhost:8025 |
| PostgreSQL | localhost:55432 |

Les ports sont liés à `127.0.0.1` : rien n'est exposé sur le réseau local.

---

## Base PostgreSQL

Base **dédiée au POC**, créée dans un volume Docker nommé `documenso-poc-db`.
Aucune base existante n'est réutilisée.

| Élément | Valeur |
| --- | --- |
| Base | `documenso_poc` |
| Utilisateur | `documenso` |
| Volume | `documenso-poc-db` |
| Port hôte | 55432 (décalé pour ne pas heurter un PostgreSQL local) |

**Pooling.** Sans pooler ici : `NEXT_PRIVATE_DATABASE_URL` et
`NEXT_PRIVATE_DIRECT_DATABASE_URL` pointent sur la même base, ce que la
documentation Documenso autorise explicitement hors PgBouncer.

**Migrations Prisma.** Appliquées par l'entrypoint de l'image officielle au
premier démarrage, une seule fois, contre cette base et elle seule. Rien à
lancer à la main, et pas de migrations concurrentes puisqu'il n'y a qu'une
instance.

Vérifier le schéma après le premier démarrage :

```bash
docker compose exec database \
  psql -U documenso -d documenso_poc -c '\dt' | head -30
```

---

## Variables nécessaires

Valeurs absentes de ce document et du dépôt. Elles vivent dans `.env`, en
permissions 600, couvert par `.gitignore`.

| Variable | Rôle | Origine |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | mot de passe PostgreSQL | `00-generate-secrets.sh` |
| `NEXTAUTH_SECRET` | secret de session | `00-generate-secrets.sh` |
| `NEXT_PRIVATE_ENCRYPTION_KEY` | chiffrement applicatif | `00-generate-secrets.sh` |
| `NEXT_PRIVATE_ENCRYPTION_SECONDARY_KEY` | chiffrement secondaire | `00-generate-secrets.sh` |
| `NEXT_PRIVATE_SIGNING_PASSPHRASE` | passphrase PKCS#12 | `01-generate-certificate.sh` |

Les quatre premières font 32 octets d'entropie (`openssl rand`), encodées en
base64url. La passphrase du certificat fait 24 octets.

Les variables non secrètes (URLs, transport de stockage, SMTP, provider de
jobs) sont fixées en clair dans `compose.yml` : elles ne sont pas
confidentielles et les lire d'un coup d'œil aide plus que ça ne coûte.

**Ne jamais régénérer `NEXT_PRIVATE_ENCRYPTION_KEY`** sur une base contenant
déjà des données : elles deviendraient illisibles.

**Sauvegarder `.env` comme un secret**, au même titre que le certificat.
Vérifié le 2026-09-12 : sans ce fichier l'application refuse de démarrer, et
sa régénération invalide toutes les sessions. Les PDF déjà scellés, eux, ne
sont pas affectés (voir `RESULTATS_TEST_2026-09-12.md`, constat 2).

---

## Certificat

Certificat X.509 auto-signé, généré localement par
`scripts/01-generate-certificate.sh`.

| Élément | Valeur |
| --- | --- |
| Organization | `Triactis POC` |
| Common Name | `Documenso Test Signing Certificate` |
| Clé | RSA 4096, SHA-256 |
| Validité | 365 jours |
| Fichier | `certs/cert.p12`, permissions 600, monté en lecture seule |

La clé privée et le `.crt` intermédiaires sont créés dans un répertoire
temporaire et détruits à la sortie du script, quelle qu'en soit la cause.
Seule l'archive `.p12` subsiste. `certs/`, `*.p12` et `*.key` sont dans le
`.gitignore`.

### Portée juridique

Ce certificat sert exclusivement à un **POC technique**. Il ne constitue ni
une signature qualifiée eIDAS, ni une QES, ni une AES, ni un certificat
qualifié, ni un équivalent juridique de DocuSign. Toute communication interne
sur ce POC doit reprendre cette réserve.

---

## Email

Mailpit capte tous les mails sortants et les affiche sur
http://localhost:8025. Zéro compte à créer, zéro DNS à configurer, zéro euro,
et aucun mail ne part vers l'extérieur : appréciable quand on teste avec des
adresses fictives.

C'est ce qui permet de valider la chaîne complète (invitation, relance,
notification de complétion) sans dépendre d'un tiers.

### Basculer sur un envoi réel

Le jour où il faut faire signer une personne réellement distante, remplacer
le bloc SMTP de `compose.yml` par :

```yaml
NEXT_PRIVATE_SMTP_TRANSPORT: resend
NEXT_PRIVATE_RESEND_API_KEY: "${NEXT_PRIVATE_RESEND_API_KEY:?manquant}"
NEXT_PRIVATE_SMTP_FROM_ADDRESS: <adresse sur un domaine vérifié>
NEXT_PRIVATE_SMTP_FROM_NAME: Triactis Signature POC
```

et ajouter la clé dans `.env`. Cela suppose un compte Resend, une clé API et
la vérification d'un domaine par enregistrements DNS : trois actions
manuelles. Non fait à ce stade, volontairement, pour ne pas bloquer la
validation du parcours de signature.

---

## Background jobs

Provider `local`, adossé à PostgreSQL. Aucun Redis, aucun Inngest, aucun
BullMQ.

Ce provider fonctionne ici parce que le processus Documenso est permanent :
il peut s'auto-appeler en HTTP et faire tourner son planificateur cron en
mémoire. C'est très exactement ce qui tombe en serverless, et la raison
première du renoncement à Vercel (voir `VERCEL_POC_NOTES.md` § 3).

Jobs concernés : envoi des mails, **scellement du PDF final**, webhooks,
relances de signature, expiration des destinataires.

---

## Templates

`test-templates/`, ignoré par Git sauf son README. Aucun document, même
fictif, ne part sur GitHub.

PDF uniquement pour ce premier POC. Pas de DOCX : la conversion exigerait
Gotenberg ou LibreOffice, donc un service de plus et davantage de mémoire.
Le DOCX sera testé après validation du parcours PDF.

Le NDA de test est généré par `./scripts/04-generate-test-nda.py`, sans
dépendance externe. Contenu intégralement fictif. Champs à poser : Nom,
Prénom, Société, Fonction, Date, Signature.

Le placement des champs se fait à la main dans l'interface Documenso. Il n'est
pas automatisé : deviner des coordonnées sur un PDF dont la mise en page n'est
pas connue produirait des champs mal positionnés.

Jeu de données de test : Projet Alpha, TEST CAPITAL SAS, Jean Dupont,
Président, et une adresse e-mail de test.

---

## Déploiement

Prérequis : Docker et Docker Compose v2, 2 Go de RAM disponibles pour Docker.

```bash
cd experiments/documenso-poc

./scripts/00-generate-secrets.sh       # secrets dans .env
./scripts/01-generate-certificate.sh   # certificat auto-signé
./scripts/02-up.sh                     # démarrage, attend /api/health
./scripts/04-generate-test-nda.py      # NDA de test fictif
```

Le premier démarrage prend quelques minutes : téléchargement des images puis
migrations Prisma sur une base vierge.

Ensuite, sur http://localhost:3000 : créer un compte, récupérer le lien de
vérification dans http://localhost:8025, se connecter.

Commandes courantes :

```bash
docker compose logs -f documenso     # journaux applicatifs
docker compose ps                    # état des conteneurs
./scripts/03-down.sh                 # arrêt, données conservées
./scripts/02-up.sh                   # redémarrage
```

---

## Limites

1. **Pas d'URL publique dans cette configuration.** Le POC décrit ici tourne sur
   le poste. Cette limite est levée par le déploiement Oracle Cloud décrit dans
   `ORACLE_DEPLOYMENT.md` : instance publique en HTTPS valide, signataire
   distant réel testé depuis un téléphone.
2. **Certificat auto-signé.** Les lecteurs PDF afficheront la signature comme
   non vérifiable auprès d'une autorité reconnue. Attendu, et sans portée
   juridique.
3. **Emails captés localement.** Rien ne sort. Validé fonctionnellement, pas
   en délivrabilité réelle.
4. **PDF uniquement.** DOCX hors périmètre à ce stade.
5. **Instance unique.** Ni haute disponibilité, ni sauvegarde automatique.
   Le volume `documenso-poc-db` est le seul dépositaire des données du POC.

## Avant tout hébergement : point de sécurité à traiter

Sans objet en local, dirimant dès qu'un reverse proxy est placé devant
l'application.

Les formulaires `/signin`, `/signup` et `/forgot-password` sont servis sans
attribut `method`, donc en GET par défaut, et ne sont rattrapés que par le
gestionnaire JavaScript. Tant que le JavaScript n'est pas hydraté, une
soumission envoie **les identifiants en clair dans la query string**.

Documenso ne les journalise pas, mais sa propre documentation exige un reverse
proxy en production, et nginx, Caddy, Traefik comme les load balancers cloud
journalisent la query string par défaut.

Parade, sans toucher à Documenso : configurer le proxy pour ne pas journaliser
la query string sur ces trois chemins. Constat détaillé et vérifié dans
`RESULTATS_TEST_2026-09-12.md`, constat 3. Parade appliquée et vérifiée sur
l'instance Oracle : voir `ORACLE_DEPLOYMENT.md`.

## Détection automatique des champs : écartée

L'éditeur propose un bouton « Detect with AI ». Il exige un projet Google Cloud
avec facturation active et envoie le contenu des documents à Google Vertex AI.
Payant, et incompatible avec la confidentialité attendue sur des NDA et des
dossiers de cession. Le placement manuel reste la voie retenue : il se fait une
fois par modèle, pas à chaque envoi.

---

## Procédure de rollback

Le POC est confiné à `experiments/documenso-poc/` sur la branche
`leolearning`. Il ne touche ni le `index.html` du dépôt, ni aucun projet
Vercel, ni aucune base existante.

Annuler le POC sans rien détruire d'autre :

```bash
./scripts/03-down.sh                   # arrêt
git checkout main                      # retour à l'état antérieur
```

La branche `leolearning` conserve l'ensemble ; rien n'est perdu.

---

## Procédure de suppression complète

```bash
./scripts/99-purge.sh
```

Le script liste ce qui va être détruit et exige de taper `SUPPRIMER` pour
confirmer. Il supprime les conteneurs, le réseau et le volume
`documenso-poc-db`, donc **toutes les données du POC** : comptes, templates,
documents, PDF signés. Irréversible, sans sauvegarde.

Il ne touche volontairement ni `.env`, ni `certs/cert.p12`, ni
`test-templates/`. Pour les retirer aussi :

```bash
rm -f .env certs/cert.p12
rm -rf test-templates/*.pdf
```

Retirer les images téléchargées :

```bash
docker rmi documenso/documenso:v2.18.0 postgres:15 axllent/mailpit:latest
```

Retirer le POC du dépôt :

```bash
git branch -D leolearning
git push origin --delete leolearning
```

---

## Résultats du test

Parcours complet exécuté sur deux journées : **GO AVEC RÉSERVES**.

- `RESULTATS_TEST_2026-09-11.md` : parcours bureau de bout en bout, PDF scellé
  et vérifié cryptographiquement.
- `RESULTATS_TEST_2026-09-12.md` : parcours mobile de bout en bout, persistance
  à travers un redémarrage complet du conteneur, et trois constats nouveaux
  dont un point de sécurité à traiter avant tout hébergement.

Réserve de méthode, levée depuis : ces deux journées de test avaient été
menées sur Documenso construit depuis les sources, à la même version et même
configuration, et non via ce `compose.yml` (les CDN d'images Docker étaient
inaccessibles depuis l'environnement d'audit). Le parcours a depuis été rejoué
de bout en bout via ce `compose.yml`, avec l'image officielle épinglée
`documenso/documenso:v2.18.0`, sur la machine Oracle : voir
`ORACLE_DEPLOYMENT.md`. L'écart entre le testé et le livré est donc fermé.

## Ce qui reste à faire

- [x] Rejouer le parcours via `compose.yml` avec l'image officielle
      (fait sur Oracle, cf. `ORACLE_DEPLOYMENT.md`)
- [ ] Mesurer le comportement sur vos vrais modèles de documents
- [ ] Arbitrer la charge du placement manuel, une fois ces modèles connus
