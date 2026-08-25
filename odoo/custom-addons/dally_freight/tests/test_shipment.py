# -*- coding: utf-8 -*-
import re

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from .common import create_shipment, set_shipment_state


@tagged("post_install", "-at_install", "dally")
class TestDallyShipment(TransactionCase):
    """Freight arithmetic and lifecycle.

    Chargeable weight gets its own attention: under-quoting light bulky cargo is
    the most expensive routine mistake in this business.
    """

    REFERENCE_RE = re.compile(r"^DT-SHP-\d{4}-\d{6}$")

    def setUp(self):
        super().setUp()
        self.Shipment = self.env["dally.shipment"]
        self.partner = self.env["res.partner"].create({"name": "Test Customer"})
        self.senegal = self.env.ref("base.sn", raise_if_not_found=False)
        self.france = self.env.ref("base.fr", raise_if_not_found=False)

    def _shipment(self, **overrides):
        values = {
            "partner_id": self.partner.id,
            "transport_mode": "sea",
            "direction": "import",
        }
        values.update(overrides)
        # Le create() applique une garde d'état initial (§20). Un test
        # qui a besoin d'instancier directement en `arrived` passe par
        # l'helper de test qui utilise le token de bypass in-process.
        if values.get("state") and values["state"] not in ("draft", "request_received"):
            return create_shipment(self.env, values)
        return self.Shipment.create(values)

    # ─── Reference ────────────────────────────────────────────────────

    def test_reference_format(self):
        shipment = self._shipment()
        self.assertRegex(
            shipment.reference, self.REFERENCE_RE,
            "Expected DT-SHP-YYYY-NNNNNN as required by the specification",
        )

    def test_references_are_unique(self):
        references = {self._shipment().reference for _ in range(10)}
        self.assertEqual(len(references), 10)

    def test_copy_does_not_reuse_reference(self):
        shipment = self._shipment()
        duplicate = shipment.copy()
        self.assertNotEqual(duplicate.reference, shipment.reference)
        self.assertRegex(duplicate.reference, self.REFERENCE_RE)

    # ─── Route ────────────────────────────────────────────────────────

    def test_route_summary(self):
        shipment = self._shipment(
            origin_city="Le Havre",
            origin_country_id=self.france.id if self.france else False,
            destination_city="Dakar",
            destination_country_id=self.senegal.id if self.senegal else False,
        )
        self.assertIn("Le Havre", shipment.route_summary)
        self.assertIn("Dakar", shipment.route_summary)
        self.assertIn("→", shipment.route_summary)

    def test_route_summary_does_not_repeat_a_value(self):
        """Port and city are often the same word; it must not appear twice."""
        shipment = self._shipment(
            origin_location="Dakar", origin_city="Dakar",
            destination_city="Bamako",
        )
        self.assertEqual(shipment.route_summary.count("Dakar"), 1)

    def test_route_summary_with_only_destination(self):
        shipment = self._shipment(destination_city="Dakar")
        self.assertEqual(shipment.route_summary, "Dakar")

    # ─── Cargo totals ─────────────────────────────────────────────────

    def test_totals_computed_from_packages(self):
        shipment = self._shipment()
        self.env["dally.shipment.package"].create({
            "shipment_id": shipment.id,
            "package_type": "pallet",
            "quantity": 3,
            "unit_weight_kg": 250.0,
            "length_cm": 120.0, "width_cm": 100.0, "height_cm": 150.0,
        })
        # 1.20 × 1.00 × 1.50 = 1.8 CBM per pallet
        self.assertAlmostEqual(shipment.volume_cbm, 5.4, places=3)
        self.assertAlmostEqual(shipment.weight_kg, 750.0, places=3)
        self.assertEqual(shipment.packages_count, 3)

    def test_totals_accept_manual_entry_without_packages(self):
        """At quotation time the detail is rarely known yet."""
        shipment = self._shipment(weight_kg=500.0, volume_cbm=2.5, packages_count=4)
        self.assertAlmostEqual(shipment.weight_kg, 500.0)
        self.assertAlmostEqual(shipment.volume_cbm, 2.5)
        self.assertEqual(shipment.packages_count, 4)

    def test_packages_override_manual_totals(self):
        shipment = self._shipment(weight_kg=999.0)
        self.env["dally.shipment.package"].create({
            "shipment_id": shipment.id,
            "package_type": "parcel",
            "quantity": 2,
            "unit_weight_kg": 10.0,
        })
        self.assertAlmostEqual(
            shipment.weight_kg, 20.0,
            msg="Once package detail exists, it is the authority",
        )

    def test_partial_dimensions_do_not_zero_a_manual_volume(self):
        line = self.env["dally.shipment.package"].create({
            "shipment_id": self._shipment().id,
            "package_type": "other",
            "quantity": 1,
            "unit_volume_cbm": 3.0,
            "length_cm": 100.0,   # width and height missing
        })
        self.assertAlmostEqual(line.unit_volume_cbm, 3.0)

    # ─── Chargeable weight ────────────────────────────────────────────

    def test_chargeable_weight_air_uses_iata_ratio(self):
        """2 CBM of light cargo bills as 334 kg by air, not its 50 kg."""
        shipment = self._shipment(
            transport_mode="air", weight_kg=50.0, volume_cbm=2.0,
        )
        self.assertAlmostEqual(shipment.chargeable_weight_kg, 334.0, places=1)

    def test_chargeable_weight_keeps_actual_when_dense(self):
        shipment = self._shipment(
            transport_mode="air", weight_kg=1000.0, volume_cbm=1.0,
        )
        self.assertAlmostEqual(shipment.chargeable_weight_kg, 1000.0, places=1)

    def test_chargeable_weight_groupage_one_cbm_per_tonne(self):
        shipment = self._shipment(
            transport_mode="groupage", weight_kg=300.0, volume_cbm=1.5,
        )
        self.assertAlmostEqual(shipment.chargeable_weight_kg, 1500.0, places=1)

    def test_chargeable_weight_without_volume(self):
        shipment = self._shipment(transport_mode="air", weight_kg=120.0)
        self.assertAlmostEqual(shipment.chargeable_weight_kg, 120.0)

    def test_chargeable_weight_unknown_mode_falls_back_to_gross(self):
        shipment = self._shipment(
            transport_mode="other", weight_kg=100.0, volume_cbm=5.0,
        )
        self.assertAlmostEqual(shipment.chargeable_weight_kg, 100.0)

    def test_chargeable_weight_recomputes_on_mode_change(self):
        shipment = self._shipment(
            transport_mode="sea", weight_kg=100.0, volume_cbm=1.0,
        )
        self.assertAlmostEqual(shipment.chargeable_weight_kg, 1000.0)
        shipment.transport_mode = "air"
        self.assertAlmostEqual(shipment.chargeable_weight_kg, 167.0, places=1)

    # ─── Dates and lateness ───────────────────────────────────────────

    def test_arrival_before_departure_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._shipment(
                departure_date="2026-03-10", actual_arrival="2026-03-01",
            )

    def test_eta_before_departure_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._shipment(
                departure_date="2026-03-10", estimated_arrival="2026-03-05",
            )

    def test_is_late_when_past_eta(self):
        shipment = self._shipment(
            estimated_arrival="2020-01-01", state="in_transit",
        )
        self.assertTrue(shipment.is_late)

    def test_not_late_once_arrived(self):
        shipment = self._shipment(
            estimated_arrival="2020-01-01",
            actual_arrival="2020-01-05",
            state="arrived",
        )
        self.assertFalse(shipment.is_late)

    def test_not_late_when_delivered(self):
        shipment = self._shipment(estimated_arrival="2020-01-01")
        set_shipment_state(shipment, "delivered")
        self.assertFalse(shipment.is_late)

    def test_not_late_without_eta(self):
        self.assertFalse(self._shipment(state="in_transit").is_late)

    def test_is_late_is_searchable(self):
        """Operations needs a "what is late" list; a non-stored compute needs
        an explicit search method for that to work."""
        late = self._shipment(estimated_arrival="2020-01-01", state="in_transit")
        on_time = self._shipment(estimated_arrival="2999-01-01", state="in_transit")

        found_late = self.Shipment.search([("is_late", "=", True)])
        self.assertIn(late, found_late)
        self.assertNotIn(on_time, found_late)

        found_ok = self.Shipment.search([("is_late", "=", False)])
        self.assertIn(on_time, found_ok)
        self.assertNotIn(late, found_ok)

    # ─── Lifecycle ────────────────────────────────────────────────────

    def test_state_change_stamps_the_time(self):
        shipment = self._shipment()
        self.assertFalse(shipment.state_changed_on)
        set_shipment_state(shipment, "in_transit")
        self.assertTrue(shipment.state_changed_on)

    def test_departure_date_filled_on_departure(self):
        shipment = self._shipment()
        set_shipment_state(shipment, "departed")
        self.assertTrue(shipment.departure_date)

    def test_existing_departure_date_is_not_overwritten(self):
        shipment = self._shipment(departure_date="2026-01-15")
        set_shipment_state(shipment, "departed")
        self.assertEqual(str(shipment.departure_date), "2026-01-15")

    def test_delivery_fills_arrival_and_delivery_dates(self):
        shipment = self._shipment()
        set_shipment_state(shipment, "delivered")
        self.assertTrue(shipment.actual_arrival)
        self.assertTrue(shipment.delivery_date)

    def test_unknown_state_is_rejected(self):
        with self.assertRaises(UserError):
            self._shipment().action_set_state("teleported")

    def test_delivered_cannot_be_cancelled(self):
        shipment = self._shipment()
        set_shipment_state(shipment, "delivered")
        with self.assertRaises(UserError):
            shipment.action_cancel()

    # ─── Deletion ─────────────────────────────────────────────────────

    def test_in_progress_shipment_cannot_be_deleted(self):
        """It is an operational record the customer has been told about (§87)."""
        shipment = self._shipment(state="in_transit")
        with self.assertRaises(UserError):
            shipment.unlink()

    def test_draft_shipment_can_be_deleted(self):
        shipment = self._shipment()
        shipment.unlink()
        self.assertFalse(shipment.exists())

    def test_cancelled_shipment_can_be_deleted(self):
        shipment = self._shipment(state="cancelled")
        shipment.unlink()
        self.assertFalse(shipment.exists())

    # ─── Consistency ──────────────────────────────────────────────────

    def test_consignee_cannot_equal_customer(self):
        with self.assertRaises(ValidationError):
            self._shipment(consignee_id=self.partner.id)

    def test_negative_weight_is_rejected_by_database(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._shipment(weight_kg=-5.0)
            self.env.flush_all()
