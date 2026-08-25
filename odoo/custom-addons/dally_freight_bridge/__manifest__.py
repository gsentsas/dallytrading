{
    "name": "DallyTrading — pont Freight",
    "summary": "Confine tk_freight au back-office et expose le fret au portail par projection.",
    "description": """
Pont entre le moteur opérationnel tiers `tk_freight` et le portail DallyTrading.

Ce module ne modifie jamais `tk_freight` : il le *confine*. Le fournisseur reste
mis à jour normalement, sans fork.

Ce qu'il fait, et pourquoi — le détail des mesures est dans
`docs/evaluations/TK-FREIGHT-EVALUATION.md`, partie II :

1. Il retire au groupe portail les 26 droits d'accès que `tk_freight` lui
   accorde. Mesuré : un client lisait et modifiait les colis d'un autre, et
   exfiltrait le contenu binaire de ses documents.
2. Il neutralise les 17 routes HTTP du fournisseur, y compris le suivi public
   (énumérable) et les routes déclarées `csrf=False` (création prouvée sans
   jeton).
3. Il refuse de démarrer si l'un des deux points ci-dessus a été défait — par
   exemple par une mise à jour du fournisseur rechargeant ses propres droits.

Le portail client passe exclusivement par les projections de `dally_portal`.
""",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "category": "Inventory/Delivery",
    "version": "19.0.2.0.0",
    "license": "LGPL-3",
    # tk_freight est un module tiers sous licence OPL-1. Il n'est pas versionné
    # dans ce dépôt : ce module ne s'installe que là où la copie licenciée est
    # présente dans l'addons_path.
    "depends": ["base", "mail", "tk_freight", "dally_crm", "dally_freight", "dally_tracking", "dally_portal"],
    "data": [
        "security/tk_freight_portal_lockdown.xml",
        "data/freight_shipment_stages.xml",
        "data/tk_freight_fr_view_overlay.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
