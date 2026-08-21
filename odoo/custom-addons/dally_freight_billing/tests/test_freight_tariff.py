# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightTariff(TransactionCase):
    """Lock the tariff semantics imported from FActuration COntainer 2."""

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({"name": "Tariff Test Customer"})
        self.Shipment = self.env["dally.shipment"]
        self.Package = self.env["dally.shipment.package"]
        self.Rule = self.env["dally.freight.tariff.rule"]
        self.Family = self.env["dally.freight.tariff.family"]

        self.food = self.env.ref("dally_freight_billing.tariff_family_food")
        self.seafood = self.env.ref("dally_freight_billing.tariff_family_seafood")
        self.honey = self.env.ref("dally_freight_billing.tariff_family_honey")
        self.clothing = self.env.ref("dally_freight_billing.tariff_family_clothing")
        self.non_food = self.env.ref("dally_freight_billing.tariff_family_non_food")

    def _shipment(self, mode="air", **overrides):
        values = {
            "partner_id": self.partner.id,
            "transport_mode": mode,
            "direction": "export",
            "customer_segment_snapshot": "individual",
            "goods_received_on": "2026-08-21",
        }
        values.update(overrides)
        return self.Shipment.create(values)

    def _line(self, shipment, family, **overrides):
        values = {
            "shipment_id": shipment.id,
            "package_type": "parcel",
            "description": "Test goods",
            "quantity": 1,
            "unit_weight_kg": 10.0,
            "tariff_family_id": family.id,
            "billing_method": "real",
        }
        values.update(overrides)
        return self.Package.create(values)

    def _assert_standard_price(self, mode, family, expected):
        line = self._line(self._shipment(mode), family)
        line.action_apply_freight_tariff()
        self.assertAlmostEqual(line.applied_unit_price_eur, expected, places=2)
        self.assertEqual(line.pricing_type_snapshot, "standard")
        self.assertTrue(line.tariff_rule_id)
        self.assertTrue(line.tariff_applied_on)

    # ------------------------------------------------------------------
    # Exact workbook tariff grid
    # ------------------------------------------------------------------

    def test_air_food_is_3_50(self):
        self._assert_standard_price("air", self.food, 3.50)

    def test_air_seafood_is_3_50(self):
        self._assert_standard_price("air", self.seafood, 3.50)

    def test_air_honey_is_3_50(self):
        self._assert_standard_price("air", self.honey, 3.50)

    def test_air_clothing_is_5(self):
        self._assert_standard_price("air", self.clothing, 5.00)

    def test_air_non_food_is_5(self):
        self._assert_standard_price("air", self.non_food, 5.00)

    def test_sea_food_is_2_50(self):
        self._assert_standard_price("sea", self.food, 2.50)

    def test_sea_seafood_is_5(self):
        self._assert_standard_price("sea", self.seafood, 5.00)

    def test_sea_honey_is_5(self):
        self._assert_standard_price("sea", self.honey, 5.00)

    def test_sea_clothing_is_4(self):
        self._assert_standard_price("sea", self.clothing, 4.00)

    def test_sea_non_food_requires_manual_price(self):
        line = self._line(self._shipment("sea"), self.non_food)
        with self.assertRaises(UserError):
            line.action_apply_freight_tariff()
        self.assertFalse(line.applied_unit_price_eur)

    # ------------------------------------------------------------------
    # Historical/manual pricing is authoritative
    # ------------------------------------------------------------------

    def test_manual_historical_price_wins_over_grid(self):
        line = self._line(
            self._shipment("sea"),
            self.food,
            manual_unit_price_eur=2.00,
            pricing_reason="Tarif historique conservé lors de la fusion.",
            pricing_type_snapshot="special",
        )
        line.action_apply_freight_tariff()
        self.assertAlmostEqual(line.applied_unit_price_eur, 2.00, places=2)
        self.assertFalse(line.tariff_rule_id)
        self.assertEqual(line.pricing_type_snapshot, "special")

        # Reapplying after a grid change still cannot overwrite history because
        # the manual snapshot remains the authority.
        line.action_apply_freight_tariff()
        self.assertAlmostEqual(line.applied_unit_price_eur, 2.00, places=2)

    def test_campaign_price_keeps_promotion_type(self):
        line = self._line(
            self._shipment("air"),
            self.clothing,
            manual_unit_price_eur=2.00,
            pricing_reason="Campagne promotionnelle",
            pricing_type_snapshot="promotion",
        )
        line.action_apply_freight_tariff()
        self.assertAlmostEqual(line.applied_unit_price_eur, 2.00, places=2)
        self.assertEqual(line.pricing_type_snapshot, "promotion")
        self.assertFalse(line.tariff_rule_id)

    def test_manual_price_requires_reason(self):
        with self.assertRaises(ValidationError):
            self._line(
                self._shipment("air"),
                self.food,
                manual_unit_price_eur=2.00,
            )

    # ------------------------------------------------------------------
    # Weight method and price remain independent
    # ------------------------------------------------------------------

    def test_air_volumetric_billing_uses_167_snapshot(self):
        line = self._line(
            self._shipment("air"),
            self.food,
            unit_weight_kg=50.0,
            unit_volume_cbm=1.0,
            billing_method="volumetric",
        )
        line.action_apply_freight_tariff()
        self.assertAlmostEqual(line.volumetric_ratio_kg_cbm, 167.0, places=1)
        self.assertAlmostEqual(line.billable_weight_kg, 167.0, places=1)
        self.assertAlmostEqual(line.transport_amount_eur, 584.50, places=2)

    def test_sea_commercial_ratio_is_separate_from_operational_ratio(self):
        shipment = self._shipment("sea")
        line = self._line(
            shipment,
            self.food,
            unit_weight_kg=50.0,
            unit_volume_cbm=1.0,
            billing_method="volumetric",
        )
        line.action_apply_freight_tariff()

        # Current workbook commercial parameter: 300 kg/CBM.
        self.assertAlmostEqual(line.volumetric_ratio_kg_cbm, 300.0, places=1)
        self.assertAlmostEqual(line.billable_weight_kg, 300.0, places=1)
        self.assertAlmostEqual(line.transport_amount_eur, 750.0, places=2)

        # dally_freight operational chargeable weight remains 1000 kg/CBM for
        # sea. The billing module must not mutate that operational rule.
        self.assertAlmostEqual(shipment.chargeable_weight_kg, 1000.0, places=1)

    def test_real_weight_ignores_volumetric_ratio(self):
        line = self._line(
            self._shipment("air"),
            self.food,
            unit_weight_kg=50.0,
            unit_volume_cbm=10.0,
            billing_method="real",
        )
        line.action_apply_freight_tariff()
        self.assertAlmostEqual(line.billable_weight_kg, 50.0, places=1)
        self.assertAlmostEqual(line.transport_amount_eur, 175.0, places=2)

    # ------------------------------------------------------------------
    # Deterministic rule selection
    # ------------------------------------------------------------------

    def test_specific_customer_segment_wins_over_all(self):
        family = self.Family.create({"name": "Test segment", "code": "test_segment"})
        self.Rule.create({
            "name": "Generic",
            "transport_mode": "air",
            "family_id": family.id,
            "customer_segment": "all",
            "price_per_kg_eur": 10.0,
        })
        specific = self.Rule.create({
            "name": "Individual",
            "transport_mode": "air",
            "family_id": family.id,
            "customer_segment": "individual",
            "price_per_kg_eur": 8.0,
        })

        found = self.Rule._find_applicable(
            transport_mode="air",
            family=family,
            customer_segment="individual",
            pricing_date="2026-08-21",
        )
        self.assertEqual(found, specific)

    def test_overlapping_same_scope_is_rejected(self):
        family = self.Family.create({"name": "Test overlap", "code": "test_overlap"})
        self.Rule.create({
            "name": "First",
            "transport_mode": "sea",
            "family_id": family.id,
            "customer_segment": "all",
            "price_per_kg_eur": 3.0,
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
        })
        with self.assertRaises(ValidationError):
            self.Rule.create({
                "name": "Overlap",
                "transport_mode": "sea",
                "family_id": family.id,
                "customer_segment": "all",
                "price_per_kg_eur": 4.0,
                "date_from": "2026-06-01",
                "date_to": "2027-01-31",
            })

    def test_adjacent_non_overlapping_dates_are_allowed(self):
        family = self.Family.create({"name": "Test dates", "code": "test_dates"})
        old = self.Rule.create({
            "name": "Old",
            "transport_mode": "air",
            "family_id": family.id,
            "customer_segment": "all",
            "price_per_kg_eur": 3.0,
            "date_from": "2026-01-01",
            "date_to": "2026-06-30",
        })
        new = self.Rule.create({
            "name": "New",
            "transport_mode": "air",
            "family_id": family.id,
            "customer_segment": "all",
            "price_per_kg_eur": 4.0,
            "date_from": "2026-07-01",
        })
        self.assertTrue(old)
        self.assertTrue(new)
