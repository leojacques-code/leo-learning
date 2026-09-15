# Déploiement du POC Documenso sur Oracle Cloud

Date : 2026-09-15 · Branche : `leolearning`

Ce document décrit l'instance publique de test. Il ne contient **aucune valeur
de secret** : uniquement leurs noms et l'endroit où ils vivent.

---

## 1. Architecture

```
                    Internet
                        │
                        │ 80 / 443
                        ▼
              ┌───────────────────┐
              │  Caddy            │  seul point d'entrée applicatif
              │  HTTPS auto       │  aucun access log HTTP
              └─────────┬─────────┘
                        │ réseau Docker interne
        ┌───────────────┼───────────────┬──────────────┐
        ▼               ▼               ▼              ▼
  ┌───────────┐  ┌────────────┐  ┌───────────┐  ┌─────────────┐
  │ Documenso │  │  Mailpit   │  │  page de  │  │  récepteur  │
  │  :3000    │  │  :8025 UI  │  │   démo    │  │ de webhooks │
  └─────┬─────┘  │  :1025 SMTP│  │ (statique)│  │    :9000    │
        │        └────────────┘  └───────────┘  └─────────────┘
        ▼
  ┌────────────┐
  │ PostgreSQL │  volume documenso-poc-db
  │   :5432    │  contient aussi les PDF
  └────────────┘
```

Aucun des services applicatifs n'est publié sur une interface publique :
`compose.yml` les lie à `127.0.0.1`, et Caddy les joint par le réseau Docker.

---

## 2. Machine

| Élément | Valeur |
| --- | --- |
| Fournisseur | Oracle Cloud Infrastructure, Always Free |
| Région | France Central (Paris) |
| Forme | VM.Standard.A1.Flex |
| Processeur | 2 OCPU **ARM64 / aarch64** |
| Mémoire | 12 Go |
| Disque de démarrage | ~47 Go |
| Système | Ubuntu 24.04 LTS (ARM64) |
| Adresse publique | IPv4 **éphémère** (voir § 13) |
| Coût | 0 € — aucune ressource payante n'a été créée |

L'architecture ARM64 impose de vérifier chaque image. Les images utilisées
publient toutes un manifeste `linux/arm64` :

| Image | arm64 |
| --- | --- |
| `documenso/documenso:v2.18.0` | oui |
| `postgres:15` | oui |
| `axllent/mailpit:latest` | oui |
| `caddy:2.10-alpine` | oui |
| `python:3.12-alpine` (récepteur de webhooks) | oui |

Aucune image n'a été remplacée par un fork, et la version de Documenso reste
épinglée à **v2.18.0**.

---

## 3. Noms d'hôte

Il n'y a pas de domaine dédié. Les noms sont dérivés de l'adresse publique via
**sslip.io**, qui résout `a-b-c-d.sslip.io` vers `a.b.c.d` sans inscription ni
configuration.

| Service | Nom |
| --- | --- |
| Application | `<ip-avec-tirets>.sslip.io` |
| Boîte aux lettres | `mail.<ip-avec-tirets>.sslip.io` |
| Support de démonstration | `demo.<ip-avec-tirets>.sslip.io` |

Caddy obtient un certificat public valide pour les trois, automatiquement.

La VM résout elle-même ces trois noms vers `127.0.0.1` via `/etc/hosts` : le
retour de son adresse publique vers elle-même (hairpin NAT) n'est pas garanti
chez Oracle, et les vérifications menées depuis la machine échoueraient sinon
alors que le service répond parfaitement depuis Internet.

---

## 4. Disposition sur le disque

```
/opt/leo-learning/                      dépôt Git, remplacé à chaque déploiement
  experiments/documenso-poc/            code, compose, scripts

/opt/documenso-poc/                     ÉTAT D'EXÉCUTION, hors dépôt Git
  .env                                  secrets applicatifs          600
  certs/cert.p12                        certificat de signature      600
  state/auth.env                        identifiants Basic Auth      600
  state/seed-state.json                 état de l'amorçage           600
  state/bootstrapped                    marqueur de fin d'amorçage
  state/last-phase                      phase du dernier déploiement
  Caddyfile                             configuration rendue
  demo/                                 page servie par Caddy
  webhook/webhook_sink.py               récepteur de webhooks
  artifacts/                            PDF signé, paquet de restitution  700

/var/backups/documenso-poc/<horodatage>/   sauvegardes                700
```

La séparation est délibérée. Le dépôt Git est écrasé à chaque déploiement
(`git checkout --force`) ; l'état d'exécution ne l'est jamais. `git clean`
n'est appelé nulle part.

---

