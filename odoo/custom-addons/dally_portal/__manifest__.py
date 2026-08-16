# -*- coding: utf-8 -*-
{
    "name": "DallyTrading Client Portal",
    "summary": "Espace client cloisonné et édition sécurisée du profil contact",
    "description": """
DallyTrading Client Portal
==========================

Donne à un client authentifié l'accès à **ses** dossiers, et à rien d'autre.

Ce que ce module porte
----------------------

- Les ACL portail : le groupe ``base.group_portal`` n'avait jusqu'ici **aucun**
  accès, et ce module n'ouvre que ce qui est nécessaire en lecture. L'ACL native
  de ``res.partner`` reste elle aussi read-only.
- Les record rules, fondées sur ``commercial_partner_id`` : les contacts d'une
  même société voient les dossiers de cette société.
- Les projections ``_dally_portal_payload()``.
- La route de profil et sa capacité ORM sans ``sudo``, limitée au contact exact,
  avec refus de tout ``res.partner.write`` portail générique.
- ``dally.portal.document`` : la seule voie par laquelle un fichier peut atteindre
  un client.

Pourquoi un module séparé
-------------------------

Le périmètre de ce qu'un client peut voir tient dans un seul répertoire, se relit
d'un bloc et se désinstalle. Dispersé dans sept modules métier, il faudrait sept
lectures pour répondre à « qu'est-ce qu'un client voit ? ».

Identité
--------

Aucun annuaire d'utilisateurs parallèle. Un client est un ``res.users`` portail
Odoo (``share = True``, ``base.group_portal``), et les requêtes s'exécutent **sous
son identité** : ce sont les record rules de l'ORM qui décident, pas un filtre
applicatif. Un ``domain`` oublié dans un contrôleur ne peut donc pas exposer le
dossier d'un autre client.

Ce que le module n'expose jamais
--------------------------------

``dally.sourcing.offer``, ``dally.sourcing.supplier``, ``dally.trade.cost`` et
``dally.trade.commission`` n'ont aucune ACL portail. Sur ces trois derniers,
``partner_id`` désigne un fournisseur ou un prestataire — jamais le client. Les
traiter comme les autres aurait donné à un client-fournisseur l'accès aux coûts
et aux commissions.
""",
    "version": "19.0.1.1.0",
    "category": "Website/Portal",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "license": "LGPL-3",
    "depends": [
        # Groupes portail, utilisateurs share=True, mixin portal.mixin.
        "portal",
        # Invitation et activation de compte : le MVP n'ouvre pas d'inscription
        # libre, il s'appuie sur le jeton d'invitation d'Odoo.
        "auth_signup",
        # Les cinq modèles métier exposés au client.
        "dally_crm",
        "dally_sourcing",
        "dally_trade",
        "dally_freight",
        "dally_tracking",
    ],
    "data": [
        "security/dally_portal_security.xml",
        "security/ir.model.access.csv",
        "security/dally_portal_rules.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
