# E-commerce Pro — architecture et roadmap

E-commerce Pro poursuit le socle boutique DallyTrading après Freight Pro. Les Lots
A et B sont validés et fusionnés dans `main`. Le Lot C est développé sur
`feature/ecommerce-pro-lot-c`.

## 1. Architecture

La boutique n'est pas un second ERP. Odoo reste la source de vérité pour les
produits, prix, clients, commandes, méthodes de remise et frais ; Next.js reste
l'unique vitrine publique et le BFF.

Le socle `dally_shop` fournit :

- publication produit fermée par défaut sur `product.template` ;
- taxonomie publique `dally.shop.category` ;
- prix issus exclusivement d'une pricelist Odoo ;
- politique de stock et projection catalogue ;
- galerie produit ;
- panier scellé côté Next ;
- checkout invité ou connecté ;
- idempotence par identifiant de panier ;
- une seule `sale.order` ;
- workflow commercial séparé de `sale.order.state` ;
- espace client commandes ;
- projections strictes sans coûts, marges ni données internes ;
- neutralisation du portail natif Sale.

Le checkout ne confirme jamais la vente Odoo. La validation commerciale Lot B ne
la confirme pas non plus. Au Lot C, `action_confirm()` n'est autorisé que par une
action métier explicite d'autorisation de préparation, après validation
commerciale et après résolution des frais de remise. Le Lot C ne suppose aucun
paiement : le Lot D décidera si et quand un paiement devient une précondition.

## 2. Principes

1. **Pas de `website_sale`.** Next reste l'unique vitrine publique.
2. **Pas de modèle de commande parallèle.** `sale.order` reste l'autorité.
3. **Aucun prix fourni par le navigateur.** Odoo calcule tarif, taxes, frais et totaux.
4. **Idempotence avant effets métier.** Un rejeu ne duplique ni commande, ni transition, ni notification.
5. **État métier séparé de l'état natif Sale.** `received`, `validated`, `rejected`, `cancelled` restent des états DallyTrading.
6. **Droits minimaux.** Les écritures sensibles passent par des méthodes métier gardées ; pas d'ACL générique d'écriture sur les commandes boutique.
7. **Projection client par liste blanche.** Aucun nouveau champ Odoo ne traverse automatiquement.
8. **Notifications asynchrones.** Les actions métier mettent des messages dans `mail.mail`, sans SMTP synchrone.
9. **Méthode de remise résolue côté Odoo.** Le navigateur transmet uniquement un code public actif, jamais un identifiant ORM ni un montant.
10. **Snapshot logistique.** La méthode, les frais et l'adresse applicables sont figés sur la commande ; modifier le catalogue de livraison ne réécrit pas l'historique.
11. **Confirmation native explicitement gardée.** Seule l'autorisation de préparation Lot C peut appeler `sale.order.action_confirm()`.

## 3. Lots

### Lot A — Backoffice commandes — VALIDÉ

- rôle « Boutique — opérations » ;
- lecture de `sale.order` limitée à `dally_shop_order = True` ;
- lecture de `sale.order.line` limitée aux lignes de ces commandes ;
- menu Boutique → Commandes ;
- vues dédiées ;
- aucune mutation générique de la vente.

### Lot B — Workflow commercial — VALIDÉ

États métier :

- `received` — commande reçue ;
- `validated` — validation commerciale explicite ;
- `rejected` — refus avec motif client obligatoire ;
- `cancelled` — annulation après validation, avec motif client obligatoire.

Le Lot B apporte le journal immuable `dally.shop.order.transition`, les boutons
métier dédiés, les notifications mises en file, la projection portail du workflow
et la migration des commandes historiques vers `received`, sans notification
rétroactive. Une validation Lot B laisse `sale.order.state = draft` et ne crée ni
picking, ni facture, ni paiement.

RC validée sur pile isolée : frontend 831/831, Odoo 199 tests, canaris Lot B,
régressions Freight/Vehicle/Groupage/Shop et audit des journaux.

### Lot C — Livraison — EN RECETTE

Le Lot C ajoute :

- modèle `dally.shop.delivery.method` configurable ;
- méthodes actives exposées par code public, jamais par identifiant ORM ;
- types `pickup` et `delivery` ;
- politiques de frais `free`, `fixed`, `quote` ;
- méthodes par défaut `pickup` et `delivery_to_confirm` ;
- adresse de livraison distincte si nécessaire ;
- snapshot de l'adresse, de la méthode et des frais sur `sale.order` ;
- total global seulement lorsque les frais sont connus ;
- cotation manuelle des frais à confirmer ;
- autorisation explicite de préparation ;
- suivi `pending → preparing → ready`, puis `picked_up` pour un retrait ou
  `out_for_delivery → delivered` pour une livraison ;
- journal immuable `dally.shop.fulfillment.event` ;
- notifications de remise mises en file ;
- projection checkout et portail stricte ;
- migration des commandes historiques sans confirmation, picking, facture ou
  notification rétroactive.

Frontière importante : la commande reste en brouillon après checkout, validation
commerciale et cotation des frais. L'action « Autoriser la préparation » est le
seul point Lot C pouvant confirmer la vente native. Une commande déjà engagée en
préparation ne peut plus être annulée par le simple workflow Lot B : une future
annulation logistique devra traiter les effets Stock avant de fermer la commande.

### Lot D — Paiement

Le fournisseur de paiement sera derrière une abstraction DallyTrading :

- intention de paiement idempotente ;
- référence publique opaque ;
- webhook signé ;
- ledger d'événements ;
- aucune confiance dans un statut navigateur ;
- remboursement/annulation traçables ;
- décision explicite sur le lien paiement → autorisation de préparation.

### Lot E — Facturation

- politique explicite de création de facture ;
- facture après événement métier défini, jamais au simple checkout ;
- rapprochement paiement/facture ;
- documents client publiés explicitement.

### Lot F — Pilotage

- dashboard boutique ;
- commandes reçues, validées, à préparer, remises, annulées ;
- chiffre d'affaires confirmé et encaissé distingués ;
- alertes sur commandes bloquées ;
- métriques respectant les droits du lecteur.

## 4. Hors périmètre immédiat

Marketplace multi-vendeurs, promotions complexes, abonnements, fidélité,
multi-entrepôt avancé et synchronisation avec une boutique tierce restent hors du
chemin critique : catalogue → commande reçue → validation → paiement → préparation
→ livraison.
