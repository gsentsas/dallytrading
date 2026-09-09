# -*- coding: utf-8 -*-
{
    "name": "DallyTrading Web Branding",
    "summary": "Identite DallyTrading pour les ecrans publics d'authentification",
    "version": "19.0.1.0.0",
    "category": "Website/Website",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "license": "LGPL-3",
    "depends": [
        "website",
        "auth_signup",
        "auth_passkey",
    ],
    "data": [
        "views/login_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "dally_web_branding/static/src/scss/login.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
