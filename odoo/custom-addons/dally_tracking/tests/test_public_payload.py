# -*- coding: utf-8 -*-
"""The confidentiality boundary (§44).

If any test in this file fails, sensitive data can reach the internet. They are
written to be blunt about it: rather than checking a handful of known-bad keys,
they assert the payload's keys against the declared allowlist and scan the
serialised output for the values themselves.
"""

import json

from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_tracking.models.dally_shipment import (
    FORBIDDEN_PUBLIC_FIELDS,
    PUBLIC_PAYLOAD_KEYS,
)


@tagged("post_install", "-at_install", "dally")
class TestPublicPayload(TransactionCase):

    #: Distinctive values planted in confidential fields. If any of these strings
    #: appears in the payload, something leaked.
    SECRET_COST = 987654.321
    SECRET_NOTE = "CONFIDENTIAL-AGENT-MARGIN-DO-NOT-DISCLOSE"
    SECRET_VALUE = 555444.111

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({
            "name": "Sensitive Customer SARL",
            "email": "private@example.com",
        })
        self.shipment = self.env["dally.shipment"].create({
            "partner_id": self.partner.id,
            "transport_mode": "sea",
            "direction": "import",
            "origin_city": "Le Havre",
            "destination_city": "Dakar",
            "goods_description": "Spare parts",
            "estimated_arrival": "2026-09-15",
            "supplier_cost": self.SECRET_COST,
            "declared_value": self.SECRET_VALUE,
            "internal_notes": self.SECRET_NOTE,
        })
        self.Event = self.env["dally.shipment.event"]

    # ─── Allowlist ────────────────────────────────────────────────────

    def test_payload_keys_are_within_the_allowlist(self):
        """The guarantee that survives future field additions."""
        payload = self.shipment._dally_public_payload()
        unexpected = set(payload) - PUBLIC_PAYLOAD_KEYS
        self.assertFalse(
            unexpected,
            "Keys not declared in PUBLIC_PAYLOAD_KEYS reached the payload: %s"
            % unexpected,
        )

    def test_no_forbidden_key_in_payload(self):
        payload = self.shipment._dally_public_payload()
        for forbidden in FORBIDDEN_PUBLIC_FIELDS:
            self.assertNotIn(forbidden, payload)

    def test_no_database_id_anywhere(self):
        """A sequential id must never become an authorisation handle (§42)."""
        self.Event.create({
            "shipment_id": self.shipment.id,
            "status": "departed",
            "description": "Departed from Le Havre",
            "visible_to_customer": True,
        })
        serialised = json.dumps(self.shipment._dally_public_payload())
        self.assertNotIn('"id"', serialised)
        self.assertNotIn('"_id"', serialised)

    # ─── Confidential values ──────────────────────────────────────────

    def test_supplier_cost_never_appears(self):
        serialised = json.dumps(self.shipment._dally_public_payload())
        self.assertNotIn(str(self.SECRET_COST), serialised)
        self.assertNotIn("987654", serialised)

    def test_internal_notes_never_appear(self):
        serialised = json.dumps(self.shipment._dally_public_payload())
        self.assertNotIn(self.SECRET_NOTE, serialised)
        self.assertNotIn("CONFIDENTIAL", serialised)

    def test_declared_value_never_appears(self):
        """The customs value is the customer's business but not tracking data."""
        serialised = json.dumps(self.shipment._dally_public_payload())
        self.assertNotIn(str(self.SECRET_VALUE), serialised)
        self.assertNotIn("555444", serialised)

    def test_customer_identity_never_appears(self):
        """Someone walking references must not learn who ships what."""
        serialised = json.dumps(self.shipment._dally_public_payload())
        self.assertNotIn("Sensitive Customer", serialised)
        self.assertNotIn("private@example.com", serialised)

    def test_internal_note_of_a_visible_event_never_appears(self):
        """A published event may still carry a private note."""
        self.Event.create({
            "shipment_id": self.shipment.id,
            "status": "in_transit",
            "description": "In transit",
            "internal_note": "SECRET-EVENT-NOTE agent unreliable, chase daily",
            "visible_to_customer": True,
        })
        serialised = json.dumps(self.shipment._dally_public_payload())
        self.assertIn("In transit", serialised)
        self.assertNotIn("SECRET-EVENT-NOTE", serialised)
        self.assertNotIn("unreliable", serialised)

    def test_attachments_never_appear(self):
        """Publishing an event is not the same decision as publishing a document."""
        attachment = self.env["ir.attachment"].create({
            "name": "bill-of-lading-CONFIDENTIAL.pdf",
            "datas": b"ZmFrZQ==",
        })
        self.Event.create({
            "shipment_id": self.shipment.id,
            "status": "departed",
            "description": "Goods loaded",
            "visible_to_customer": True,
            "attachment_ids": [(6, 0, attachment.ids)],
        })
        serialised = json.dumps(self.shipment._dally_public_payload())
        self.assertNotIn("bill-of-lading", serialised)
        self.assertNotIn("attachment", serialised.lower())

    # ─── Timeline filtering ───────────────────────────────────────────

    def test_timeline_contains_only_visible_events(self):
        self.Event.create({
            "shipment_id": self.shipment.id,
            "status": "goods_received",
            "description": "PUBLIC goods received",
            "visible_to_customer": True,
        })
        self.Event.create({
            "shipment_id": self.shipment.id,
            "status": "preparing",
            "description": "INTERNAL awaiting agent confirmation",
            "visible_to_customer": False,
        })

        payload = self.shipment._dally_public_payload()
        descriptions = [entry["description"] for entry in payload["timeline"]]

        self.assertTrue(any("PUBLIC" in d for d in descriptions))
        self.assertFalse(
            any("INTERNAL" in d for d in descriptions),
            "An internal event reached the public timeline",
        )

    def test_event_payload_refuses_invisible_events_even_if_asked(self):
        """Defence in depth: the projection filters again, on its own."""
        hidden = self.Event.create({
            "shipment_id": self.shipment.id,
            "status": "preparing",
            "description": "INTERNAL should never publish",
            "visible_to_customer": False,
        })
        self.assertEqual(
            hidden._dally_public_event_payload(), [],
            "Passing an internal event directly must still publish nothing",
        )

    def test_timeline_is_chronological(self):
        """A customer reads a journey forwards."""
        self.Event.create({
            "shipment_id": self.shipment.id,
            "event_date": "2026-03-10 08:00:00",
            "status": "departed", "description": "Second",
            "visible_to_customer": True,
        })
        self.Event.create({
            "shipment_id": self.shipment.id,
            "event_date": "2026-03-01 08:00:00",
            "status": "goods_received", "description": "First",
            "visible_to_customer": True,
        })
        timeline = self.shipment._dally_public_payload()["timeline"]
        self.assertEqual([e["description"] for e in timeline], ["First", "Second"])

    def test_empty_timeline_is_a_list_not_null(self):
        """The front end iterates it without a null check."""
        payload = self.shipment._dally_public_payload()
        self.assertIsInstance(payload["timeline"], list)

    # ─── Content the customer is entitled to ──────────────────────────

    def test_payload_contains_what_the_customer_needs(self):
        payload = self.shipment._dally_public_payload()
        self.assertEqual(payload["reference"], self.shipment.reference)
        self.assertEqual(payload["status"], "draft")
        self.assertTrue(payload["statusLabel"])
        self.assertIn("Le Havre", payload["origin"])
        self.assertIn("Dakar", payload["destination"])
        self.assertEqual(payload["estimatedArrival"], "2026-09-15")
        self.assertEqual(payload["goodsDescription"], "Spare parts")

    def test_status_label_is_human_readable(self):
        """The label, not the technical code, is what is displayed."""
        self.shipment.state = "in_transit"
        payload = self.shipment._dally_public_payload()
        self.assertEqual(payload["status"], "in_transit")
        self.assertNotEqual(payload["statusLabel"], "in_transit")

    def test_last_update_follows_the_latest_visible_event(self):
        self.Event.create({
            "shipment_id": self.shipment.id,
            "event_date": "2026-04-02 10:00:00",
            "status": "in_transit", "description": "Latest news",
            "visible_to_customer": True,
        })
        payload = self.shipment._dally_public_payload()
        self.assertTrue(payload["lastUpdate"].startswith("2026-04-02"))

    def test_last_update_ignores_internal_events(self):
        """An internal update must not make the customer think something moved."""
        # Aucune transition d'état ici : elle en engendrerait un événement
        # automatique, dont la publication dépend de la politique. Ce test
        # porte sur les deux événements posés explicitement ci-dessous, et sur
        # rien d'autre.
        self.Event.create({
            "shipment_id": self.shipment.id,
            "event_date": "2026-04-01 10:00:00",
            "status": "goods_received", "description": "Received",
            "visible_to_customer": True,
        })
        self.Event.create({
            "shipment_id": self.shipment.id,
            "event_date": "2026-04-05 10:00:00",
            "status": "preparing", "description": "INTERNAL chase agent",
            "visible_to_customer": False,
        })
        payload = self.shipment._dally_public_payload()
        self.assertTrue(
            payload["lastUpdate"].startswith("2026-04-01"),
            "lastUpdate must reflect the newest event the customer can see",
        )

    # ─── Reference resolution ─────────────────────────────────────────

    def test_reference_lookup_is_case_and_space_insensitive(self):
        Shipment = self.env["dally.shipment"]
        reference = self.shipment.reference
        for typed in (
            reference.lower(),
            "  %s  " % reference,
            reference.replace("-", "-"),
            " %s " % reference,       # pasted from a PDF
            reference.replace("DT", "dt"),
        ):
            with self.subTest(typed=typed):
                self.assertEqual(
                    Shipment._dally_find_for_tracking(
                        typed, self.shipment.public_tracking_token
                    ),
                    self.shipment,
                )

    def test_unknown_reference_returns_empty_recordset(self):
        Shipment = self.env["dally.shipment"]
        for typed in ("DT-SHP-2026-999999", "", None, "garbage", 12345):
            with self.subTest(typed=typed):
                self.assertFalse(
                    Shipment._dally_find_for_tracking(
                        typed, self.shipment.public_tracking_token
                    )
                )

    def test_carrier_number_is_not_searchable_for_tracking(self):
        """Matching a carrier's number would let anyone holding a bill of lading
        probe for shipments that are not theirs."""
        self.shipment.carrier_tracking_number = "MSCU1234567"
        self.assertFalse(
            self.env["dally.shipment"]._dally_find_for_tracking(
                "MSCU1234567", self.shipment.public_tracking_token
            )
        )
