# Sourcing

Le sous-système sourcing porte un dossier du besoin client jusqu'à l'achat et la
vente. Ce n'est pas un formulaire adossé à quelques champs.

> ⚠️ **Les tests Odoo de ce module n'ont pas été exécutés.** Ils exigent une instance
> Odoo 19 DallyTrading dédiée, qui n'existe pas encore. Leur passage reste à prouver.

---

## 1. Périmètre

Le sourcing répond à : *« je cherche ce produit, ce fournisseur, ce fabricant ou cette
solution d'approvisionnement »*.

La participation directe de DallyTrading à un achat-revente relèvera de `dally_trade`.
Cette frontière est tenue volontairement : sans elle, l'un des deux modules devient un
fourre-tout.

Rien n'est spécifique à une catégorie de produits. Les mêmes modèles servent les
denrées agricoles, les équipements, les biens de consommation et les fournitures
professionnelles.

## 2. Le cycle métier

```text
Demande client → Qualification → Recherche fournisseurs → Fournisseurs candidats
   → Offres fournisseurs → Comparaison → Proposition DallyTrading → Négociation
   → Acceptation client → Achat fournisseur → Vente client → Exécution → Clôture
```

Chaque étape est une décision humaine. **Rien en aval n'est créé automatiquement** :
ni contact, ni opportunité CRM, ni bon de commande, ni expédition.

## 3. Modèles

| Modèle | Rôle | Référence |
|---|---|---|
| `dally.sourcing.request` | La demande du client, conservée telle que soumise | `DT-SRC-YYYY-NNNNNN` |
| `dally.sourcing.supplier` | La participation d'un `res.partner` à une recherche | — |
| `dally.sourcing.offer` | Ce qu'un fournisseur a chiffré — **interne** | — |
| `dally.sourcing.proposal` | Ce que DallyTrading propose au client | `DT-SRP-YYYY-NNNNNN` |

### Ce qui est réutilisé plutôt que reconstruit

| Besoin | Réutilisé |
|---|---|
| Références | `dally.reference.mixin` (`dally_core`) |
| Anti-doublon contact | `res.partner._dally_find_existing` (`dally_crm`) |
| Authentification, scopes, idempotence, journalisation | `dally_api` |
| Incoterms | `account.incoterms` natif |
| Unités | `uom.uom` natif |
| Fournisseur, client | `res.partner` natif |
| Achat, vente | `purchase.order`, `sale.order` natifs |

**Aucune seconde base de fournisseurs.** Un fournisseur est un `res.partner` ; le même
peut figurer sur vingt demandes avec une issue différente à chaque fois.

## 4. La frontière de confidentialité

C'est la contrainte structurante du module.

```text
Offre fournisseur (dally.sourcing.offer)
   coût unitaire, transport, assurance, douane, scores, notes
        │
        │  _dally_draft_from_offer  ← le seul pont
        │  ne fait traverser qu'un prix de vente dérivé
        ▼
Proposition client (dally.sourcing.proposal)
   prix de vente, transport estimé, frais de service, conditions
```

Ce sont **deux modèles distincts, pas un modèle avec un filtre**. Conséquences :

- l'offre n'a **aucun endpoint public** et n'apparaît dans **aucun DTO** ;
- l'accès ORM à l'offre exclut **entièrement** les groupes commercial et lecture seule ;
- `cost_basis`, `margin` et `margin_rate` portent `groups=` : l'ORM les retire pour
  quiconque n'est pas manager sourcing ou finance.

« Montrer l'offre au client » ne peut donc pas arriver par accident : il faudrait
écrire un nouvel endpoint exprès.

### Ce qu'un utilisateur commercial voit et ne voit pas

| Élément | Commercial | Sourcing User | Sourcing Manager | Finance |
|---|---|---|---|---|
| Demande | lecture | lecture + écriture | lecture + écriture | — |
| Fournisseurs candidats | **aucun accès** | complet | complet | — |
| Offres fournisseurs | **aucun accès** | complet | complet | lecture |
| Proposition | lecture | lecture + écriture | complet | — |
| `cost_basis`, `margin` | **retirés par l'ORM** | **retirés par l'ORM** | visibles | visibles |
| `internal_notes` | visibles | visibles | visibles | visibles |

