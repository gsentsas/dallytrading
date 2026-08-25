# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Consolidations fret",
    "summary": "Départs physiques, MAWB, manifestes et contrôles de paiement.",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "author": "DallyTrading",
    "depends": [
        "dally_freight_billing",
        "dally_freight_bridge",
        "dally_freight_notifications",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/consolidation_rules.xml",
        "data/ir_sequence_data.xml",
        "reports/consolidation_reports.xml",
        "reports/consolidation_manifest.xml",
        "views/consolidation_views.xml",
        "views/shipment_package_views.xml",
        "wizard/payment_override_views.xml",
        "wizard/add_to_consolidation_views.xml",
        "wizard/historical_backfill_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
