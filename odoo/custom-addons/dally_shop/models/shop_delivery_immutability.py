# -*- coding: utf-8 -*-
"""Rend immuables les caractéristiques d'une méthode déjà utilisée.

Une commande Lot C conserve un lien vers ``dally.shop.delivery.method``. Sans
verrou, modifier ensuite le code, le type ou les frais de cette méthode
réécrirait implicitement l'histoire : une ancienne livraison pourrait devenir un
retrait, ou afficher un autre libellé, sans mutation de la commande elle-même.

Une méthode déjà référencée devient donc une définition versionnée. On peut encore
la désactiver, la réordonner ou ajuster son aide pour empêcher/guider de nouveaux
checkouts, mais toute modification sémantique exige de créer une nouvelle méthode.
"""

from odoo import _, models
from odoo.exceptions import ValidationError


_IMMUTABLE_ON_USE = {
    "name",
    "code",
    "kind",
    "fee_policy",
    "fixed_fee",
    "currency_id",
}


class DallyShopDeliveryMethodImmutable(models.Model):
    _inherit = "dally.shop.delivery.method"

    def write(self, vals):
        semantic_changes = _IMMUTABLE_ON_USE.intersection(vals)
        if semantic_changes and self:
            used = self.env["sale.order"].sudo().search_count([
                ("dally_shop_delivery_method_id", "in", self.ids),
            ])
            if used:
                raise ValidationError(
                    _(
                        "Une méthode de remise déjà utilisée par une commande ne "
                        "peut plus changer de définition. Désactivez-la et créez "
                        "une nouvelle méthode."
                    )
                )
        return super().write(vals)
