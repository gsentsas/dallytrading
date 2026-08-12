# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Freight",
    "summary": "Freight files: sea, air, road, vehicles, groupage, cargo and routes.",
    "description": """
DallyTrading Freight
====================

The business source of truth for DallyTrading shipments. One model, ``dally.shipment``,
covers every mode: sea, air, road, vehicle transport and groupage.

What it deliberately does **not** do
------------------------------------

It does not duplicate anything native (§70). The customer is a ``res.partner``,
the quotation a ``sale.order``, the invoice an ``account.move``. Pricing lives on
the sales order, not here. This module adds only what freight needs and Odoo does
not model:

* transport mode and direction
* route: origin and destination, port or airport
* cargo: packages, weight, volume in CBM, dimensions, container
* **chargeable weight** — the greater of gross and volumetric weight, which is
  what freight is actually billed on
* operational milestones: departure, ETA, actual arrival, delivery

Confidentiality
---------------

``supplier_cost``, ``margin`` and ``internal_notes`` carry ``groups=``, so the ORM
strips them for users outside the relevant group. Combined with the field
allowlist in the tracking API, that gives two independent layers: one that filters
the response, one that never loads the data at all (§44).
""",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "category": "Services/DallyTrading",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    # sale brings account with it, which is what account.move is resolved from.
    # Declared explicitly all the same: relying on a transitive dependency breaks
    # silently the day it changes.
    "depends": [
        "dally_core",
        "sale",
        "account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/dally_freight_rules.xml",
        "data/ir_sequence_data.xml",
        "views/dally_shipment_views.xml",
        "views/dally_freight_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