## 5. Secrets

Tous créés **sur la machine**, jamais transmis, jamais affichés.

| Nom | Rôle | Créé par |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | mot de passe PostgreSQL | `scripts/00-generate-secrets.sh` |
| `NEXTAUTH_SECRET` | secret de session | idem |
| `NEXT_PRIVATE_ENCRYPTION_KEY` | chiffrement applicatif | idem |
| `NEXT_PRIVATE_ENCRYPTION_SECONDARY_KEY` | chiffrement secondaire | idem |
| `NEXT_PRIVATE_SIGNING_PASSPHRASE` | passphrase PKCS#12 | `scripts/01-generate-certificate.sh` |
| `POC_MAIL_PASSWORD` | Basic Auth Mailpit | `oracle/deploy.sh` |
| `POC_DEMO_PASSWORD` | Basic Auth page de démo | idem |
| `POC_APP_BOOTSTRAP_PASSWORD` | Basic Auth temporaire de l'application | idem |

**Ne jamais régénérer `NEXT_PRIVATE_ENCRYPTION_KEY`** sur une base contenant
des données : elles deviendraient illisibles. `deploy.sh` ne régénère aucun
secret existant, par construction.

### Secrets GitHub Actions requis

Par leur nom seulement :

- `ORACLE_HOST`
- `ORACLE_USER`
- `ORACLE_SSH_PRIVATE_KEY`
- `POC_RECOVERY_PASSWORD` — facultatif : s'il est présent, il devient le mot de
  passe Basic Auth de Mailpit et de la page de démonstration. C'est la voie de
  récupération quand ces mots de passe ont été perdus. Il ne touche à aucun
  compte Documenso.

Aucun secret Documenso n'est stocké dans GitHub, et aucun n'y remonte.

### Comment les valeurs sont restituées

Le dépôt est public : tout ce qu'un job Actions affiche est lisible par
n'importe qui. L'agent qui conduit le déploiement n'a par ailleurs pas d'accès
SSH direct à la machine.

`oracle/relay.sh` résout le problème par un chiffrement asymétrique à sens
unique : `oracle/relay-cert.pem` est un certificat **public**, versionné sans
risque ; la machine chiffre les valeurs vers ce certificat et n'imprime que le
chiffré. Seul le détenteur de la clé privée, qui n'a jamais quitté
l'environnement de l'agent, peut le lire.

Les mêmes valeurs sont lisibles directement sur la machine, en SSH, dans
`/opt/documenso-poc/state/auth.env` et `/opt/documenso-poc/state/seed-state.json`,
tous deux en permissions 600.

---

## 6. Ports

| Port | Exposition | Contrôlé par |
| --- | --- | --- |
| 22 | public | Security List Oracle + iptables |
| 80 | public | Caddy (redirection vers 443) |
| 443 | public | Caddy |
| 3000 | `127.0.0.1` uniquement | `compose.yml` |
| 55432 | `127.0.0.1` uniquement | `compose.yml` (PostgreSQL décalé) |
| 8025 | `127.0.0.1` uniquement | `compose.yml` (interface Mailpit) |
| 1025 | `127.0.0.1` uniquement | `compose.yml` (SMTP Mailpit) |
| 5432 | non publié | réseau Docker interne |
| 9000 | non publié | réseau Docker interne |
| 2019 | non publié | API d'administration Caddy, **coupée** (`admin off`) |

Le pare-feu hôte n'autorise en entrée que 22, 80 et 443. Les règles sont
**ajoutées** (`iptables -I INPUT ... -j ACCEPT`), jamais substituées : aucune
politique n'est modifiée, aucun flush n'est fait, la session SSH ne peut pas
être coupée par le déploiement.

La vérification depuis l'extérieur est faite par le runner GitHub, qui est sur
Internet : c'est le seul endroit d'où le constat a une valeur.

---

## 7. Point de sécurité : query string

`RESULTATS_TEST_2026-09-12.md`, constat 3 : les formulaires `/signin`,
`/signup` et `/forgot-password` sont servis sans attribut `method` et peuvent,
avant hydratation du JavaScript, partir en **GET avec l'email et le mot de
passe dans la query string**. Documenso ne les journalise pas, mais un reverse
proxy le ferait par défaut.

Parade appliquée : **aucun access log HTTP**. `log { output discard }` est posé
explicitement sur chacun des trois sites de `Caddyfile.tpl`, plutôt que de se
reposer sur le fait que Caddy n'en écrit pas par défaut — l'intention est ainsi
lisible et une reprise du fichier ne la perdra pas par accident.

