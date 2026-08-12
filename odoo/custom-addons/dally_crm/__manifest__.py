# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — CRM",
    "summary": "Website leads in Odoo CRM: service, attribution, deduplication.",
    "description": """
DallyTrading CRM
================

Extends the native ``crm.lead`` rather than introducing a parallel model, so
that pipelines, activities, reporting and the chatter keep working as Odoo
users expect (§70).

Adds:

* a customer-facing reference (DT-YYYY-NNNNNN) shared with the website
* the requested service, taken from the ``dally_core`` catalogue
* marketing attribution: source URL and raw UTM values as received
* an idempotency key with a database-level uniqueness guarantee, so a
  double-click or a network retry cannot create two leads (§41)
* contact deduplication, searching email, phone, WhatsApp then company (§28)
""",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "category": "Services/DallyTrading",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    # utm arrives through crm, but it is declared explicitly because this module
    # references utm.source and utm.medium directly. Relying on a transitive
    # dependency would break silently if crm ever drops it.
    # sale is required because a qualified request raises a native sale.order.
    # The dependency is deliberate: the alternative would be a parallel quotation
    # model, which is exactly what §70 forbids.
    "depends": [
        "dally_core",
        "crm",
        "utm",
        "sale",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/dally_crm_rules.xml",
        "data/utm_data.xml",
        "views/crm_lead_views.xml",
        "views/dally_quote_request_views.xml",
        "views/sale_order_views.xml",
        "views/dally_crm_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
