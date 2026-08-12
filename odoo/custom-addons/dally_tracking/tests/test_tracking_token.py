# -*- coding: utf-8 -*-
"""The tracking token.

The reference stays human-readable and therefore sequential; the token is what
stops the series being walked. These tests check both properties that matter:
the token is unpredictable, and the reference alone is never enough.
"""

import json
import re

from odoo.tests import HttpCase, TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestTrackingToken(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Shipment = self.env["dally.shipment"]
        self.partner = self.env["res.partner"].create({"name": "Token Customer"})

    def _shipment(self, **overrides):
        values = {
            "partner_id": self.partner.id,
            "transport_mode": "sea",
            "direction": "import",
        }
        values.update(overrides)
        return self.Shipment.create(values)

    # ─── Generation ───────────────────────────────────────────────────

    def test_token_generated_at_creation(self):
        """Lazy generation would let a shipment be notified before it had one."""
        shipment = self._shipment()
        self.assertTrue(shipment.public_tracking_token)
        self.assertGreaterEqual(len(shipment.public_tracking_token), 32)

    def test_tokens_are_unique(self):
        tokens = {self._shipment().public_tracking_token for _ in range(30)}
        self.assertEqual(len(tokens), 30)

    def test_token_is_not_predictable_from_the_reference(self):
        """The reference is sequential; the token must share nothing with it."""
        first = self._shipment()
        second = self._shipment()

        self.assertNotIn(first.reference, first.public_tracking_token)
        self.assertNotIn(
            str(first.id), first.public_tracking_token,
            "The database id must never appear in the token",
        )
        # Consecutive shipments must not produce tokens with a shared prefix, which
        # is what a counter or a timestamp would leak.
        shared = 0
        for a, b in zip(first.public_tracking_token, second.public_tracking_token):
            if a != b:
                break
            shared += 1
        self.assertLess(shared, 8, "Tokens share a suspiciously long prefix")

    def test_token_uses_url_safe_characters(self):
        """It travels in a query string, in e-mails and in WhatsApp messages."""
        token = self._shipment().public_tracking_token
        self.assertRegex(token, re.compile(r"^[A-Za-z0-9_-]+$"))

    def test_copy_does_not_reuse_the_token(self):
        shipment = self._shipment()
        duplicate = shipment.copy()
        self.assertTrue(duplicate.public_tracking_token)
        self.assertNotEqual(
            duplicate.public_tracking_token, shipment.public_tracking_token
        )

    # ─── Matching ─────────────────────────────────────────────────────

    def test_correct_token_matches(self):
        shipment = self._shipment()
        self.assertTrue(
            shipment._dally_token_matches(shipment.public_tracking_token)
        )

    def test_wrong_token_does_not_match(self):
        shipment = self._shipment()
        for candidate in ("", None, 12345, "wrong-token-value",
                          shipment.public_tracking_token[:-1],
                          shipment.public_tracking_token + "x"):
            with self.subTest(candidate=candidate):
                self.assertFalse(shipment._dally_token_matches(candidate))

    def test_rotation_invalidates_the_previous_token(self):
        shipment = self._shipment()
        old = shipment.public_tracking_token

        shipment.action_rotate_tracking_token()

        self.assertNotEqual(shipment.public_tracking_token, old)
        self.assertFalse(shipment._dally_token_matches(old))
        self.assertTrue(
            shipment._dally_token_matches(shipment.public_tracking_token)
        )

    def test_rotation_is_logged(self):
        shipment = self._shipment()
        shipment.action_rotate_tracking_token()
        self.assertIn(
            "rotated",
            " ".join(shipment.message_ids.mapped("body")).lower(),
        )

    # ─── Lookup requires both ─────────────────────────────────────────

    def test_lookup_requires_the_token(self):
        shipment = self._shipment()
        self.assertFalse(
            self.Shipment._dally_find_for_tracking(shipment.reference, ""),
            "The reference alone must never resolve: the series is walkable",
        )
        self.assertFalse(
            self.Shipment._dally_find_for_tracking(shipment.reference, None)
        )

    def test_lookup_succeeds_with_both(self):
        shipment = self._shipment()
        self.assertEqual(
            self.Shipment._dally_find_for_tracking(
                shipment.reference, shipment.public_tracking_token
            ),
            shipment,
        )

    def test_lookup_fails_with_a_wrong_token(self):
        shipment = self._shipment()
        other = self._shipment()
        self.assertFalse(
            self.Shipment._dally_find_for_tracking(
                shipment.reference, other.public_tracking_token
            ),
            "A token is bound to one shipment",
        )

    def test_unknown_reference_and_wrong_token_are_indistinguishable(self):
        shipment = self._shipment()
        unknown = self.Shipment._dally_find_for_tracking(
            "DT-SHP-2026-999999", shipment.public_tracking_token
        )
        wrong_token = self.Shipment._dally_find_for_tracking(
            shipment.reference, "definitely-not-the-right-token-value"
        )
        self.assertFalse(unknown)
        self.assertFalse(wrong_token)

    def test_token_absent_from_the_public_payload(self):
        """It would end up in browser history, proxy logs and screenshots."""
        shipment = self._shipment()
        serialised = json.dumps(shipment._dally_public_payload())
        self.assertNotIn(shipment.public_tracking_token, serialised)
        self.assertNotIn("public_tracking_token", serialised)
        self.assertNotIn("token", serialised.lower())

    def test_tracking_url_contains_reference_and_token(self):
        shipment = self._shipment()
        url = shipment.public_tracking_url
        self.assertIn(shipment.reference, url)
        self.assertIn(shipment.public_tracking_token, url)
        self.assertIn("/tracking", url)


@tagged("post_install", "-at_install", "dally")
class TestTrackingTokenEndpoint(HttpCase):
    """The token requirement, through the real HTTP stack."""

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({"name": "HTTP Token Customer"})
        self.shipment = self.env["dally.shipment"].create({
            "partner_id": self.partner.id,
            "transport_mode": "air",
            "direction": "export",
            "origin_city": "Dakar",
            "destination_city": "Paris",
        })
        self.key = self.env["dally.api.key"].create({
            "name": "Tracking token test key",
            "scopes": "tracking:read",
            "allowed_ips": "",
            "user_id": self.env.ref("dally_tracking.user_dally_api_tracking").id,
        })
        self.raw_key = self.key.key_to_display

    def _get(self, reference, token=None):
        url = "/api/v1/tracking/%s" % reference
        if token is not None:
            url = "%s?token=%s" % (url, token)
        return self.url_open(
            url, headers={"X-API-Key": self.raw_key}, timeout=30
        )

    def test_reference_alone_is_refused(self):
        response = self._get(self.shipment.reference)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_reference_with_token_succeeds(self):
        response = self._get(
            self.shipment.reference, self.shipment.public_tracking_token
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["reference"], self.shipment.reference
        )

    def test_wrong_token_is_refused_identically_to_an_unknown_reference(self):
        wrong = self._get(self.shipment.reference, "x" * 43)
        unknown = self._get("DT-SHP-2026-999999",
                            self.shipment.public_tracking_token)
        self.assertEqual(wrong.status_code, 404)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(wrong.json()["error"], unknown.json()["error"])

    def test_short_token_is_refused_without_a_database_lookup(self):
        response = self._get(self.shipment.reference, "abc")
        self.assertEqual(response.status_code, 404)

    def test_enumeration_yields_nothing(self):
        """Walking the series must not return a single shipment."""
        year = self.shipment.reference.split("-")[2]
        for number in range(1, 15):
            reference = "DT-SHP-%s-%06d" % (year, number)
            response = self._get(reference)
            self.assertEqual(
                response.status_code, 404,
                "Reference %s answered without a token" % reference,
            )

    def test_rotated_token_stops_working(self):
        old = self.shipment.public_tracking_token
        self.assertEqual(self._get(self.shipment.reference, old).status_code, 200)

        self.shipment.action_rotate_tracking_token()

        self.assertEqual(self._get(self.shipment.reference, old).status_code, 404)
        self.assertEqual(
            self._get(
                self.shipment.reference, self.shipment.public_tracking_token
            ).status_code,
            200,
        )

    def test_token_absent_from_the_response(self):
        response = self._get(
            self.shipment.reference, self.shipment.public_tracking_token
        )
        self.assertNotIn(self.shipment.public_tracking_token, response.text)

    def test_no_listing_endpoint(self):
        response = self.url_open(
            "/api/v1/tracking",
            headers={"X-API-Key": self.raw_key},
            timeout=30,
        )
        self.assertEqual(response.status_code, 400)