Vérification automatique à chaque déploiement (`oracle/checks.sh`) : une requête
est émise avec un marqueur unique et **fictif** en query string, puis recherchée
dans les journaux Caddy, les journaux Documenso et le volume de données Caddy.
Zéro occurrence attendue. Aucun vrai mot de passe n'est utilisé pour ce test.

---

## 8. Déploiement

### Déclenchement

Un `push` sur la branche `leolearning` touchant `experiments/documenso-poc/**`
ou le fichier de workflow. Rien d'autre n'est nécessaire.

`workflow_dispatch` est déclaré mais GitHub ne l'expose que pour les workflows
présents sur la branche par défaut, ce qui n'est pas le cas ici.

### Ce que fait le workflow

1. écrit la clé SSH dans `$RUNNER_TEMP` en 600, et vérifie qu'elle est
   exploitable avant de s'en servir ;
2. attend que le port 22 réponde (utile après un redémarrage de la machine) ;
3. se connecte, fait cloner le dépôt public par la machine et lui fait
   basculer sur **le commit exact** qui a déclenché le workflow ;
4. lance `oracle/run.sh` ;
5. vérifie depuis Internet l'exposition réseau ;
6. efface le matériel SSH du runner, quoi qu'il arrive.

Aucune action tierce n'est utilisée dans ce job : la clé privée y transite, et
lui adjoindre du code non relu serait le maillon faible du dispositif.

### Ce que fait `oracle/run.sh`

| Étape | Contenu |
| --- | --- |
| 1 | bootstrap de l'hôte (paquets, Docker, pare-feu, SSH) |
| 2 | déploiement de la pile |
| 3 | génération des modèles de démonstration |
| 4 | amorçage applicatif et recette fonctionnelle |
| 5 | fermeture de l'inscription, retrait du Basic Auth applicatif |
| — | espace partagé Triactis et recette depuis un second compte (§ 9) |
| 6 | contrôles d'après déploiement |
| 7 | test de persistance |
| 8 | sauvegarde et restitution chiffrée |
| — | inventaire applicatif, en lecture seule, publié en fin de journal |

Toutes les étapes sont idempotentes.

### Séquence d'ouverture au public

L'inscription n'est jamais ouverte sur une instance joignable sans
authentification :

1. premier déploiement : l'inscription est ouverte, mais **tout le site est
   derrière un Basic Auth Caddy** ;
2. le compte d'administration est créé par l'API, depuis la machine ;
3. un marqueur `state/bootstrapped` est posé ;
4. `deploy.sh` est relancé : l'inscription se ferme, le Basic Auth applicatif
   est retiré, Caddy redémarré ;
5. le Basic Auth reste en place devant Mailpit et la page de démonstration.

L'interrupteur est la variable `POC_DISABLE_SIGNUP` de
`/opt/documenso-poc/oracle.env`, dont la valeur par défaut ferme l'inscription.
Elle n'est **jamais** écrite en dur dans `compose.oracle.yml` : une valeur en
dur survit à l'oubli et rouvre l'instance à chaque déploiement.

Seconde barrière, indépendante : `NEXT_PRIVATE_ALLOWED_SIGNUP_DOMAINS` est
câblée sur le domaine du cabinet. Elle ne sert à rien tant que l'interrupteur
ferme tout, et elle évite qu'une réouverture ouvre l'instance au premier venu.

### Deux chemins d'accès pendant l'amorçage

Le Basic Auth de Caddy et le jeton d'API Documenso voyagent tous deux dans
l'en-tête `Authorization` : ils ne peuvent pas coexister sur une même requête.
L'amorçage utilise donc l'URL publique HTTPS pour la création de compte, la
vérification et la connexion, et la boucle locale pour les appels authentifiés
par jeton d'API. Le parcours public reste vérifié par `oracle/checks.sh` et par
la sonde externe du workflow.

### Le mot de passe humain n'est pas une dépendance

Sur une instance déjà amorcée, l'amorçage essaie d'abord le jeton d'API
conservé en 600 sur la machine. S'il répond, aucune session par mot de passe
n'est ouverte : changer le mot de passe du compte depuis l'interface, geste
d'exploitation parfaitement légitime, ne casse donc plus la recette.

Si le jeton ne répond plus, la connexion classique prend le relais, et si elle
échoue à son tour le message dit quoi faire. **Aucun script ne modifie le mot
de passe d'un compte pour se débloquer.**

---

## 9. Utilisation multi-utilisateurs

### L'espace partagé

| Élément | Valeur |
| --- | --- |
| Organisation | `Triactis` |
| Équipe | `Triactis` |
| Modèles de démonstration | propriété de l'équipe, visibilité `EVERYONE` |
| Rôle du compte d'administration | `ADMIN` |
| Rôle d'un collaborateur | `MEMBER` |

