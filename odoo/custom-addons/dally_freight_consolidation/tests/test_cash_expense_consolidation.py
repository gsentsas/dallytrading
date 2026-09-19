# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import ConsolidationCommon


@tagged("post_install", "-at_install", "dally")
class TestCashExpenseConsolidation(ConsolidationCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.xof = cls.env.ref("base.XOF")
        cls.depart_1 = cls._consolidation("AIR-DSS-CDG-2026-001")
        cls.depart_2 = cls._consolidation("AIR-DSS-CDG-2026-002")

    def _upsert(self, key, **extra):
        vals = {
            "external_expense_key": key,
            "expense_date": "2026-09-05",
            "category": "Fret",
            "description": "Paiement transport",
            "currency_id": self.xof.id,
            "source": "google_sheets",
            **extra,
        }
        return (
            self.env["dally.cash.expense"].sudo().with_company(self.env.company)
            .upsert_from_sync(
                vals, [{"actor_name": "Gilles", "amount": 1000.0}]
            )
        )[0]

    def test_reference_tableur_rattache_automatiquement_le_depart(self):
        depense = self._upsert(
            "sheet-exp-1",
            reference="Wave - AIR-DSS-CDG-2026-001 - 550560 FCFA",
        )
        self.assertEqual(depense.consolidation_id, self.depart_1)

    def test_description_ou_commentaire_peut_porter_la_reference(self):
        depense = self._upsert(
            "sheet-exp-2",
            comment="Justificatif pour AIR-DSS-CDG-2026-002",
        )
        self.assertEqual(depense.consolidation_id, self.depart_2)

    def test_sans_reference_certaine_la_depense_reste_non_affectee(self):
        depense = self._upsert("sheet-exp-3", reference="PHOTO-2026-09-05")
        self.assertFalse(depense.consolidation_id)

    def test_deux_references_differentes_ne_sont_jamais_devinees(self):
        depense = self._upsert(
            "sheet-exp-4",
            reference="AIR-DSS-CDG-2026-001 / AIR-DSS-CDG-2026-002",
        )
        self.assertFalse(depense.consolidation_id)

    def test_affectation_explicite_garde_la_priorite(self):
        depense = self._upsert(
            "sheet-exp-5",
            reference="AIR-DSS-CDG-2026-001",
            consolidation_id=self.depart_2.id,
        )
        self.assertEqual(depense.consolidation_id, self.depart_2)
