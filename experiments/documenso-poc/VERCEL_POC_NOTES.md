# Notes : pourquoi ce POC ne tourne pas sur Vercel

Date : 2026-09-11

Ce document trace l'audit de faisabilité mené avant de monter le POC, et
justifie le choix d'une exécution locale. Il sert aussi à ne pas refaire
l'analyse dans six mois.

---

## 1. Version Documenso auditée

| Élément | Valeur |
| --- | --- |
| Dépôt | `github.com/documenso/documenso` (officiel) |
| Version | 2.18.0 |
| Commit upstream | `5603a9e59da2ae770edcc822ac08a5e3df02ad82` |
| Date | 2026-09-11 |
| Licence | AGPL v3 (`packages/ee` sous licence entreprise) |

## 2. Modifications apportées à Documenso

**Aucune.**

Ce dépôt ne contient pas une ligne de code Documenso. Le POC consomme l'image
officielle `documenso/documenso:v2.18.0`. Il n'y a donc ni fork, ni patch, ni
divergence à maintenir. Ce qui est versionné ici est uniquement de la
configuration d'exécution : `compose.yml`, des scripts shell, de la
documentation.

C'était l'objectif : pouvoir distinguer sans ambiguïté Documenso original de
ce qui relève du POC. La frontière est nette, puisqu'il n'y a rien à
distinguer.

---

## 3. Vercel : le constat

### 3.1 Ce n'est pas une cible supportée par l'éditeur

Source primaire : la documentation livrée **dans** le dépôt Documenso à la
version 2.18.0, `apps/docs/content/docs/self-hosting/getting-started/requirements.mdx`,
section « Supported Platforms » :

> - **Linux** : Any modern distribution (Ubuntu, Debian, CentOS, Alpine)
> - **Docker** : Official images available on DockerHub and GitHub Container Registry
> - **Kubernetes** : Helm charts and manifests available
> - **PaaS providers** : Railway, Render, Koyeb (one-click deploys available)

Vercel n'y figure pas. Les pages de déploiement livrées
(`apps/docs/content/docs/self-hosting/deployment/`) sont `docker`,
`docker-compose`, `kubernetes`, `manual`, `railway` : **il n'existe pas de
`vercel.mdx`**. Vercel n'est mentionné que deux fois dans tout le dépôt, de
façon incidente, comme exemple d'environnement « where file mounting is not
available ».

Un article « Deploying Documenso with Vercel, Supabase and Resend » circule
sur le site de Documenso. Il est antérieur à la migration de Next.js vers
React Router + Hono et ne décrit pas l'architecture de la v2.18.0. Réserve
assumée : ce domaine était inaccessible depuis l'environnement d'audit, le
contenu de l'article n'a donc pas été lu directement.

### 3.2 Le point d'entrée est un serveur permanent

`apps/remix/server/main.js`, dernière ligne :

```js
serve({ fetch: handler.fetch, port });
```

Documenso ne produit pas un handler de fonction mais un serveur HTTP Hono qui
écoute un port. La documentation confirme, en exigeant un reverse proxy qui
« forwards requests to Documenso **on port 3000** ».

### 3.3 Le PDF final signé dépend d'un mécanisme incompatible

C'est le point qui a tranché, parce qu'il porte sur la finalisation et le
téléchargement du document signé, c'est-à-dire la finalité même du POC.

La génération du PDF scellé est un job de fond :
`packages/lib/jobs/definitions/internal/seal-document.ts`, identifiant
`internal.seal-document`.

Le provider `local` dispatche les jobs ainsi
(`packages/lib/jobs/client/local.ts`) :

```js
await Promise.race([
  fetch(endpoint, { method: 'POST', body: ..., headers }).catch(() => null),
  new Promise((resolve) => { setTimeout(resolve, 150); }),
]);
```

L'application s'appelle elle-même en HTTP et **n'attend délibérément pas la
réponse** : elle rend la main au bout de 150 ms. Sur un processus permanent
c'est sain, le serveur survit et traite la requête. En serverless, l'instance
est gelée dès que le handler a répondu : la requête sortante peut ne jamais
partir. Documenso n'utilise pas `waitUntil`.

Conséquence : un document signé peut rester bloqué en `PENDING`, sans PDF
final.

### 3.4 Le filet de sécurité tombe aussi

Documenso prévoit un rattrapage, `internal.seal-document-sweep`, qui repêche
les enveloppes qui auraient dû être scellées. C'est un cron, et le cron du
provider `local` est un `setTimeout` récursif en mémoire du processus
(`local.ts`, `CRON_POLL_INTERVAL_MS = 30_000`), démarré au chargement du
module par `jobsClient.startCron()` (`apps/remix/server/router.ts:157`). En
serverless ce timer meurt avec le gel de l'instance.

