# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Freight Billing Sync",
    "summary": "Tarification, facturation et synchronisation du cahier fret.",
    "version": "19.0.1.3.0",
    "license": "LGPL-3",
    "depends": [
        "dally_api",
        "dally_freight",
        "dally_crm",
        "sale",
        "account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/freight_tariff_data.xml",
        "data/freight_product_data.xml",
        "views/freight_tariff_views.xml",
        "views/shipment_billing_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
