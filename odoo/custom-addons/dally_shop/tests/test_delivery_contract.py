# -*- coding: utf-8 -*-
"""Bornes du contrat public des méthodes de remise."""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally_shop")
class TestDeliveryMethodContract(TransactionCase):

    def _values(self, **overrides):
        values = {
            "name": "Méthode contrat",
            "code": "contrat-test",
            "kind": "delivery",
            "fee_policy": "quote",
            "fixed_fee": 0.0,
            "currency_id": self.env.company.currency_id.id,
            "client_help": "Aide client",
        }
        values.update(overrides)
        return values

    def test_code_est_normalise_avant_validation(self):
        method = self.env["dally.shop.delivery.method"].create(
            self._values(code="  code-normalise  ")
        )
        self.assertEqual(method.code, "code-normalise")

    def test_bornes_publiques_sont_imposees_cote_odoo(self):
        with self.assertRaises(ValidationError):
            self.env["dally.shop.delivery.method"].create(
                self._values(code="a" * 65)
            )
        with self.assertRaises(ValidationError):
            self.env["dally.shop.delivery.method"].create(
                self._values(name="N" * 129, code="nom-trop-long")
            )
        with self.assertRaises(ValidationError):
            self.env["dally.shop.delivery.method"].create(
                self._values(client_help="A" * 301, code="aide-trop-longue")
            )

    def test_montant_fixe_est_interdit_hors_politique_fixed(self):
        with self.assertRaises(ValidationError):
            self.env["dally.shop.delivery.method"].create(
                self._values(fee_policy="quote", fixed_fee=2500.0)
            )
