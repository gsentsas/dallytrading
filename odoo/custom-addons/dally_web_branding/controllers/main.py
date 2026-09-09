# -*- coding: utf-8 -*-
"""Point d'entree du CRM, sans logique d'authentification parallele."""

from urllib.parse import urlsplit

from odoo import http
from odoo.addons.website.controllers.main import Website
from odoo.http import request


CRM_HOST = "crm.dallytrading.com"


def normalized_host(host):
    """Normalise la casse, le port et le point terminal d'un en-tete Host."""
    try:
        parsed = urlsplit(f"//{host.strip()}")
        # Lire ``port`` valide aussi qu'il est numerique. Userinfo et chemin ne
        # font jamais partie d'un en-tete Host valable.
        parsed.port
    except ValueError:
        return ""
    if parsed.username is not None or parsed.password is not None or parsed.path:
        return ""
    return (parsed.hostname or "").rstrip(".").lower()


class DallyWebBrandingWebsite(Website):
    """Redirige uniquement la racine du hostname CRM vers le login natif."""

    @http.route(methods=["GET"])
    def index(self, **kw):
        if normalized_host(request.httprequest.host) == CRM_HOST:
            return request.redirect("/web/login", 303)
        return super().index(**kw)
