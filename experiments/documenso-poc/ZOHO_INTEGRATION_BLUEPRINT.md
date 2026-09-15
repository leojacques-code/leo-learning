# Intégration Zoho CRM : ce qui serait à construire

Date : 2026-09-15 · Branche : `leolearning`

**Rien n'est connecté.** Aucune application Zoho n'a été créée, aucun
identifiant demandé, aucun appel à l'API Zoho effectué. Ce document décrit une
intégration **possible**, avec assez de précision pour être chiffrée et
décidée, pas une intégration en place.

Il s'appuie sur ce qui est **réellement vérifié** du côté Documenso par le POC
déployé : l'API v2 utilisée pour créer les modèles et les documents, les
webhooks configurés, et l'identifiant externe porté par chaque document.

---

## 1. Le problème que cela résout

Aujourd'hui, pour faire signer un NDA acquéreur :

1. on ouvre le modèle Word ;
2. on remplace à la main le nom du projet, la société, le prénom, le nom, la
   fonction ;
3. on exporte en PDF ;
4. on rédige le mail ;
5. on envoie ;
6. on attend ;
7. on relance ;
8. on classe le PDF signé ;
9. on note quelque part que la personne a signé.

Les étapes 1 à 5 et 8 à 9 sont mécaniques : elles ne demandent aucun jugement.
Ce sont exactement celles qu'une intégration supprime.

Le jugement reste entier là où il est : à qui on envoie, ce qu'on négocie, ce
qu'on accepte.

---

## 2. Architecture cible

```
  ZOHO CRM                      MIDDLEWARE                    DOCUMENSO
  ────────                      ──────────                    ─────────

  Deal (MVxxxx)
  Contact             ──────▶   lecture des champs
  Account                       du dossier
       ▲                              │
       │                              ▼
       │                        choix du modèle
       │                        + valeurs variables
       │                              │
       │                              ▼
       │                                            ──────▶  POST /api/v2/envelope/use
       │                                                     payload :
       │                                                       envelopeId  (le modèle)
       │                                                       recipients  (le signataire)
       │                                                       prefillFields
       │                                                       externalId  (= id du Deal)
       │                                                       distributeDocument: true
       │                                                              │
       │                                                              ▼
       │                                                     courriel au signataire
       │                                                     lien de signature
       │                                                              │
       │                                                              ▼
       │                                                     signature, scellement
       │                                                              │
       │                        réception  ◀──────────────────────────┘
       └──────────────────────  mise à jour                  webhook DOCUMENT_COMPLETED
                                de la fiche                  payload.externalId = DEAL-…
```

Le middleware n'est pas un gros système : c'est un service qui reçoit deux
sortes d'appels (un bouton depuis Zoho, un webhook depuis Documenso) et tient
la correspondance entre les deux. Une fonction serverless ou un petit conteneur
sur la même VM suffit.

---

## 3. Le point qui rend tout cela propre : `externalId`

Chaque document créé porte un identifiant externe, décidé par nous.

| Document | externalId |
| --- | --- |
| NDA acquéreur du dossier MV0412, acquéreur n° 7 | `MV0412-NDA-ACQ-007` |
| NDA cédant du dossier MV0412 | `MV0412-NDA-CED` |
| Lettre de mission MV0412 | `MV0412-LM` |

Dans le POC déployé, les documents de démonstration portent `DEAL-DEMO-001`,
`DEAL-DEMO-002`, `DEAL-DEMO-003`.

Pourquoi c'est important : le webhook de retour porte cet identifiant. Le
middleware n'a donc **rien à deviner** — ni à rapprocher sur un nom, ni sur une
adresse électronique, qui changent, se dupliquent et se saisissent mal. Il lit
`externalId`, il sait quelle fiche mettre à jour.

C'est la différence entre une intégration qui tient et une intégration qui
dérive au bout de six mois.

---

## 4. Correspondance des champs

### Zoho → Documenso (aller)

| Champ Zoho | Variable du modèle | Champ Documenso |
| --- | --- | --- |
| `Deal.Deal_Name` | `MV_PROJET` | titre du document (`override.title`) |
| `Deal.id` | — | `externalId` |
| `Account.Account_Name` | `MV_SOCIETE` | champ TEXT « Société » (prefill) |
| `Contact.First_Name` | `MV_PRENOM` | `recipients[].name` (partie prénom) |
| `Contact.Last_Name` | `MV_NOM` | `recipients[].name` (partie nom) |
| `Contact.Email` | `MV_EMAIL` | `recipients[].email` |
| `Contact.Title` | `MV_FONCTION` | champ TEXT « Fonction » (prefill) |
| — | `MV_DATE` | champ DATE, renseigné par le signataire au moment de signer |

La date n'est pas préremplie **volontairement** : la date qui compte est celle
de la signature, pas celle de la préparation du document.

### Documenso → Zoho (retour)

| Événement webhook | Champ Zoho à écrire | Valeur |
| --- | --- | --- |
| `DOCUMENT_SENT` | `NDA_Status` | `Sent` |
| `DOCUMENT_OPENED` | `NDA_Status` | `Opened` |
| `DOCUMENT_SIGNED` | `NDA_Status` | `Signed` |
| `DOCUMENT_COMPLETED` | `NDA_Status` | `Completed` |
| | `NDA_Signed_At` | horodatage de l'événement |
| | `NDA_Document_Url` | lien de téléchargement du PDF scellé |
| `DOCUMENT_REJECTED` | `NDA_Status` | `Rejected` |
| `DOCUMENT_CANCELLED` | `NDA_Status` | `Cancelled` |

