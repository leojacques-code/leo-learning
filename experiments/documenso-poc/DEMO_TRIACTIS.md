# Démonstration Triactis — signature électronique

Date : 2026-09-15 · Instance Documenso auto-hébergée sur Oracle Cloud

**Données intégralement fictives.** Aucun dossier réel, aucun nom de client,
aucun montant du cabinet. Aucun courriel ne part vers l'extérieur : tout est
capté par une boîte aux lettres locale.

**Portée juridique.** Le certificat de signature est auto-signé. Il ne
constitue ni une signature qualifiée eIDAS, ni une QES, ni une AES, ni un
équivalent juridique d'un prestataire de confiance. Ce point doit être dit,
pas contourné : ce qui est démontré est la **chaîne de production**, pas le
niveau de preuve.

---

## Ce qu'on cherche à montrer

Une seule idée, déclinée sept fois : **le document ne se refait pas, les
données changent.**

Aujourd'hui, faire signer un NDA acquéreur demande neuf gestes, dont sept sont
mécaniques. Ce qui suit montre qu'il en reste deux.

---

## Démo 1 — Le modèle est préparé une fois

Trois modèles sont en place : NDA Cédant, NDA Acquéreur, Lettre de mission.

Sur chacun, les champs sont **déjà positionnés** : nom, société, fonction,
date, signature. Ils n'ont été placés qu'une fois, à la création du modèle.
Ils ne le seront plus jamais.

> « Le placement des champs, c'est le travail fastidieux. Il se fait une fois
> par modèle, pas une fois par envoi. »

À montrer : ouvrir un modèle, montrer les cadres posés sur la page 2.

---

## Démo 2 — Seules cinq ou six données changent

| Variable | Exemple |
| --- | --- |
| `MV_PROJET` | Projet Atlas |
| `MV_SOCIETE` | ALPHA CONSEIL SAS |
| `MV_PRENOM` `MV_NOM` | Jean Dupont |
| `MV_FONCTION` | Président |
| `MV_EMAIL` | jean.dupont@example.test |

Un appel d'API et le document existe : destinataire configuré, champs placés,
société et fonction déjà renseignées, courriel parti.

> « On ne touche plus au PDF. On renseigne les données du dossier, et le
> document est prêt. »

À montrer : la liste des documents, deux documents nés du même modèle avec des
sociétés différentes.

---

## Démo 3 — Envoi en masse

Un fichier CSV, une ligne par destinataire, et Documenso produit **un document
individualisé par ligne**, avec son propre lien et son propre suivi.

Le fichier de démonstration contient douze acquéreurs fictifs.

> « J'ai vingt acquéreurs à qui envoyer le même NDA. Je fournis un CSV. »

À montrer : depuis un modèle, l'action d'envoi en masse et le CSV.

---

## Démo 4 — Lien direct réutilisable

À ne pas confondre avec l'envoi en masse. Ce sont deux mécanismes différents,
et la confusion ruinerait la démonstration.

| | Envoi en masse | Lien direct |
| --- | --- | --- |
| Destinataires | connus d'avance, listés dans le CSV | inconnus, se présentent eux-mêmes |
| Nombre de documents | un par ligne, créés tout de suite | un par ouverture du lien |
| Courriel d'invitation | oui, nominatif | non |
| Identité du signataire | pré-remplie | saisie par le signataire |

> « Un lien unique que je partage. Chaque personne qui l'ouvre remplit son NDA
> et le signe. Chaque utilisation crée un nouveau document. »

---

## Démo 5 — Signature depuis un téléphone

C'est le moment le plus parlant, parce qu'il se vit plutôt qu'il ne s'explique.

1. ouvrir le lien reçu sur l'iPhone ;
2. renseigner les champs restants ;
3. signer **au doigt** ;
4. valider.

Le document passe en terminé, le PDF scellé est produit dans la foulée.

> « Le cédant n'a rien à installer, aucun compte à créer. Il ouvre un lien et
> il signe. »

---

