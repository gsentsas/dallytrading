# -*- coding: utf-8 -*-
"""Le départ auquel une dépense se rattache.

Le modèle de caisse appartient à dally_freight_billing alors que les
consolidations vivent ici. Cette extension est donc le bon endroit pour tenir
le lien sans créer de dépendance circulaire.

Les dépenses Ops portent toujours leur consolidation explicitement. Les lignes
historiques/tableur, elles, n'ont longtemps porté que la référence métier dans
reference, description ou comment. Lors d'un upsert on peut les rattacher sans
deviner : on ne retient une consolidation que si UNE SEULE référence exacte de
la société apparaît dans ces champs. Zéro ou plusieurs correspondances
signifient qu'aucune affectation automatique n'est faite.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DallyCashExpense(models.Model):
    _inherit = "dally.cash.expense"

    consolidation_id = fields.Many2one(
        "dally.freight.consolidation",
        string="Départ",
        index=True,
        ondelete="restrict",
        tracking=True,
    )

    @api.constrains("consolidation_id", "company_id")
    def _check_consolidation_company(self):
        for depense in self:
            consolidation = depense.consolidation_id
            if consolidation and consolidation.company_id != depense.company_id:
                raise ValidationError(
                    _("Une dépense ne peut être rattachée qu'à un départ de sa société."))

    @api.model
    def upsert_from_sync(self, values, allocations):
        """Enrichit un import caisse avec son départ quand il est certain.

        Le connecteur Google Sheets historique n'envoie pas consolidation_id.
        On exploite donc uniquement les références déjà présentes dans le
        payload. Une affectation explicite fournie par un appelant garde
        toujours la priorité.
        """
        enriched = dict(values or {})
        if not enriched.get("consolidation_id"):
            consolidation = self._resolve_consolidation_from_sync_values(enriched)
            if consolidation:
                enriched["consolidation_id"] = consolidation.id
        return super().upsert_from_sync(enriched, allocations)

    @api.model
    def _resolve_consolidation_from_sync_values(self, values):
        """Retourne l'unique consolidation nommée dans la dépense, sinon vide."""
        texte = " ".join(
            str(values.get(champ) or "")
            for champ in ("reference", "description", "comment")
        ).casefold()
        if not texte.strip():
            return self.env["dally.freight.consolidation"].browse()

        consolidations = self.env["dally.freight.consolidation"].sudo().search([
            ("company_id", "=", self.env.company.id),
        ])
        correspondances = consolidations.filtered(
            lambda depart: depart.name and depart.name.casefold() in texte)
        return correspondances if len(correspondances) == 1 else consolidations.browse()
