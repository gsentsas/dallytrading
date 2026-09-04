# A004_POSTED_INVOICE_SUPPLEMENT_DESIGN

## Contexte

Le dossier A004 possède déjà une facture comptabilisée `FAC/2026/00019` de 17,75 EUR.
Le Sheet ajoute ensuite une ligne métier de 5,00 EUR. Le total métier attendu
devient donc 22,75 EUR.

Le Sheet porte aussi deux paiements :

- 11 643 XOF
- 3 280 XOF

## Contrainte comptable

Une facture posted ne doit pas être réécrite pour absorber la ligne de 5,00 EUR.
`FAC/2026/00019` reste la pièce historique autoritaire pour les 17,75 EUR déjà
comptabilisés.

## Le mécanisme exact du blocage, tel que mesuré

Trois faits établis en lecture seule sur la base de production le 03/09/2026 :

1. `dally_shipment.billing_locked` vaut `true` sur le shipment 694.
   `dally_freight_billing/models/commercial_documents.py` le passe à `true` au
   moment où le devis natif et la facture brouillon sont générés.
2. `dally_freight_billing/models/billing_lock.py`, dans
   `DallyShipmentPackage.create()`, lève « Cannot add freight lines while
   billing is locked. Reset the draft billing first. » dès que le dossier est
   verrouillé. C'est le message que le connecteur remonte au Sheet.
3. Le chemin de déverrouillage refuse explicitement une facture comptabilisée :
   « Posted invoice %s cannot be reset by Freight sync. » Or `FAC/2026/00019`
   est `posted`, `not_paid`, résiduel 17,75 EUR, sans aucune ligne de lettrage.

Conséquence : aucune séquence de synchronisation, quelle qu'elle soit, ne peut
ni ajouter la ligne de 5,00 EUR ni lever `billing_locked`. Ce n'est pas une
limite du connecteur à contourner, c'est la garantie comptable du modèle. Toute
correction passe donc nécessairement par une pièce complémentaire.

## Stratégie supportée

La correction doit créer une pièce comptable complémentaire séparée pour la
ligne nouvelle de 5,00 EUR, rattachée au même dossier métier et explicitement
traçable comme supplément. Cette pièce porte sa propre numérotation comptable
et ne modifie pas `FAC/2026/00019`.

Les paiements Sheet de 11 643 XOF et 3 280 XOF doivent être rapprochés selon les
règles comptables existantes contre les pièces ouvertes du dossier. Si le taux
ou l'arrondi laisse un écart, l'écart doit rester explicite par les mécanismes
comptables normaux, sans réécriture de la facture posted initiale.

## Hors périmètre de cette branche

Cette branche ne doit pas implémenter le supplément A004. Elle ne porte que la
note de conception pour cadrer une correction future.
