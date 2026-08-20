# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Tableau de bord Freight",
    "summary": "Des indicateurs cliquables qui ouvrent exactement ce qu'ils comptent.",
    "description": """
Un tableau de bord où chaque chiffre est une porte.

## Pourquoi un tableau de bord de plus

`tk_freight` en fournit un. Il ne peut pas servir ici, pour trois raisons
mesurées dans son code :

* il compte sur `freight.shipment`, le modèle du fournisseur, alors que
  l'exploitation vit sur `dally.shipment` — ses quatorze états, de « en
  transit » à « en livraison », n'existent pas chez lui ;
* **tous ses compteurs sont en `sudo()`** : ils comptent les dossiers de tout
  le monde, quel que soit le lecteur. Un chiffre qu'on ne peut pas ouvrir est
  au mieux inutile, au pire une fuite ;
* c'est du code fournisseur, et le corriger sur place serait perdu à la
  première mise à jour.

Celui-ci compte ce que l'utilisateur a le droit de voir, et rien d'autre.

## Le compteur et l'action ne peuvent pas diverger

C'est la propriété centrale, et elle est structurelle plutôt que surveillée :
chaque carte déclare **un** domaine, dans `CARTES`. Le même appel produit le
chiffre affiché et le domaine de la liste ouverte. Il n'existe aucun endroit où
écrire un critère deux fois, donc aucun endroit où les désynchroniser.

## Pas de JavaScript

Une vue kanban, un bouton `type="object"` par carte, une `ir.actions.act_window`
en retour. Rien à compiler, rien à hydrater, et le clic fonctionne partout où
Odoo fonctionne.
""",
    "version": "19.0.1.0.0",
    "category": "Inventory/Delivery",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "license": "LGPL-3",
    # Le pont apporte `tk_freight` (pour les réservations), `dally_freight`
    # (les expéditions) et `dally_crm` (les demandes).
    "depends": ["dally_freight_bridge"],
    "data": [
        "security/ir.model.access.csv",
        "views/dally_freight_dashboard_views.xml",
        "data/dally_freight_dashboard_data.xml",
        "data/tk_freight_dashboard_hidden.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