Un commercial peut donc présenter une proposition **sans apprendre ce qu'elle a coûté**.

## 5. Workflow

Seize états. La carte des transitions est déclarée comme donnée
(`ALLOWED_TRANSITIONS`), lisible d'un coup d'œil et vérifiée par un test.

```text
new → to_qualify → researching → suppliers_identified → offers_received
    → comparing → proposal_ready → proposal_sent → negotiating → accepted
    → purchasing → in_progress → completed

on_hold    depuis tout état en cours, et retour à l'état d'origine
rejected   terminal
cancelled  terminal
```

Toutes les transitions passent par `_dally_set_state`, jamais par une affectation
directe de `state`. C'est ce qui empêche une demande `new` de devenir `completed` — un
dossier clos sans fournisseur, sans offre et sans achat derrière lui.

`completed`, `rejected` et `cancelled` sont **terminaux**. La seule sortie est
`action_reopen()`, l'action métier explicite exigée : une demande annulée ne dérive pas
d'elle-même vers l'achat.

### Garde-fous métier

| Action | Condition |
|---|---|
| `action_mark_suppliers_identified` | au moins un fournisseur candidat |
| `action_mark_offers_received` | au moins une offre |
| `action_prepare_proposal` | au moins une offre |
| `action_send_proposal` | une proposition avec un montant, et un destinataire |
| `action_validate_price` (proposition) | un montant total strictement positif |
| `action_mark_ready` (proposition) | un montant, une date de validité **et un prix validé** |
| `action_create_purchase_order` | demande acceptée, offre sélectionnée, fournisseur, **produit catalogue**, quantité > 0, prix d'achat > 0, devise, société |
| `action_create_sale_order` | demande acceptée, client, proposition acceptée, **produit catalogue**, quantité > 0, prix de vente > 0, devise, société |

Un devis sans date de validité engagerait DallyTrading indéfiniment : les prix
fournisseurs et les taux de fret bougent.

### Le prix commercial est décidé, jamais calculé

Une proposition rédigée depuis une offre part **sans prix de vente**. Aucune marge
par défaut n'est appliquée, et la constante Python qui le faisait a été supprimée :
un taux codé en dur est un prix que l'entreprise annonce sans que personne ne l'ait
choisi, et le client l'oppose ensuite à DallyTrading.

Ce qui traverse la frontière de confidentialité est le `cost_basis` seul — lui-même
restreint par `groups=` — afin que le responsable qui fixe le prix voie ce qu'il doit
couvrir.

Le passage à `ready` puis `sent` exige `price_validated`, positionné par
`action_validate_price()` et réservé à la direction sourcing, à la finance et à la
direction générale : un utilisateur qui ne voit pas le coût n'est pas en mesure de juger
si le prix le couvre. La traçabilité est conservée (`price_validated_by_id`,
`price_validated_on`).

Contrairement à `cost_basis` et `margin`, ces trois champs **ne portent pas** de
`groups=`. Savoir si un prix est approuvé est une information de workflow, pas une
donnée confidentielle : un utilisateur sourcing doit pouvoir lire pourquoi sa
proposition ne partira pas. La restriction porte donc sur *qui peut le poser*, vérifiée
en Python dans `_dally_check_price_validation_rights()` et non par un groupe de champ —
un groupe de champ aurait de surcroît cassé le retrait automatique de la validation,
puisque celui-ci écrit `price_validated` au nom d'un utilisateur qui n'a pas le droit de
valider.

Toute modification du prix, de la quantité, du fret estimé, des frais de service, des
autres charges, de la taxe ou de la devise **retire la validation** : sinon
l'approbation porterait sur un montant que personne n'a approuvé.

Si DallyTrading veut un jour une marge par défaut, elle relèvera de la configuration —
administrable, documentée, éventuellement dépendante du type d'opération — pas d'une
constante de module.

### Aucune commande commerciale vide

`action_create_purchase_order()` et `action_create_sale_order()` créent la commande
**avec sa ligne, en un seul appel**, ou refusent avec un `UserError` qui énumère ce
qui manque.

