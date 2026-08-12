# -*- coding: utf-8 -*-
"""The public catalogue contract.

Odoo is the source of truth for which fields the website's quote form asks for, so
this projection is a published contract. These tests pin it: a missing key breaks
the form silently, and an extra one leaks internal organisation.
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_core.models.dally_service_type import REQUIREMENT_FLAGS

#: Exactly the keys the contract promises. Asserted both ways: nothing missing,
#: nothing extra.
EXPECTED_KEYS = {
    "code", "name", "description", "active", "sort_order", *REQUIREMENT_FLAGS,
}


@tagged("post_install", "-at_install", "dally")
class TestServiceCatalogue(TransactionCase):

    def setUp(self):
        super().setUp()
        self.ServiceType = self.env["dally.service.type"]

    def _create(self, **overrides):
        values = {
            "name": "Test Service",
            "code": "test_service",
            "category": "other",
        }
        values.update(overrides)
        return self.ServiceType.create(values)

    # ─── Payload shape ────────────────────────────────────────────────

    def test_payload_has_exactly_the_contract_keys(self):
        payload = self.env.ref("dally_core.service_freight_sea")._dally_public_payload()
        self.assertEqual(
            set(payload), EXPECTED_KEYS,
            "The published contract changed: %s" % (set(payload) ^ EXPECTED_KEYS),
        )

    def test_payload_excludes_internal_organisation(self):
        """Category and published status are ours, not the form's business."""
        payload = self.env.ref("dally_core.service_freight_sea")._dally_public_payload()
        for internal in ("category", "published", "id", "create_uid", "write_date"):
            self.assertNotIn(internal, payload)

    def test_flags_are_booleans_not_none(self):
        """The form branches on them directly; None would be falsy but untypeable."""
        payload = self.env.ref("dally_core.service_sourcing")._dally_public_payload()
        for flag in REQUIREMENT_FLAGS:
            self.assertIsInstance(payload[flag], bool, flag)

    def test_sort_order_comes_from_sequence(self):
        service = self._create(code="ordered_service", sequence=42)
        self.assertEqual(service._dally_public_payload()["sort_order"], 42)

    def test_description_is_a_string_when_empty(self):
        """The front end renders it without a null check."""
        service = self._create(code="no_description", description=False)
        self.assertEqual(service._dally_public_payload()["description"], "")

    # ─── Active / inactive filtering ──────────────────────────────────

    def test_catalogue_lists_active_published_services(self):
        codes = {entry["code"] for entry in self.ServiceType._dally_public_catalogue()}
        self.assertIn("freight_sea", codes)
        self.assertIn("sourcing", codes)

    def test_catalogue_excludes_archived_service(self):
        service = self._create(code="archived_service")
        self.assertIn(
            "archived_service",
            {e["code"] for e in self.ServiceType._dally_public_catalogue()},
        )

        service.active = False
        self.assertNotIn(
            "archived_service",
            {e["code"] for e in self.ServiceType._dally_public_catalogue()},
            "An archived service must not be offerable: nobody could price it",
        )

    def test_catalogue_excludes_unpublished_service(self):
        self._create(code="internal_only", published=False)
        self.assertNotIn(
            "internal_only",
            {e["code"] for e in self.ServiceType._dally_public_catalogue()},
        )

    def test_catalogue_entries_are_marked_active(self):
        for entry in self.ServiceType._dally_public_catalogue():
            self.assertTrue(entry["active"], entry["code"])

    def test_catalogue_is_ordered_by_sort_order(self):
        orders = [e["sort_order"] for e in self.ServiceType._dally_public_catalogue()]
        self.assertEqual(orders, sorted(orders))

    # ─── Codes ────────────────────────────────────────────────────────

    def test_unknown_code_resolves_to_empty(self):
        for value in ("does_not_exist", "", False, None):
            self.assertFalse(self.ServiceType._get_by_code(value))

    def test_archived_service_still_resolves_by_code(self):
        """A request from last year points at a service since withdrawn."""
        service = self._create(code="withdrawn_x")
        service.active = False
        self.assertEqual(self.ServiceType._get_by_code("withdrawn_x"), service)

    def test_code_format_is_enforced(self):
        for bad in ("Freight_Sea", "freight sea", "freight-sea", "fret!"):
            with self.subTest(code=bad), self.assertRaises(ValidationError):
                self._create(code=bad)

    # ─── Flag coherence ───────────────────────────────────────────────

    def test_vehicle_and_goods_are_mutually_exclusive(self):
        """They describe the same thing — what is shipped."""
        with self.assertRaises(ValidationError):
            self._create(
                code="contradictory",
                requires_vehicle=True,
                requires_goods=True,
            )

    def test_seeded_flags_match_the_business(self):
        """Spot-check the seed data against how each service is actually quoted."""
        air = self.env.ref("dally_core.service_freight_air")
        self.assertTrue(air.requires_weight, "Air freight is priced on weight")
        self.assertFalse(air.requires_volume)

        sea = self.env.ref("dally_core.service_freight_sea")
        self.assertTrue(sea.requires_volume, "Sea freight is priced on volume")

        vehicle = self.env.ref("dally_core.service_freight_vehicle")
        self.assertTrue(vehicle.requires_vehicle)
        self.assertFalse(vehicle.requires_goods)

        sourcing = self.env.ref("dally_core.service_sourcing")
        self.assertTrue(sourcing.requires_budget)
        self.assertFalse(
            sourcing.requires_origin,
            "A sourcing enquiry has no port of loading yet",
        )

        other = self.env.ref("dally_core.service_other")
        self.assertFalse(any(other[flag] for flag in REQUIREMENT_FLAGS),
                         "A general enquiry must stay a simple form")
