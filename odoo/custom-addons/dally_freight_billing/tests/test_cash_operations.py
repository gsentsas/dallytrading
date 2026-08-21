# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightCashOperations(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eur = cls.env.ref("base.EUR")
        cls.xof = cls.env.ref("base.XOF")
        cls.eur.active = True
        cls.xof.active = True

    def test_expense_upsert_is_business_idempotent(self):
        values = {
            "external_expense_key": "DEP-20260821-0001",
            "expense_date": "2026-08-21",
            "category": "Transport",
            "description": "Course locale",
            "beneficiary": "Transporteur test",
            "currency_id": self.xof.id,
            "total_eur_snapshot": 15.24,
            "total_xof_snapshot": 10000.0,
            "payment_method": "Wave",
            "state": "validated",
            "source": "google_sheets",
        }
        allocations = [
            {"actor_name": "Gilles", "amount": 6000.0},
            {"actor_name": "Alain", "amount": 4000.0},
        ]
        first, created_first = self.env["dally.cash.expense"].upsert_from_sync(values, allocations)
        second, created_second = self.env["dally.cash.expense"].upsert_from_sync(values, allocations)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first, second)
        self.assertEqual(len(first.allocation_ids), 2)
        self.assertAlmostEqual(first.total_amount, 10000.0, places=2)
        self.assertEqual(
            self.env["dally.cash.expense"].search_count([
                ("external_expense_key", "=", "DEP-20260821-0001")
            ]), 1,
        )

    def test_expense_correction_replaces_allocation_snapshot(self):
        values = {
            "external_expense_key": "DEP-20260821-0002",
            "expense_date": "2026-08-21",
            "category": "Carburant",
            "description": "Carburant véhicule",
            "currency_id": self.xof.id,
            "state": "review",
            "source": "google_sheets",
        }
        expense, _ = self.env["dally.cash.expense"].upsert_from_sync(
            values, [{"actor_name": "Dalanda", "amount": 5000.0}]
        )
        expense2, created = self.env["dally.cash.expense"].upsert_from_sync(
            values, [{"actor_name": "Dalanda", "amount": 7500.0}]
        )
        self.assertFalse(created)
        self.assertEqual(expense, expense2)
        self.assertEqual(len(expense2.allocation_ids), 1)
        self.assertAlmostEqual(expense2.total_amount, 7500.0, places=2)

    def test_transfer_upsert_is_business_idempotent(self):
        values = {
            "external_transfer_key": "TRF-20260821-0001",
            "transfer_date": "2026-08-21",
            "from_actor": "Gilles",
            "to_actor": "Dalanda",
            "amount": 50.0,
            "currency_id": self.eur.id,
            "total_eur_snapshot": 50.0,
            "total_xof_snapshot": 32800.0,
            "reason": "Remise caisse",
            "payment_method": "Espèces",
            "state": "validated",
            "source": "google_sheets",
        }
        first, created_first = self.env["dally.cash.transfer"].upsert_from_sync(values)
        second, created_second = self.env["dally.cash.transfer"].upsert_from_sync(values)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first, second)
        self.assertEqual(
            self.env["dally.cash.transfer"].search_count([
                ("external_transfer_key", "=", "TRF-20260821-0001")
            ]), 1,
        )