Une commande sans ligne utilisable est pire qu'aucune commande : elle peut être
confirmée, elle apparaît dans le reporting, et plus personne ne sait ce qui devait
être acheté. Une ligne de vente à prix nul, elle, peut être confirmée *et facturée* —
le client reçoit une facture pour rien.

Le point de blocage réel est le produit : une ligne `purchase.order.line` ou
`sale.order.line` exige un `product_id`, et une demande de sourcing décrit un besoin,
pas une référence de catalogue. D'où le champ `product_id` sur
`dally.sourcing.request`, vide à la réception et à renseigner avant conversion. Créer
le produit automatiquement remplirait le catalogue de quasi-doublons que personne n'a
arbitrés.

L'unité de mesure de la ligne est **délibérément omise** : Odoo la dérive du produit,
qui en est la source de vérité.

Les frais de service d'une proposition font une ligne distincte, jamais fondus dans le
prix unitaire — le client voit ce qu'il paie, et la ligne peut être taxée
différemment. Elle n'est ajoutée que si le paramètre système
`dally_sourcing.service_fee_product_ref` désigne un produit de service ; sinon les
frais ne sont pas ventilés et l'opérateur ajoute la ligne, ce qui est visible plutôt
que surprenant.

Les deux conversions restent **idempotentes** : relancées, elles ouvrent le document
existant au lieu d'en émettre un second.

## 6. Idempotence

`request_uuid` porte une contrainte `UNIQUE`. La recherche d'idempotence utilise
`active_test=False` : **sans cela, le rejeu d'une demande archivée tomberait dans
`create()`, heurterait la contrainte et remonterait en 500** au lieu de renvoyer la
référence d'origine. C'est exactement le bug déjà trouvé sur les demandes de devis, et
il est couvert ici par un test dès le départ.

Un rejeu ne consomme pas de nouveau numéro de séquence.

## 7. Sécurité

### Groupes

| Groupe | Rôle |
|---|---|
| `dally_core.group_dally_sourcing` | **Sourcing User** — existait déjà, réutilisé |
| `dally_sourcing.group_dally_sourcing_manager` | Sélection d'offre, propositions, coûts et marges |
| `dally_sourcing.group_dally_sourcing_api` | Création publique uniquement |

Le tier manager est ce qui garde l'argent : un utilisateur sourcing recherche des
fournisseurs et enregistre des offres, un manager décide sur quelle offre acheter et à
quel prix revendre.

### Utilisateur d'API dédié

`user_dally_api_sourcing` — le **troisième** utilisateur d'intégration, après ceux des
leads et du tracking.

Réutiliser un existant serait plus simple et faux : l'utilisateur des leads porte
`group_dally_commercial`, qui implique `group_dally_readonly`, précisément le groupe
qui garde `internal_notes`. Celui-ci n'est dans **aucun** groupe métier, donc l'ORM
retire les notes internes, les coûts et les marges avant que le moindre code de
contrôleur ne s'exécute.

### Record rule sur l'API

L'utilisateur d'API ne lit que **ses propres** enregistrements
(`create_uid = user.id`). L'endpoint de création n'a besoin de relire que le sien pour
l'idempotence ; sans cette règle il pourrait lire toutes les demandes, y compris celles
saisies par le personnel avec un contenu interne plus riche.

### Multi-société

Une record rule globale sur les quatre modèles. Prévue dès maintenant pour ne pas avoir
à la rétrofitter — et **sans aucun rapport avec SEN CONTAINERS**, qui reste un
`res.partner` externe standard sans dépendance technique d'aucune sorte.

## 8. API

### `POST /api/v1/sourcing/requests`

Scope **`sourcing:write`** — celui qui existait déjà. Pas de `sourcing:create` : la
convention du projet est `<domaine>:write` (`leads:write`, `quotes:write`), et une
seconde orthographe pour le même domaine mènerait à accorder le mauvais scope à une clé.

