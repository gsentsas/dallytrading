# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Core",
    "summary": "Shared foundation for DallyTrading: references, service catalogue, roles.",
    "description": """
DallyTrading Core
=================

Foundation module for the DallyTrading business suite. Provides what every
other ``dally_*`` module builds on, and nothing else:

* ``dally.reference.mixin`` — auto-numbered business references (DT-YYYY-NNNNNN)
* ``dally.service.type`` — catalogue of commercial activities, keyed by a
  stable code that the public website and the API refer to
* Security groups and the root menu

This module deliberately contains no partner-specific or brand-specific
concept: partners of any kind are plain ``res.partner`` records.
""",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "category": "Services/DallyTrading",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    # Kept intentionally minimal: mail is required for the chatter used by
    # downstream modules, base_setup for the settings panel.
    "depends": [
        "base",
        "mail",
    ],
    "data": [
        "security/dally_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/dally_service_type_data.xml",
        "views/dally_service_type_views.xml",
        "views/dally_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
