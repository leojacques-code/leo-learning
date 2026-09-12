# Résultats du test, jour 2

Date : 2026-09-12 · Documenso v2.18.0 · commit upstream `5603a9e`

Suite de `RESULTATS_TEST_2026-09-11.md`. Les deux réserves du jour 1 sont
levées, et trois constats nouveaux sont apparus, dont un qui mérite votre
attention avant tout hébergement.

---

## Verdict mis à jour

```
DOCUMENSO POC LOCAL

Status : GO AVEC RÉSERVES
```

Le statut ne change pas, mais les réserves ne sont plus les mêmes : celles du
jour 1 sont traitées, une nouvelle apparaît (constat 3 ci-dessous), qui ne
concerne pas l'usage local mais conditionnerait un hébergement.

---

## Réserve 1 du jour 1 : levée

**Champ trop étroit tronquant son contenu.** Confirmé comme étant la
conséquence du placement automatisé du test, pas un défaut du produit. Le
champ faisait 11,3 % de la largeur de page parce qu'un clic crée un champ à la
taille par défaut. En posant les champs à la main on les dimensionne sur le
cadre.

Reste un point de contrôle opérationnel, pas un blocage : **vérifier la
largeur des champs destinés à un nom ou une raison sociale longue, et relire
le PDF final avant diffusion.**

---

## Réserve 2 du jour 1 : levée

**Parcours mobile mené jusqu'au bout.** Ce qui manquait au jour 1 (l'insertion
du champ dans le document depuis un téléphone) a été réalisé, en calculant la
position écran du champ à partir de ses coordonnées en base (x = 26,6 %,
y = 57,0 % de la page 2) et du cadre du canvas de page.

| Étape mobile (390 px, profil iPhone 13) | Résultat |
| --- | --- |
| Ouverture du lien de signature | ✅ |
| Ouverture du tiroir bas | ✅ |
| Tracé de la signature au doigt | ✅ |
| Insertion du champ dans le document | ✅ |
| Finalisation (« Complete ») | ✅ |
| Enveloppe passée COMPLETED | ✅ |
| Job `internal.seal-document` | ✅ COMPLETED |
| PDF scellé produit | ✅ 215 295 octets |

Contrôle du PDF issu du parcours mobile :

```
/Sig        : présent
/SubFilter  : /ETSI.CAdES.detached
/ByteRange  : [0 189964 214542 753]
certificat  : O = Triactis POC, CN = Documenso Test Signing Certificate
```

**Le parcours complet fonctionne donc aussi depuis un téléphone.**

### Cause de l'erreur JavaScript, identifiée

L'erreur est reproductible, et sa cause est localisée dans le code amont :

`packages/ui/primitives/signature-pad/canvas.ts`, méthode `onResize()` :

```js
const oldWidth = this.currentCanvasWidth;
const oldHeight = this.currentCanvasHeight;
const ctx = this.getContext();
const imageData = ctx.getImageData(0, 0, oldWidth, oldHeight);
```

Aucune garde sur `oldWidth === 0`. Quand le pavé de signature est monté dans
un conteneur de taille nulle, ce qui est le cas du tiroir bas replié en
mobile, `getImageData` lève `IndexSizeError: The source width is 0`.

L'exception est levée dans un gestionnaire de redimensionnement : elle
interrompt ce seul rappel, pas le composant. Le canvas est réinitialisé au
redimensionnement suivant, avec ses vraies dimensions. C'est exactement ce qui
a été observé : erreur en console, tracé capté, signature validée,
finalisation réussie.

**Conclusion : bruit de console d'origine amont, sans effet fonctionnel.** Ce
n'est ni un défaut introduit par le POC, ni un obstacle. À signaler à l'éditeur
le jour où le sujet deviendrait sérieux.

---

## Constat 1 : persistance à travers un redémarrage complet du conteneur

Le conteneur d'exécution a été recyclé entre les deux journées. Toute la pile
était arrêtée au réveil. Après relance :

| Élément | État |
| --- | --- |
| Volume PostgreSQL | 67 Mo, intact |
| Compte | présent |
| Enveloppes | 2, statuts conservés (COMPLETED, PENDING) |
| PDF en base | 3 |
| Champs | 4 |

C'est un test de persistance plus dur que celui du jour 1, qui ne redémarrait
que le processus applicatif.

---

## Constat 2 : le PDF scellé survit à la rotation des secrets

Les fichiers sensibles ayant été détruits au nettoyage du jour 1,
`NEXTAUTH_SECRET`, les deux clés de chiffrement **et le certificat de
signature** ont dû être intégralement régénérés.

Après cette rotation complète, le PDF scellé la veille est re-servi à
l'identique : `200 application/pdf`, 228 212 octets, exactement la taille
d'origine.

**Le PDF signé est autoporteur.** Sa validité ne dépend ni des clés de
l'instance ni du certificat courant : la signature et le certificat sont
embarqués dans le fichier. C'est rassurant pour l'archivage.