Ces champs Zoho n'existent pas aujourd'hui : il faudrait les créer dans le
module Deals (ou dans un module dédié « NDA » si l'on veut plusieurs NDA par
dossier, ce qui est le cas réel côté acquéreurs).

**Point de structure à arbitrer avant de construire quoi que ce soit.** Un
dossier a un cédant mais N acquéreurs. Trois champs sur le Deal suffisent pour
le NDA cédant et la lettre de mission ; pour les NDA acquéreurs il faut un
module ou un sous-formulaire à N lignes, une ligne par acquéreur approché. Le
module `NDAs Envoyés` existant est probablement le bon point d'accroche, mais
cela reste à vérifier sur la structure réelle avant tout développement.

---

## 5. Ce que le middleware doit faire, concrètement

### Aller : création du document

```
POST /api/v2/envelope/use
Authorization: Bearer <jeton d'API Documenso>
Content-Type: multipart/form-data

payload = {
  "envelopeId": "<id du modèle NDA Acquéreur>",
  "externalId": "MV0412-NDA-ACQ-007",
  "recipients": [
    { "id": <id du destinataire dans le modèle>,
      "email": "jean.dupont@exemple.fr",
      "name": "Jean Dupont" }
  ],
  "prefillFields": [
    { "id": <id du champ Société>, "type": "text", "value": "ALPHA CONSEIL SAS" },
    { "id": <id du champ Fonction>, "type": "text", "value": "Président" }
  ],
  "override": { "title": "Projet Atlas - NDA Acquereur - ALPHA CONSEIL SAS" },
  "distributeDocument": true
}
```

La réponse contient l'identifiant du document créé **et le lien de signature de
chaque destinataire**. C'est ce qui permet, si on le souhaite, de ne pas passer
par le courriel du tout et de transmettre le lien par un autre canal.

C'est exactement l'appel que le POC déployé exécute, et qui est vérifié.

### Retour : réception du webhook

```
POST <url du middleware>
{
  "event": "DOCUMENT_COMPLETED",
  "payload": {
    "externalId": "MV0412-NDA-ACQ-007",
    "status": "COMPLETED",
    "title": "...",
    ...
  }
}
```

Le middleware lit `externalId`, en déduit le dossier et l'acquéreur, et écrit
dans Zoho.

---

## 6. Ce qu'il faut décider avant de construire

Ces questions ne sont pas techniques : y répondre est un préalable, pas un
détail d'implémentation.

1. **Où vivent les statuts côté Zoho ?** Champs sur le Deal, ou module dédié ?
   Cela dépend de la structure des `NDAs Envoyés`, à regarder de près.
2. **Qui déclenche l'envoi ?** Un bouton dans Zoho actionné par un humain, ou
   un automatisme sur changement d'étape ? Un automatisme qui envoie des NDA
   tout seul est un risque. Recommandation : bouton, décision humaine.
3. **Où vit le middleware ?** La VM Oracle actuelle peut l'héberger, mais elle
   porte déjà le POC : mélanger un composant de production avec un POC est une
   mauvaise idée à terme.
4. **Que se passe-t-il si le webhook n'arrive pas ?** Il faut un rattrapage :
   une relecture périodique des documents par l'API pour resynchroniser les
   statuts. Sans cela, une fiche restera à « Sent » alors que le document est
   signé, et la confiance dans le suivi est perdue.
5. **Le certificat.** Le POC signe avec un certificat auto-signé sans portée
   juridique. Un usage réel suppose un arbitrage sur le niveau de signature
   attendu (simple, avancée, qualifiée), qui est une question juridique avant
   d'être technique, et qui a un coût.

---

## 7. Charge estimée

Estimation indicative, à confirmer une fois les questions du § 6 tranchées.

| Lot | Contenu | Ordre de grandeur |
| --- | --- | --- |
| 1 | Champs et module Zoho, modèles Documenso définitifs | 1 à 2 jours |
| 2 | Middleware aller (bouton Zoho → création du document) | 2 à 3 jours |
| 3 | Middleware retour (webhook → mise à jour Zoho) | 1 à 2 jours |
| 4 | Rattrapage, journalisation, reprise sur erreur | 1 à 2 jours |
| 5 | Hébergement, supervision, recette | 1 à 2 jours |

Ce chiffrage suppose un modèle de document stabilisé. Si les modèles changent
encore, le lot 1 se répète.

---

## 8. Ce qui est déjà acquis grâce au POC

Ce n'est pas un projet qui partirait de zéro. Sont **vérifiés sur l'instance
déployée** :

- l'API v2 de Documenso crée des modèles avec leurs champs positionnés ;
- `envelope/use` crée un document depuis un modèle, le préremplit, le distribue
  et renvoie les liens de signature ;
- l'identifiant externe est porté par le document et revient dans le webhook ;
- les webhooks partent réellement et sont reçus (récepteur de démonstration en
  place sur la même pile) ;
- l'envoi en masse depuis un CSV fonctionne dans l'édition Community ;
- le lien direct réutilisable fonctionne ;
- le PDF final est scellé cryptographiquement et téléchargeable par l'API.

Ce qui reste à construire, c'est la moitié Zoho et le middleware. La moitié
Documenso est démontrée.
