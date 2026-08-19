# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Acheminement structuré",
    "summary": "Relie les objets fret aux référentiels : régions, ports, "
               "compagnies, incoterms, itinéraires.",
    "description": """
Ce que le commercial saisissait en texte libre devient une relation.

## Le problème

`dally.quote.request` et `dally.shipment` décrivaient un acheminement avec un
pays, deux chaînes de caractères pour les villes et une troisième pour le
transporteur. Rien n'empêchait « Dakar », « dakar », « DKR » et « Port de
Dakar » de coexister dans la même colonne, et aucun regroupement, aucun tarif,
aucune statistique ne pouvait s'appuyer là-dessus.

Les référentiels existent depuis `dally_freight_data` : ports, aéroports,
compagnies aériennes et maritimes, itinéraires fréquents, subdivisions. Ce
module les raccorde.

## Ce qu'il ne fait pas

Il **ne supprime aucun champ**. `origin_city`, `destination_city` et
`carrier_name` restent, alimentés par les relations quand elles sont
renseignées. Le portail public, l'API et les projections continuent de les
lire sans rien savoir des nouveaux champs. La relation devient la source
principale ; la chaîne reste un miroir.

## Pourquoi un module à part

Les champs visent `freight.port`, `freight.airline` et `freight.vessel`, qui
appartiennent au fournisseur. `dally_freight` ne dépend pas de `tk_freight` et
ne doit pas commencer : c'est ce découplage qui permet de faire tourner le
moteur fret maison sans le module acheté. La dépendance vit donc ici, dans un
module qu'on peut retirer sans toucher au reste.
""",
    "version": "19.0.1.0.0",
    "category": "Inventory/Delivery",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "license": "LGPL-3",
    "depends": ["dally_freight_data"],
    "data": [
        "views/dally_quote_request_views.xml",
        "views/dally_shipment_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