Corollaire opérationnel en revanche : **perdre le `.env` empêche l'application
de redémarrer** et invalide les sessions. Le fichier doit être sauvegardé
comme un secret, au même titre que le certificat.

---

## Constat 3 : identifiants exposés dans l'URL si le JavaScript n'est pas actif

C'est le point nouveau qui mérite votre attention. Il ne concerne pas l'usage
local, mais il conditionnerait tout hébergement.

### Le fait

Le formulaire de connexion servi par le serveur est :

```html
<form class="flex w-full flex-col gap-y-4">
```

Ni `method`, ni `action`. En HTML, un formulaire sans `method` vaut
`method="GET"` et s'envoie sur l'URL courante. La soumission n'est rattrapée
que par le gestionnaire React `onSubmit`
(`apps/remix/app/components/forms/signin.tsx:328`).

Tant que le JavaScript n'a pas pris la main, soumettre le formulaire déclenche
donc un **GET portant les identifiants en clair dans la query string** :

```
http://localhost:3000/signin?email=test%40example.test&password=MotDePasseSecret123
```

Vérifié deux fois : une fois par accident (automatisation ayant soumis avant
l'hydratation) puis délibérément, JavaScript entièrement désactivé.
`/signup` et `/forgot-password` présentent la même structure de formulaire.

### La portée réelle, sans la surestimer

| Point | Constat |
| --- | --- |
| La connexion aboutit-elle ? | Non, la page se recharge simplement |
| Documenso journalise-t-il le mot de passe ? | **Non**, vérifié : zéro occurrence dans ses journaux |
| Historique du navigateur | **Oui**, l'URL complète y entre |
| Journaux d'un reverse proxy en amont | **Oui** par défaut : nginx, Caddy, Traefik et les load balancers cloud journalisent la query string |
| Occurrence en usage normal | Faible : le JavaScript s'hydrate vite |
| Occurrence en conditions dégradées | Réelle : réseau lent, erreur JS, proxy d'entreprise filtrant, ou utilisateur rapide au premier chargement |

Ce qui rend le point matériel plutôt que théorique : la documentation de
Documenso **exige** un reverse proxy en production, et ces proxies journalisent
la query string par défaut.

### Conséquence pratique

- **Pour le POC local : sans objet.** Pas de proxy, pas d'exposition réseau.
- **Avant tout hébergement : à traiter.** La parade sans toucher à Documenso
  est de configurer le reverse proxy pour ne pas journaliser la query string
  sur `/signin`, `/signup` et `/forgot-password`. C'est une ligne de
  configuration, pas un chantier.

À remonter à l'éditeur également : la correction amont propre serait un
`method="post"` sur ces formulaires.

---

## Constat 4 : « Detect with AI » est payant et sort les documents

La fonction de détection automatique des champs repérée dans l'éditeur, qui
aurait pu alléger le placement manuel, exige selon la documentation officielle
(`self-hosting/configuration/advanced/ai-features.mdx`) :

- un projet Google Cloud avec l'API Vertex AI activée **et la facturation
  active** ;
- une clé API Vertex AI Express avec accès aux modèles Gemini ;
- les variables `GOOGLE_VERTEX_PROJECT_ID` et `GOOGLE_VERTEX_API_KEY`.

Deux objections dirimantes pour ce POC :

1. **Ce n'est pas gratuit.** La facturation Google Cloud doit être active.
2. **Le contenu des documents part chez Google.** Pour un cabinet M&A qui
   manipule des NDA et des dossiers de cession, c'est une décision de
   confidentialité, pas un réglage technique.

**Recommandation : ne pas activer.** Le placement manuel des champs reste la
voie sobre, et il se fait une fois par modèle de document, pas à chaque envoi.

---

## Scénarios de test couverts

| # | Scénario | Résultat |
| --: | --- | --- |
| 1 | Un signataire, signature complète | ✅ jour 1, bureau |
| 2 | Document créé mais non signé | ✅ enveloppe 2 laissée PENDING une journée |
| 3 | Document ouvert puis quitté | ✅ ouvert, quitté, conteneur redémarré entre-temps |
| 4 | Signature complète après retour sur le lien | ✅ lien rouvert le lendemain, après rotation des secrets |
| 5 | PDF final téléchargé | ✅ `200 application/pdf`, taille conforme |
| 6 | Parcours complet depuis un téléphone | ✅ jour 2 |

---

## Ce qui reste ouvert

1. **Rejouer via le `compose.yml` livré.** Toujours impossible ici : les CDN de
   blobs d'images restent inaccessibles (403 sur Docker Hub et ghcr.io,
   revérifié ce jour). C'est le seul écart entre le testé et le livré, et il se
   ferme en une commande sur votre poste.
2. **Vos vrais modèles de documents.** Le POC tourne sur un NDA fictif de deux
   pages. Le comportement sur vos documents réels, plus longs et à mise en page
   plus dense, reste à mesurer.
3. **La charge du placement manuel**, une fois vos modèles connus. À arbitrer
   sur pièces, sachant que « Detect with AI » est écarté (constat 4).
