# -*- coding: utf-8 -*-
"""Le justificatif d'une dépense de caisse.

## Pourquoi une relation explicite

Une dépense peut porter des pièces jointes de discussion — un échange, une
capture, une relance. Le justificatif, lui, est autre chose : c'est la preuve
qu'on ressortira si quelqu'un demande où sont passés vingt-cinq mille francs.
Le confondre avec le reste obligerait, le jour venu, à deviner laquelle des
pièces fait foi.

La relation vit dans le module qui possède la dépense, et n'a besoin que de
`ir.attachment` — donc aucune dépendance nouvelle.
"""

from odoo import api, fields, models


class DallyCashExpense(models.Model):
    _inherit = "dally.cash.expense"

    receipt_attachment_id = fields.Many2one(
        "ir.attachment",
        string="Justificatif",
        copy=False,
        # `restrict` : on ne supprime pas une preuve par effet de bord. La
        # retirer doit être un geste délibéré, pas la conséquence du ménage
        # d'une autre table.
        ondelete="restrict",
    )
    has_receipt = fields.Boolean(
        string="Justificatif fourni",
        compute="_compute_has_receipt",
        store=True,
    )

    @api.depends("receipt_attachment_id")
    def _compute_has_receipt(self):
        for depense in self:
            depense.has_receipt = bool(depense.receipt_attachment_id)
