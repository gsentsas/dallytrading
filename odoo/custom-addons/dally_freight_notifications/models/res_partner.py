# -*- coding: utf-8 -*-
"""Le consentement du partenaire aux messages de suivi."""

from odoo import fields, models


class ResPartner(models.Model):
    _name = "res.partner"
    _inherit = "res.partner"

    dally_freight_notify = fields.Boolean(
        string="Notifications de suivi",
        default=True,
        help="Décoché, ce partenaire ne reçoit plus les messages de suivi "
             "d'expédition. La file en garde trace : la notification est "
             "enregistrée comme ignorée, avec son motif, et non perdue.",
    )
