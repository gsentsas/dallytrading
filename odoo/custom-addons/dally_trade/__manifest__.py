# -*- coding: utf-8 -*-
{
    "name": "DallyTrading Trade",
    "summary": "Opérations commerciales : achat-revente, courtage, commission, "
               "distribution, import-export, représentation",
    "description": """
DallyTrading Trade
==================

DallyTrading's own commercial transactions, in six shapes that are genuinely
different rather than one shape with a label:

- **achat-revente** — buys and resells, so both sides are priced;
- **courtage** — introduces a buyer to a seller for a fee, and never buys;
- **commission** — earns a commission on someone else's transaction;
- **distribution** — buys and resells under an ongoing arrangement;
- **import-export** — buys and resells across a border, with logistics;
- **représentation commerciale** — acts for a principal in a territory.

The rules per type are declared once, in ``models/dally_trade_rules.py``, and read
from there by every model. A brokerage therefore cannot be given a purchase order,
and a commission has no purchase price to subtract — enforced structurally rather
than by a branch in each method.

What it deliberately does not do
--------------------------------

- No parallel stock, invoicing or payment engine: those are Odoo's native flows.
- No freight logic: shipments live in ``dally_freight``, tracking in
  ``dally_tracking``. Trade links to a shipment, it does not model one.
- No product model: lines point at ``product.product``.
- No default margin, no default commission rate, no default approval threshold.
  Those are commercial policy, and policy in Python is policy nobody can change.

Confidentiality
---------------

Purchase prices, cost lines, margins, negotiation notes and approval history carry
``groups=``, so the ORM never loads them outside trade management and finance. The
public payload is an explicit allowlist, and the API user is scoped to creating its
own records and nothing else.
""",
    "version": "19.0.1.1.0",
    "category": "Sales",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "license": "LGPL-3",
    "depends": [
        "dally_core",
        "dally_crm",
        "dally_freight",
        # dally_sourcing is a dependency only for the optional link field: a trade
        # deal may originate from a sourcing request. It never requires one.
        "dally_sourcing",
        "purchase",
        "sale",
        "account",
        "uom",
        "crm",
    ],
    "data": [
        "security/dally_trade_security.xml",
        "security/ir.model.access.csv",
        "security/dally_trade_rules.xml",
        "data/ir_sequence_data.xml",
        "data/ir_config_parameter_data.xml",
        "views/dally_trade_opportunity_views.xml",
        "views/dally_trade_line_views.xml",
        "views/dally_trade_cost_views.xml",
        "views/dally_trade_commission_views.xml",
        "views/trade_links_views.xml",
        "views/dally_trade_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