Un `MEMBER` voit les modèles de l'équipe, en crée des documents et les envoie.
Il n'administre pas l'espace. C'est le niveau par défaut d'un collaborateur, et
donner `ADMIN` à tout le monde serait une facilité coûteuse.

Chaque compte garde par ailleurs son organisation et son équipe personnelles,
invisibles des autres. Le partage d'équipe **n'aspire pas** les espaces
personnels : un document de dossier déposé là y reste.

### Le modèle d'appartenance de Documenso v2.18

Il n'existe **ni table `Template`, ni table `TeamMember`**. Les modèles sont des
`Envelope` de type `TEMPLATE`, et l'accès à une équipe passe par une chaîne de
groupes :

```
User → OrganisationMember → OrganisationGroupMember
     → OrganisationGroup → TeamGroup → Team
```

Conséquence pratique : rattacher un compte au groupe interne
`INTERNAL_ORGANISATION` / `MEMBER` d'une organisation lui ouvre à la fois
l'organisation **et** les équipes auxquelles ce groupe est relié. Deux
insertions suffisent, et aucune autre écriture n'est nécessaire.

Une requête écrite de mémoire sur un schéma supposé produirait un inventaire
faux : `oracle/audit-inventory.sh` cartographie le schéma avant de l'interroger.

### Pourquoi les modèles n'ont pas été déplacés

Le lien direct, l'envoi en masse et le webhook sont tous rattachés à l'équipe
qui porte les modèles. Les déménager vers une nouvelle équipe aurait cassé les
trois d'un coup, pour un résultat identique. On fait donc entrer les comptes
dans l'équipe existante, qu'on renomme : rien ne bouge, seule l'appartenance
s'ajoute.

### Ajouter un collaborateur plus tard

```bash
# 1. rouvrir l'inscription, geste explicite
sudo sed -i 's/^POC_DISABLE_SIGNUP=.*/POC_DISABLE_SIGNUP=false/' \
  /opt/documenso-poc/oracle.env
```

2. relancer le déploiement : n'importe quel push sur `leolearning` suffit ;
3. créer le compte depuis `/signup`, avec une adresse du domaine du cabinet —
   les autres domaines restent refusés ;
4. refermer : remettre `POC_DISABLE_SIGNUP=true` et relancer.

Le rattachement à l'espace Triactis est automatique au déploiement suivant :
`oracle/workspace.py` rattache tout compte du domaine du cabinet qui ne l'est
pas encore, et ne fait rien pour ceux qui le sont déjà.

### Écritures directes en base : la règle

L'API d'invitation de Documenso existe, mais l'acceptation d'une invitation
suppose d'être connecté en tant qu'invité, donc de disposer de son mot de
passe. C'est ce qui rend l'écriture directe nécessaire ici, et non un raccourci
de confort.

Toute écriture directe est soumise aux mêmes conditions, et `oracle/run.sh`
les applique : sauvegarde immédiatement avant, transaction, idempotence, et
relecture en base pour preuve. Un échec de la mise en partage n'emporte ni les
contrôles, ni la persistance, ni la sauvegarde.

---

## 10. Exploitation courante

```bash
cd /opt/leo-learning/experiments/documenso-poc

DC="docker compose \
  --project-directory /opt/leo-learning/experiments/documenso-poc \
  --env-file /opt/documenso-poc/.env \
  --env-file /opt/documenso-poc/oracle.env \
  -f compose.yml -f compose.oracle.yml"

$DC ps
$DC logs --tail=200 documenso
$DC logs --tail=100 database
$DC logs --tail=100 caddy
docker stats --no-stream
df -h
free -h
```

Pour valider la composition **sans afficher les secrets** :

```bash
$DC config --quiet          # jamais `config` tout court
```

Contrôles complets, et inventaire en lecture seule :

```bash
bash oracle/checks.sh
bash oracle/audit-inventory.sh
```

---

## 11. Sauvegarde et restauration

### Sauvegarde

```bash
bash scripts/oracle-backup.sh
```

Écrit dans `/var/backups/documenso-poc/<horodatage>/` :

- `documenso_poc.dump` — dump PostgreSQL complet, **PDF scellés compris**
  puisque les documents sont stockés en base ;
- `env.backup` — sans lui l'application ne redémarre pas ;
- `cert.p12` — le certificat de signature ;
- `MANIFEST.txt` — commit déployé, tailles, empreintes SHA-256.

Rotation sur les 7 dernières.

