# -*- coding: utf-8 -*-
"""L'acheminement d'une expédition.

Ici le mode est explicite : `transport_mode` est saisi et suivi. La traduction
vers le vocabulaire des lieux passe par la table du pont, `MODE_TO_TRANSPORT`,
qui est l'inverse exact de celle qu'il utilise pour lire le fournisseur.

`vehicle`, `groupage` et `other` n'ont volontairement pas d'équivalent. Une
expédition provisionnée depuis un devis de groupage arrive déjà en `sea` ou en
`air` — le pont l'a traduite. Les trois valeurs restantes décrivent un service,
pas un moyen de transport, et leur en attribuer un d'office serait exactement
le repli silencieux qu'on veut éviter.
"""

from odoo import models

from odoo.addons.dally_freight_bridge.models.freight_mapping import TRANSPORT_TO_MODE

#: `sea` → `ocean`, `air` → `air`, `road` → `land`. Dérivée, pas recopiée.
MODE_TO_TRANSPORT = {mode: transport for transport, mode in TRANSPORT_TO_MODE.items()}


class DallyShipment(models.Model):
    _name = "dally.shipment"
    _inherit = ["dally.shipment", "dally.freight.routing.mixin"]

    def _dally_champs_declencheurs(self):
        return {"transport_mode"}

    def _dally_transport(self):
        self.ensure_one()
        return MODE_TO_TRANSPORT.get(self.transport_mode or "", False)