Donc : ni dispatch fiable, ni rattrapage.

### 3.5 Points secondaires

| Élément | Constat |
| --- | --- |
| Binaire natif | `@documenso/skia-canvas` embarque `skia.node`, **30 Mo mesurés**, au cœur du rendu PDF |
| Effets de bord au démarrage | `LicenseClient.start()`, `TelemetryClient.start()`, `migrateDeletedAccountServiceAccount()`, `migrateLegacyServiceAccount()` au niveau module, rejoués à chaque cold start |
| URL interne | `NEXT_PRIVATE_INTERNAL_WEBAPP_URL` retombe sur l'URL publique ; la Deployment Protection active par défaut sur les Preview renverrait 401 à l'auto-appel |
| Node 24 | supporté par Vercel, ce n'est pas là que ça casse |

### 3.6 Ce qui aurait rendu la chose envisageable

Par honnêteté : ce n'était pas mathématiquement impossible. Il aurait fallu
au minimum remplacer `main.js` par un point d'entrée de fonction Vercel,
écrire un `vercel.json`, basculer les jobs sur Inngest, et faire tenir le
binaire Skia sous la limite de taille de fonction.

Le premier point est disqualifiant pour ce POC : remplacer le point d'entrée
serveur n'est pas une adaptation petite et réversible, c'est un fork de la
couche de déploiement amont, à maintenir à chaque montée de version. Mauvais
rapport effort / risque pour répondre à une question métier.

---

## 4. Ce que le choix local apporte

| Critère | Local (retenu) | Vercel |
| --- | --- | --- |
| Coût | 0 € | 0 € |
| Modifications upstream | aucune | remplacement du point d'entrée serveur |
| Scellement du PDF final | fiable | aléatoire |
| Cron de rattrapage | fonctionnel | inopérant |
| Documents hors du poste | non | oui |
| URL publique | non | oui |

Le seul avantage de Vercel était l'URL publique. Il ne compense pas la perte
de fiabilité sur la fonction même qu'on cherche à évaluer.

---

## 5. Si une URL publique devient nécessaire

Le jour où il faudra faire signer une personne réellement distante, l'option
la plus proche de ce montage est **Render**, qui figure dans les plateformes
supportées et dont le `render.yaml` est livré dans le dépôt Documenso avec
`plan: free`.

Réserve sérieuse, à tester et non à présumer : l'offre gratuite de Render
plafonne à 512 Mo de RAM alors que Documenso annonce 1 Go minimum, et le
scellement PDF via Skia est la phase la plus gourmande. Un échec par
saturation mémoire est plausible. Le PostgreSQL gratuit expire par ailleurs
au bout de 30 jours, et le service s'endort après 15 minutes d'inactivité.

Koyeb figure également dans les plateformes supportées ; son offre gratuite
n'a pas été vérifiée.

---

## 6. Sources

Toutes les affirmations techniques ci-dessus proviennent de la lecture du
code et de la documentation embarquée au commit `5603a9e` :

- `apps/docs/content/docs/self-hosting/getting-started/requirements.mdx`
- `apps/docs/content/docs/self-hosting/configuration/background-jobs.mdx`
- `apps/remix/server/main.js`
- `apps/remix/server/router.ts`
- `packages/lib/jobs/client/local.ts`
- `packages/lib/jobs/definitions/internal/seal-document.ts`
- `packages/lib/constants/app.ts`
- `render.yaml`, `railway.toml`, `docker/production/compose.yml`

Mesure locale : `npm install @documenso/skia-canvas@3.0.8-documenso.3`, puis
`node_modules/@documenso/skia-canvas/lib/skia.node` = 30 Mo.

---

## 7. Limite de validation

Le `compose.yml`, les cinq scripts et la génération du certificat ont été
validés : syntaxe compose résolue contre un `.env` réel, message d'erreur
vérifié en cas de secret manquant, certificat PKCS#12 effectivement produit
avec le bon sujet, clé privée effectivement détruite.

En revanche **la stack n'a pas été démarrée de bout en bout** : l'environnement
d'audit n'avait pas accès aux CDN de blobs d'images Docker (403 sur Docker Hub
comme sur ghcr.io), les images n'ont donc pas pu être téléchargées. Le premier
`./scripts/02-up.sh` sur le poste sera le premier démarrage réel, et c'est là
que se vérifieront les migrations Prisma et le parcours de signature.
