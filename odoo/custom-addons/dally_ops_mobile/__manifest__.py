# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Dally Ops (terrain)",
    "summary": "Identité, rôles et services de l'application terrain des logisticiens.",
    "description": """
Ce que le logisticien fait depuis son téléphone, et rien d'autre.

## Ce que ce module n'est pas

Il ne réimplémente aucune règle métier du fret. La numérotation par
consolidation, la tarification, l'idempotence des dossiers et la caisse
existent déjà et fonctionnent en production ; ce module les **appelle**. Ce
qu'il ajoute est ce que ces services ne peuvent pas fournir : **qui** saisit.

## Pourquoi une identité d'acteur explicite

Les paiements savent déjà qui a encaissé — `dally.freight.payment.collection`
porte `collected_by_id` vers `res.users`. Les dépenses et les transferts, eux,
ne portent qu'un texte libre : `actor_name`, `from_actor`, `to_actor`. Mesuré
en production : « Gilles », « Alain ». Il n'existe donc **aucun acteur
canonique**.

Deviner l'acteur en comparant `display_name` serait la pire des solutions : un
utilisateur renommé, un homonyme, un accent, et la caisse d'un collègue se
retrouve créditée. Ce module pose donc une correspondance **explicite**,
configurée une fois par utilisateur, et refuse l'opération quand elle manque.

## Les deux rôles

Le logisticien saisit ; le responsable corrige. Ni l'un ni l'autre n'obtient
les droits techniques du connecteur tableur, ni ceux de la facturation : ces
identités-là servent une clé d'API, pas une personne, et les confondre
donnerait à un téléphone les pouvoirs d'un automate.
""",
    "version": "19.0.1.7.0",
    "category": "Inventory/Delivery",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "license": "LGPL-3",
    "depends": [
        "dally_core",
        "dally_crm",
        "dally_freight",
        "dally_freight_billing",
        "dally_freight_consolidation",
    ],
    "data": [
        "security/dally_ops_groups.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
