# E-commerce Pro — architecture et roadmap

Ce document décrit le cycle produit ouvert après la mise en production de Freight Pro.
La branche de travail est `feature/ecommerce-pro` et part de `main` après le déploiement validé du 20 août 2026.

## 1. Socle déjà en production

La boutique n'est pas un second ERP. Odoo reste la source de vérité pour les produits, les prix, les commandes et les clients ; Next.js est la vitrine et le BFF public.

Le module `dally_shop` fournit déjà :

- publication produit fermée par défaut sur `product.template` ;
- taxonomie publique `dally.shop.category` ;
- prix issus exclusivement d'une pricelist Odoo ;
- politique de stock et projection catalogue ;
- galerie produit ;
- panier scellé côté Next ;
- checkout invité ou connecté ;
- idempotence par identifiant de panier ;
- création d'une seule `sale.order`, volontairement en `draft` ;
- espace client des commandes ;
- projections strictes sans coûts, marges ni données internes ;
- neutralisation du portail natif Sale pour éviter une seconde expérience boutique.

Le checkout ne confirme donc pas encore la commande et ne crée ni facture, ni paiement, ni picking. Ce comportement est une frontière volontaire, pas un manque accidentel.

## 2. Principes du cycle E-commerce Pro

1. **Pas de `website_sale`.** Next reste l'unique vitrine publique.
2. **Pas de modèle de commande parallèle.** `sale.order` reste l'autorité.
3. **Aucun prix fourni par le navigateur.** Odoo calcule le tarif, les taxes et les totaux.
4. **Idempotence avant effets métier.** Paiement, confirmation, facture et livraison devront tous être rejouables sans doublon.
5. **Séparer réception et engagement commercial.** Une commande publique reçue n'est pas confirmée tant que les règles de paiement et de disponibilité ne l'autorisent pas.
6. **Droits minimaux.** Un opérateur boutique ne reçoit pas les droits généraux Vente, Fret ou Finance pour lire les commandes de la boutique.
7. **Le portail ne voit que des projections explicites.** Aucun champ ajouté ultérieurement à `sale.order` ne doit traverser automatiquement.

## 3. Lots

### Lot A — Backoffice commandes

Objectif : rendre les commandes boutique exploitables dans Odoo sans élargir les droits au reste des ventes.

- groupe « Boutique — opérations » ;
- lecture de `sale.order` limitée à `dally_shop_order = True` ;
- lecture de `sale.order.line` limitée aux lignes de ces commandes ;
- menu Boutique → Commandes ;
- liste, recherche et fiche de consultation dédiées ;
- aucune confirmation automatique, aucun mouvement de stock, aucune facture.

### Lot B — Workflow commercial

- état opérationnel client-safe, séparé des détails internes ;
- validation explicite d'une commande reçue ;
- refus/annulation avec motif métier ;
- journal des transitions ;
- notifications transactionnelles asynchrones ;
- projection portail cohérente avec le workflow.

### Lot C — Livraison

- modes de remise configurables ;
- adresse de livraison distincte si nécessaire ;
- calcul/validation des frais côté Odoo ;
- préparation et picking après confirmation ;
- suivi de la remise et de la livraison.

### Lot D — Paiement

Le fournisseur de paiement sera intégré derrière une abstraction DallyTrading afin que le contrat métier ne dépende pas d'un prestataire particulier.

- intention de paiement idempotente ;
- référence publique opaque ;
- webhook signé ;
- ledger d'événements de paiement ;
- confirmation de commande uniquement après règle métier satisfaite ;
- aucune confiance dans un statut remonté par le navigateur ;
- remboursement/annulation traçables.

### Lot E — Facturation

- politique explicite de création de facture ;
- facture après événement métier défini, jamais au simple clic du checkout ;
- rapprochement paiement/facture ;
- documents client accessibles par le portail selon publication.

### Lot F — Pilotage

- dashboard boutique ;
- commandes reçues, validées, à préparer, remises, annulées ;
- chiffre d'affaires confirmé et encaissé distingués ;
- alertes sur commandes bloquées ;
- métriques sans `sudo()` qui contournent les droits du lecteur.

## 4. Hors périmètre immédiat

- marketplace multi-vendeurs ;
- promotions complexes ;
- abonnement récurrent ;
- fidélité ;
- multi-entrepôt avancé ;
- synchronisation avec une boutique tierce.

Ces sujets ne doivent pas compliquer le chemin critique : catalogue → commande reçue → validation → paiement → préparation → livraison.
