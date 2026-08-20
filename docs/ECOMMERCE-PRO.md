# E-commerce Pro — architecture et roadmap

E-commerce Pro poursuit le socle boutique DallyTrading après Freight Pro. `main`
contient le Lot A validé ; le Lot B est développé sur
`feature/ecommerce-pro-lot-b`.

## 1. Architecture

La boutique n'est pas un second ERP. Odoo reste la source de vérité pour les
produits, prix, clients et commandes ; Next.js est la vitrine et le BFF public.

Le socle `dally_shop` fournit :

- publication produit fermée par défaut sur `product.template` ;
- taxonomie publique `dally.shop.category` ;
- prix issus exclusivement d'une pricelist Odoo ;
- politique de stock et projection catalogue ;
- galerie produit ;
- panier scellé côté Next ;
- checkout invité ou connecté ;
- idempotence par identifiant de panier ;
- une seule `sale.order`, créée en `draft` ;
- espace client commandes ;
- projections strictes sans coûts, marges ni données internes ;
- neutralisation du portail natif Sale.

Le checkout ne confirme jamais la vente Odoo. Cette frontière reste vraie au Lot
B : « commande validée » est un état commercial DallyTrading, distinct de
`sale.order.state`, et ne crée ni facture, ni paiement, ni picking.

## 2. Principes

1. **Pas de `website_sale`.** Next reste l'unique vitrine publique.
2. **Pas de modèle de commande parallèle.** `sale.order` reste l'autorité.
3. **Aucun prix fourni par le navigateur.** Odoo calcule tarif, taxes et totaux.
4. **Idempotence avant effets métier.** Un rejeu ne duplique ni commande, ni transition, ni notification.
5. **État métier séparé de l'état natif Sale.** La validation commerciale n'appelle pas `action_confirm()`.
6. **Droits minimaux.** L'opérateur boutique conserve des ACL de lecture seule sur `sale.order`; les transitions passent par des méthodes métier gardées.
7. **Projection client par liste blanche.** Aucun nouveau champ Odoo ne traverse automatiquement.
8. **Notifications asynchrones.** Une transition crée un `mail.mail` dans la transaction ; aucun envoi SMTP synchrone n'est déclenché par l'action métier.

## 3. Lots

### Lot A — Backoffice commandes — VALIDÉ

- rôle « Boutique — opérations » ;
- lecture de `sale.order` limitée à `dally_shop_order = True` ;
- lecture de `sale.order.line` limitée aux lignes de ces commandes ;
- menu Boutique → Commandes ;
- vues dédiées ;
- aucune mutation générique de la vente.

RC validée sur pile isolée : validation statique, tests Odoo, canaris de sécurité,
checkout, galerie et régressions fret/véhicule/groupage.

### Lot B — Workflow commercial — EN RECETTE

États métier :

- `received` — commande reçue ;
- `validated` — validation commerciale explicite ;
- `rejected` — refus avec motif client obligatoire ;
- `cancelled` — annulation après validation, avec motif client obligatoire.

Implémentation :

- champ workflow séparé de `sale.order.state` ;
- transitions bornées `received → validated|rejected`, puis `validated → cancelled` ;
- journal immuable `dally.shop.order.transition` ;
- boutons métier dédiés dans le backoffice ;
- motif client séparé des notes internes ;
- état et libellé alignés dans le portail ;
- notifications transactionnelles mises dans la file e-mail Odoo ;
- migration des commandes historiques vers `received` sans notification rétroactive ;
- aucune confirmation Vente, aucun picking, aucune facture, aucun paiement.

### Lot C — Livraison

- modes de remise configurables ;
- adresse de livraison distincte si nécessaire ;
- calcul/validation des frais côté Odoo ;
- préparation et picking seulement quand la règle métier l'autorise ;
- suivi de la remise et de la livraison.

### Lot D — Paiement

Le fournisseur de paiement sera derrière une abstraction DallyTrading :

- intention de paiement idempotente ;
- référence publique opaque ;
- webhook signé ;
- ledger d'événements ;
- aucune confiance dans un statut navigateur ;
- remboursement/annulation traçables.

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