```json
{
  "request_uuid": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
  "service_code": "sourcing",
  "customer": { "first_name": "…", "last_name": "…", "company": "…",
                "email": "…", "phone": "…", "whatsapp": "…" },
  "product": { "name": "…", "description": "…", "specifications": "…",
               "reference": "…", "url": "…" },
  "quantity": 200,
  "uom": "Units",
  "budget": 40000,
  "target_unit_price": 190,
  "currency": "EUR",
  "preferred_origin_country": "CN",
  "destination_country": "SN",
  "requested_deadline": "2026-06-01",
  "notes": "…",
  "utm": { "source": "…", "medium": "…", "campaign": "…" }
}
```

**201** renvoie uniquement la référence, le service et le statut. Aucun identifiant de
base, et aucune indication de savoir si un contact existant a été rapproché — c'est une
information commerciale interne.

| Statut | Code | Cause |
|---|---|---|
| 422 | `missing_fields` | produit ou nom absent |
| 422 | `no_contact_channel` | ni e-mail ni téléphone |
| 422 | `invalid_quantity` | quantité nulle ou négative |
| 422 | `unknown_currency` / `unknown_country` / `unknown_service` | code inconnu |
| 422 | `invalid_date` / `invalid_date_range` | date mal formée ou incohérente |
| 422 | `field_too_long` / `field_too_large` | dépassement de borne |

`service_code` est **facultatif** et vaut `sourcing` par défaut : cet endpoint *est*
l'endpoint sourcing. Un code explicite inexistant reste refusé.

### Pas d'endpoint de lecture

`GET /api/v1/sourcing/requests/<reference>` n'est **volontairement pas** implémenté :
il n'existe pas encore de portail client, donc rien ne le consomme, et une surface de
lecture publique sans consommateur est de la surface d'attaque pour rien. Le modèle
expose déjà `_dally_public_payload` pour le jour où le portail arrive.

## 9. Site

| Route | Rôle |
|---|---|
| `/sourcing` | Page de conversion : explication, formulaire 5 étapes, FAQ |
| `POST /api/sourcing` | BFF, seul chemin entre le navigateur et Odoo |

```text
Navigateur → /api/sourcing (Next.js) → OdooGateway → DallyApiAdapter
          → POST /api/v1/sourcing/requests → dally_sourcing
```

### Deux pages sourcing, deux rôles

`/sourcing` convertit, `/activites/sourcing-international` explique. Sans cette
distinction les deux viseraient « sourcing Sénégal » et se cannibaliseraient. Le CTA de
la page activité pointe donc vers `/sourcing` (champ `requestHref`), et leurs mots-clés
sont différenciés.

## 10. Documents

Le téléversement n'est **pas** implémenté. L'abstraction `DocumentStorage` existe et
attend un choix de bucket, de durée de conservation et de types acceptés — des décisions
métier, pas techniques. Le formulaire indique au client de transmettre ses documents par
e-mail ou WhatsApp en citant sa référence, ce qui est moins commode et honnête.

Aucun fichier utilisateur n'est écrit dans le système de fichiers du frontend, qui est
jetable et reconstruit à chaque déploiement.

## 11. Limites connues

| Limite | Raison |
|---|---|
| **Tests Odoo non exécutés** | Aucune instance Odoo 19 DallyTrading |
| Pas d'e-mail transactionnel | SMTP relève de l'administrateur ; `action_send` enregistre le fait plutôt que de simuler un envoi |
| Pas de conversion multi-devises automatique entre offres | Convertir en silence masquerait le taux employé ; chaque offre garde sa devise et la comparaison est humaine |
| Pas de marge par défaut | Une politique tarifaire n'est pas une constante Python. Le brouillon part sans prix, et le prix doit être saisi puis validé explicitement |
| Scores 0–5 sans pondération | Une pondération dépend du client, de la saison et de l'appétit au risque. La décision reste humaine (§14) |
| Pas de lien automatique vers `dally.shipment` | Le fret reste sous `dally_freight` ; une expédition naît quand l'opération devient logistique (§24) |
| `product_id` à renseigner avant conversion | Une ligne de commande Odoo exige un produit réel ; le créer automatiquement remplirait le catalogue de quasi-doublons non arbitrés |
| Frais de service non ventilés sans produit configuré | Ajouter un produit de service au catalogue en silence est la façon dont un catalogue devient inutilisable |
