# -*- coding: utf-8 -*-
"""Le départ auquel une dépense se rattache.

## Pourquoi ici

`dally.cash.expense` vit dans le module de facturation, `dally.freight.consolidation`
dans celui-ci. Ce module dépend du premier et étend déjà `dally.shipment` de la
même façon : il est le seul endroit où les deux modèles existent ensemble sans
créer de dépendance circulaire. Placer ce lien dans l'application terrain
ferait dépendre une relation métier d'une interface.

## Pourquoi le champ reste facultatif

Les dépenses venues du tableur et des imports anciens n'ont pas de
consolidation, et n'en auront jamais. Rendre le champ obligatoire au niveau du
modèle casserait ces flux du jour au lendemain, pour une exigence qui
n'appartient qu'à une seule interface.

Dally Ops, lui, l'exige — mais c'est le service Ops qui le fait respecter, là
où la règle a du sens.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DallyCashExpense(models.Model):
    _inherit = "dally.cash.expense"

    consolidation_id = fields.Many2one(
        "dally.freight.consolidation",
        string="Départ",
        index=True,
        # `restrict` : une consolidation qui porte des dépenses ne disparaît
        # pas en silence.
        ondelete="restrict",
        tracking=True,
    )

    @api.constrains("consolidation_id", "company_id")
    def _check_consolidation_company(self):
        """Une dépense et son départ appartiennent à la même société.

        `check_company` ferait le travail sur un champ ordinaire, mais
        `company_id` est ici renseigné par le moteur de synchronisation après
        coup ; une contrainte explicite dit la règle sans dépendre de l'ordre
        d'affectation.
        """
        for depense in self:
            consolidation = depense.consolidation_id
            if consolidation and consolidation.company_id != depense.company_id:
                raise ValidationError(
                    _("Une dépense ne peut être rattachée qu'à un départ de sa société."))
