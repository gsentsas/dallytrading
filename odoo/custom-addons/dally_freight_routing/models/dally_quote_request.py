# -*- coding: utf-8 -*-
"""L'acheminement d'une demande de devis.

Le mode ne s'y lit jamais en clair. Il se déduit du service commercial, et pour
deux services — groupage et véhicule — de la marchandise elle-même, parce que
« transport de véhicule » dit ce que le client achète et non par quoi la
voiture voyage. Ces règles existent déjà dans `dally_freight_bridge`, qui s'en
sert pour provisionner le fournisseur ; les reprendre plutôt que les réécrire
garantit que l'écran et le provisionnement ne se contrediront pas.
"""

from odoo import models


class DallyQuoteRequest(models.Model):
    # `_name` explicite : sans lui, Odoo 19 crée un modèle fantôme au lieu
    # d'appliquer le mixin au modèle existant.
    _name = "dally.quote.request"
    _inherit = ["dally.quote.request", "dally.freight.routing.mixin"]

    def _dally_champs_declencheurs(self):
        return {"service_type_id", "groupage_transport_mode", "vehicle_cargo_id"}

    def _dally_transport(self):
        self.ensure_one()
        from odoo.addons.dally_freight_bridge.models.freight_mapping import (
            GROUPAGE_MODE_TO_TRANSPORT,
            SERVICE_CODE_TO_TRANSPORT,
            VEHICLE_MODE_TO_TRANSPORT,
        )
        code = self.service_type_id.code or ""
        direct = SERVICE_CODE_TO_TRANSPORT.get(code)
        if direct:
            return direct
        if code == "freight_groupage":
            couple = GROUPAGE_MODE_TO_TRANSPORT.get(self.groupage_transport_mode or "")
            return couple[0] if couple else False
        if code == "freight_vehicle":
            # La logique véhicule est conservée telle quelle : c'est la
            # marchandise qui porte le mode, et un roulier reste du maritime.
            cargo = self.vehicle_cargo_id
            return VEHICLE_MODE_TO_TRANSPORT.get(cargo.transport_mode or "") if cargo else False
        return False
