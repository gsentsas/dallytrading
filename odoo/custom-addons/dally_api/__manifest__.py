# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — API",
    "summary": "Versioned REST endpoints for dallytrading.com.",
    "description": """
DallyTrading API
================

Narrow, versioned REST surface consumed by the Next.js backend. One endpoint per
business operation — there is deliberately no generic way to reach an arbitrary
model or method from outside (§40).

Security model
--------------

* Authentication by API key in the ``X-API-Key`` header; only a SHA-256 hash is
  stored.
* Requests act as a dedicated integration user, so ACLs and record rules apply.
  ``sudo()`` is used only for authentication and logging.
* Keys carry explicit scopes and are pinned to source IPs — 127.0.0.1 by
  default, since the Next.js backend runs on the same host.
* Every create endpoint is idempotent, guaranteed by a unique constraint rather
  than by application logic (§41).
* Responses never contain database ids: a sequential id must not become an
  authorisation handle (§42).

Endpoints
---------

* ``GET  /api/v1/services`` — public service catalogue, the source of truth for
  which fields the website's quote form must ask for
* ``POST /api/v1/quotes`` — quote requests; creates a qualifiable
  ``dally.quote.request`` and a CRM opportunity, and deliberately no
  ``sale.order``, ``res.partner`` or ``dally.shipment``
* ``POST /api/v1/sourcing/requests`` — sourcing requests; creates a qualifiable
  ``dally.sourcing.request`` and deliberately nothing else. Supplier offers, costs,
  scores and margins live on models the sourcing API user cannot reach at all
* ``POST /api/v1/leads`` — simple contact requests
* ``GET  /api/v1/tracking/<reference>`` — public shipment tracking, requiring a
  reference *and* an unpredictable token
* ``GET  /api/v1/health`` — authenticated health probe for monitoring

Planned in later phases: ``/api/v1/trading``, ``/api/v1/shipments``,
``/api/v1/customers``, and a read endpoint for sourcing once a client portal exists —
a public read surface with no consumer is attack surface for nothing.
""",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "category": "Services/DallyTrading",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "dally_core",
        "dally_crm",
        # Le point d'entrée public crée le véhicule décrit par une demande de
        # transport de véhicule, dans la même transaction que la demande.
        "dally_freight",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/dally_api_user.xml",
        "views/dally_api_key_views.xml",
        "views/dally_api_request_views.xml",
        "views/dally_api_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
