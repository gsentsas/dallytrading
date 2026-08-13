# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Sourcing",
    "summary": "Sourcing requests, candidate suppliers, offers and customer proposals.",
    "description": """
DallyTrading Sourcing
=====================

A business subsystem, not a form. It carries a sourcing case from the client's request
through supplier research and offer comparison to a customer proposal, a purchase
order and a sale.

Scope
-----

Sourcing answers *"find me this product, this supplier or this manufacturer"*. Direct
participation in buying and reselling belongs to ``dally_trade``. Keeping that line
means neither module becomes a vague catch-all.

Nothing here is specific to a product category: the same models serve agricultural
commodities, equipment, consumer goods and professional supplies.

The confidentiality boundary
----------------------------

``dally.sourcing.offer`` holds what a supplier quoted — unit price, shipping,
insurance, customs estimate, scores, notes. ``dally.sourcing.proposal`` holds what
DallyTrading offers the customer. They are **separate models**, not one model with a
filter:

* the offer model has no public endpoint and appears in no DTO;
* ORM access to it excludes commercial and read-only users entirely;
* the single bridge, ``_dally_draft_from_offer``, copies a derived selling price and
  nothing else — no supplier identity, no cost line, no score.

"Show the customer the offer" therefore cannot happen by accident.

What is reused rather than rebuilt
----------------------------------

* references — ``dally.reference.mixin`` from ``dally_core``
* contact deduplication — ``res.partner._dally_find_existing`` from ``dally_crm``
* API authentication, scopes, idempotency and logging — ``dally_api``
* incoterms — native ``account.incoterms``
* units — native ``uom.uom``
* purchase and sale — native ``purchase.order`` and ``sale.order``
""",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "category": "Services/DallyTrading",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    # purchase and sale are required by the conversion actions; account supplies
    # account.incoterms; uom supplies the units. Declared explicitly rather than
    # relied on transitively, so a change upstream breaks loudly.
    "depends": [
        "dally_core",
        "dally_crm",
        "purchase",
        "sale",
        "account",
        "uom",
    ],
    "data": [
        "security/dally_sourcing_security.xml",
        "security/ir.model.access.csv",
        "security/dally_sourcing_rules.xml",
        "data/ir_sequence_data.xml",
        "views/dally_sourcing_request_views.xml",
        "views/dally_sourcing_supplier_views.xml",
        "views/dally_sourcing_offer_views.xml",
        "views/dally_sourcing_proposal_views.xml",
        "views/order_links_views.xml",
        "views/dally_sourcing_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
