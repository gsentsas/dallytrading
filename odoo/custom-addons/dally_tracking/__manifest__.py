# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Tracking",
    "summary": "Tracking events, public timeline and the internal/public boundary.",
    "description": """
DallyTrading Tracking
=====================

Adds the customer-facing narrative to a freight file, and owns the boundary
between what DallyTrading knows and what a customer is shown.

Confidentiality — three independent layers
------------------------------------------

The requirement is that no supplier cost, margin or internal note can ever reach
the public tracking API (§44). One mechanism would be one bug away from failing,
so there are three:

1. **ORM field groups.** ``supplier_cost``, ``margin`` and ``internal_notes``
   carry ``groups=``. The tracking API acts as a user in no DallyTrading group, so
   those columns are never loaded — not filtered afterwards, never read.
2. **A record rule.** For the tracking group, ``dally.shipment.event`` is
   restricted to ``visible_to_customer = True``. A search with an empty domain
   still returns only publishable events.
3. **An explicit payload allowlist.** ``_dally_public_payload`` names every key it
   emits. A field added to the shipment tomorrow cannot appear by accident, and
   the tests assert the payload's keys against the declared set.

``sudo()`` is deliberately not used anywhere in the tracking path: it would
bypass layers 1 and 2 and leave only the third.

``visible_to_customer`` defaults to **False**, so a forgotten checkbox fails
closed instead of publishing an internal note.
""",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "category": "Services/DallyTrading",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "dally_freight",
        "dally_api",
    ],
    "data": [
        "security/dally_tracking_security.xml",
        "security/ir.model.access.csv",
        "views/dally_shipment_event_views.xml",
        "views/dally_shipment_views.xml",
        "views/dally_tracking_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