## Démo 6 — Suivi

Chaque document porte un identifiant externe de dossier, par exemple
`DEAL-DEMO-001`. C'est lui qui relie proprement le document à une fiche CRM,
sans passer par un nom ou une adresse électronique comme clé métier.

Cycle : **Sent → Opened → Signed → Completed**.

Une page de suivi montre, en direct, les événements tels qu'un CRM les
recevrait.

---

## Démo 7 — Zoho, demain

```
  ZOHO              MIDDLEWARE            DOCUMENSO
  Deal + Contact ──▶ données dossier ──▶  document créé, prérempli, envoyé
                                                    │
  NDA_STATUS     ◀── mise à jour  ◀────────  webhook COMPLETED
  document_url                               externalId = DEAL-…
```

Rien n'est connecté à Zoho aujourd'hui, et c'est dit comme tel. Ce qui est
démontré, c'est que **la moitié Documenso existe et fonctionne** : l'API crée
les documents, le webhook remonte les statuts, l'identifiant externe fait le
lien. Reste à écrire la moitié Zoho.

Détail dans `ZOHO_INTEGRATION_BLUEPRINT.md`, y compris les questions à trancher
avant de construire.

---

## Déroulé de cinq minutes

| Temps | Geste | Phrase |
| --- | --- | --- |
| 00:00 | Ouvrir Documenso, page Templates | « Trois modèles préparés. » |
| 00:30 | Ouvrir « NDA Acquéreur », page 2 | « Les champs sont déjà posés. Une fois pour toutes. » |
| 01:00 | Ouvrir un document créé depuis ce modèle | « Même modèle, société différente. Rien n'a été retapé. » |
| 01:40 | Montrer l'envoi en masse et le CSV | « Vingt acquéreurs, un fichier. » |
| 02:20 | Ouvrir le lien direct | « Un lien réutilisable. Chaque ouverture crée un document. » |
| 03:00 | **Ouvrir le lien de signature sur l'iPhone** | « Le signataire n'installe rien. » |
| 03:20 | Signer au doigt, valider | |
| 04:00 | Revenir sur l'écran : statut Completed, télécharger le PDF | « Scellé, avec sa page de certificat. » |
| 04:30 | Ouvrir la page de suivi des événements | « Voilà ce que le CRM recevrait. » |
| 04:50 | Conclusion | voir ci-dessous |

**Conclusion, à dire telle quelle :**

> Sur cette instance auto-hébergée, il n'y a pas de coût par utilisateur ni par
> enveloppe. L'infrastructure est contrôlée, les documents restent chez nous,
> et l'intégration au CRM est possible. Ce qui reste à trancher, c'est le
> niveau de preuve juridique attendu : le certificat utilisé ici est un
> certificat de test, sans valeur eIDAS.

---

## Ce qu'il ne faut pas dire

- Que c'est équivalent à DocuSign **juridiquement**. Ça ne l'est pas en l'état.
- Que c'est prêt pour la production. C'est un POC : une seule machine, pas de
  sauvegarde hors site, pas de supervision.
- Que l'intégration Zoho est faite. Elle est **conçue**, pas faite.
- Qu'il n'y aura jamais de coût. Un certificat qualifié, lui, se paie.

Ce qui est vrai se tient tout seul. Le reste se retourne en réunion.

---

## Ce qui est vraiment impressionnant, et démontrable

1. **Signer au doigt sur son téléphone en vingt secondes**, sans compte ni
   application.
2. **Le PDF final est scellé cryptographiquement** : signature PAdES intégrée,
   certificat embarqué, page d'audit ajoutée. Vérifiable hors ligne.
3. **Un CSV de vingt lignes devient vingt documents individualisés**, chacun
   avec son suivi.
4. **Le lien direct** : un seul lien partagé, autant de NDA signés que de
   personnes qui l'ouvrent.
5. **Le webhook en direct** : le document est signé, et l'écran de suivi
   affiche l'événement dans la seconde. C'est ce que le CRM recevra.