**Limite à connaître, et elle est sérieuse.** La sauvegarde est écrite sur le
même disque que les données. Ce n'est donc **pas** un plan de reprise : elle
protège d'une erreur de manipulation ou d'une purge accidentelle, pas de la
perte du volume de démarrage ni de la disparition de l'instance. Un vrai
dispositif suppose une copie hors de la machine, qui n'est pas en place.

### Restauration

```bash
bash scripts/oracle-restore.sh                      # liste les sauvegardes
bash scripts/oracle-restore.sh 20260915T101500Z     # restaure
```

**Jamais automatique.** Aucun script du dépôt ne l'appelle. Elle demande de
taper `RESTAURER` et écrase la base courante.

Le `.env` et le certificat ne sont pas restaurés automatiquement : restaurer un
dump avec un `NEXT_PRIVATE_ENCRYPTION_KEY` différent rendrait les données
chiffrées illisibles. Ce rapprochement est fait à la main, en conscience.

---

## 12. Arrêt, rollback, suppression

```bash
bash scripts/oracle-stop.sh            # arrêt, volumes CONSERVÉS
bash scripts/oracle-stop.sh --start    # relance
bash scripts/oracle-stop.sh --status   # état
```

`docker compose down -v` n'est appelé par **aucun** script automatique. La
suppression des données passe exclusivement par `scripts/99-purge.sh`, qui
énumère ce qui va disparaître et exige de taper `SUPPRIMER`. Il n'est jamais
lancé par le workflow.

Revenir à une version antérieure : pousser le commit voulu sur `leolearning`,
ou sur la machine `git checkout <sha>` puis relancer `oracle/deploy.sh`. Les
données ne sont pas touchées.

---

## 13. Si l'adresse publique change

L'adresse IPv4 est **éphémère** : Oracle peut l'attribuer à nouveau après un
arrêt prolongé de l'instance. Aucune adresse réservée n'a été prise, car cela
sort de l'offre gratuite.

Si l'adresse change :

1. mettre à jour le secret GitHub `ORACLE_HOST` avec la nouvelle adresse ;
2. pousser un commit sur `leolearning` (ou relancer le dernier workflow) ;
3. `deploy.sh` redécouvre l'adresse via le service de métadonnées Oracle,
   recalcule les trois noms sslip.io, réécrit `/etc/hosts` et le `Caddyfile`,
   et redémarre Caddy ;
4. Caddy demande de nouveaux certificats pour les nouveaux noms ;
5. vérifier : `bash oracle/checks.sh`.

**Conséquence à anticiper :** les liens de signature déjà envoyés portent
l'ancien nom d'hôte et cesseront de fonctionner. Les documents, eux, ne sont
pas perdus : seule l'URL change. Les PDF déjà scellés sont autoporteurs et ne
dépendent ni de l'adresse ni des clés de l'instance.

---

## 14. Mise à jour de Documenso

1. changer le tag dans `compose.yml` (`documenso/documenso:vX.Y.Z`) ;
2. **vérifier que l'image publie un manifeste `linux/arm64`** ;
3. sauvegarder : `bash scripts/oracle-backup.sh` ;
4. pousser sur `leolearning` ;
5. les migrations Prisma sont appliquées par l'entrypoint de l'image ;
6. vérifier : `bash oracle/checks.sh`.

Ne jamais basculer sur `latest` : une montée de version doit être un acte
délibéré, daté et réversible.

---

## 15. Limites

1. **Une seule machine.** Ni haute disponibilité, ni bascule. Une panne de
   l'instance est une indisponibilité.
2. **Sauvegarde sur le même disque.** Voir § 11. Ce n'est pas un plan de
   reprise.
3. **Certificat de signature auto-signé.** POC technique. Ni QES, ni AES, ni
   certificat qualifié, ni équivalent juridique d'un prestataire de confiance.
4. **Aucun courriel réel n'est envoyé.** Tout est capté par Mailpit. La
   délivrabilité n'est donc pas validée.
5. **Adresse IPv4 éphémère.** Voir § 13.
6. **Pas de supervision.** Pas de Prometheus, pas d'alerte. Le diagnostic se
   fait à la main avec les commandes du § 10.
7. **Détection des champs par IA non activée**, et elle ne doit pas l'être :
   elle exige une facturation Google Cloud active et envoie le contenu des
   documents à Vertex AI.
8. **Données fictives uniquement** dans les modèles de démonstration. Aucune
   donnée client réelle ne doit entrer sur cette instance.
9. **L'espace partagé ne compte qu'un compte du cabinet** à ce jour. Le
   mécanisme est vérifié de bout en bout, mais il n'a pas été éprouvé à
   plusieurs dizaines de comptes.
