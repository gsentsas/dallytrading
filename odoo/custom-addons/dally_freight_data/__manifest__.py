# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Référentiels Freight",
    "summary": "Peuple les référentiels de transport : subdivisions, ports, "
               "aéroports, compagnies, itinéraires.",
    "description": """
Les données de base du fret, et rien d'autre.

## Pourquoi un module séparé

Ce module ne définit **aucun modèle**. Il remplit ceux qui existent déjà —
`res.country.state`, `freight.port`, `freight.airline`,
`freight.frequent.route`, `res.partner` — parce que l'audit des référentiels a
montré que le schéma était complet et les tables vides. Le travail manquant
était d'alimenter, pas de concevoir.

Les données vivent à part du code pour une raison pratique : elles changent
pour des motifs différents. Un port ouvre, une compagnie fusionne, une région
est redécoupée — rien de tout cela ne devrait obliger à toucher un module qui
porte de la logique métier.

## Pourquoi pas dans `tk_freight`

Le fournisseur possède `freight.port`, `freight.airline` et
`freight.frequent.route`. Y déposer nos données les ferait disparaître à la
première mise à jour du module acheté, et rendrait toute reprise du fournisseur
conflictuelle. On remplit ses tables ; on ne modifie pas son code.

Dépendre de `dally_freight_bridge` plutôt que de `tk_freight` directement n'est
pas cosmétique : le pont porte le garde-fou qui vérifie que le portail n'a aucun
droit sur les modèles du fournisseur. Installer des données tk sans ce garde-fou
serait possible ; le rendre impossible coûtait une ligne.

## Idempotence

Tous les enregistrements sont en `noupdate="1"`. Ils sont créés à
l'installation, puis plus jamais réécrits : une correction faite à la main sur
un port survit à toutes les mises à jour ultérieures. Rejouer le seeder ne
duplique rien — l'identifiant XML sert de clé.
""",
    "version": "19.0.1.0.0",
    "category": "Inventory/Delivery",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "license": "LGPL-3",
    "depends": ["dally_freight_bridge"],
    "data": [
        "data/res_country_state.xml",
        "data/res_partner_category.xml",
        "data/res_partner_shipping_line.xml",
        "data/freight_port_ocean.xml",
        "data/freight_port_air.xml",
        "data/freight_airline.xml",
        "data/freight_frequent_route.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
