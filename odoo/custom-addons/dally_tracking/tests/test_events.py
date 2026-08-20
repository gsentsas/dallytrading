# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestShipmentEvents(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({"name": "Event Customer"})
        self.Shipment = self.env["dally.shipment"]
        self.Event = self.env["dally.shipment.event"]
        self.shipment = self.Shipment.create({
            "partner_id": self.partner.id,
            "transport_mode": "sea",
            "direction": "import",
            "origin_city": "Le Havre",
            "destination_city": "Dakar",
        })

    # ─── Defaults ─────────────────────────────────────────────────────

    def test_visibility_defaults_to_false(self):
        """A forgotten checkbox must fail closed."""
        event = self.Event.create({
            "shipment_id": self.shipment.id,
            "status": "preparing",
            "description": "Some update",
        })
        self.assertFalse(event.visible_to_customer)

    def test_description_is_required(self):
        with self.assertRaises(Exception):
            self.Event.create({
                "shipment_id": self.shipment.id,
                "status": "preparing",
            })

    def test_published_event_needs_a_meaningful_description(self):
        with self.assertRaises(ValidationError):
            self.Event.create({
                "shipment_id": self.shipment.id,
                "status": "departed",
                "description": "ok",
                "visible_to_customer": True,
            })

    def test_internal_event_may_have_a_terse_description(self):
        event = self.Event.create({
            "shipment_id": self.shipment.id,
            "status": "preparing",
            "description": "tbc",
        })
        self.assertTrue(event.id)

    # ─── Automatic events on status change ────────────────────────────

    def test_status_change_creates_an_event(self):
        self.shipment.state = "departed"
        events = self.shipment.event_ids.filtered(lambda e: e.status == "departed")
        self.assertEqual(len(events), 1)
        self.assertTrue(events.is_automatic)

    def test_customer_milestone_is_published(self):
        self.shipment.state = "delivered"
        event = self.shipment.event_ids.filtered(lambda e: e.status == "delivered")
        self.assertTrue(
            event.visible_to_customer,
            "Delivery is exactly the milestone a customer wants to see",
        )

    def test_publication_follows_the_state_wording(self):
        """Publication follows `_dally_public_state_wording()`, not a fixed list.

        Two tests used to live here, asserting that `awaiting_goods` and
        `cancelled` were never published. That was true of the hardcoded
        dictionary this module once owned; it stops being true the moment
        `dally_freight_notifications` moves the decision into a configuration
        table, where both states are publishable.

        What holds in either case is the rule itself: the transition is always
        recorded, and it is published if and only if the state appears among the
        publishable wordings. Testing the rule rather than one of its outcomes
        is what lets an operator change the policy without breaking this file.
        """
        publishable = self.env["dally.shipment"]._dally_public_state_wording()

        for state in ("awaiting_goods", "cancelled"):
            self.shipment.state = state
            event = self.shipment.event_ids.filtered(lambda e: e.status == state)
            self.assertTrue(event, "The transition must still be recorded")
            self.assertEqual(
                event.visible_to_customer,
                state in publishable,
                "%s: publication disagrees with the policy" % state,
            )

    def test_departure_event_carries_the_origin(self):
        self.shipment.state = "departed"
        event = self.shipment.event_ids.filtered(lambda e: e.status == "departed")
        self.assertIn("Le Havre", event.location or "")

    def test_arrival_event_carries_the_destination(self):
        self.shipment.state = "arrived"
        event = self.shipment.event_ids.filtered(lambda e: e.status == "arrived")
        self.assertIn("Dakar", event.location or "")

    def test_intermediate_state_leaves_location_empty(self):
        """A wrong location is worse than none."""
        self.shipment.state = "preparing"
        event = self.shipment.event_ids.filtered(lambda e: e.status == "preparing")
        self.assertFalse(event.location)

    def test_rewriting_the_same_status_creates_no_duplicate(self):
        self.shipment.state = "in_transit"
        count = len(self.shipment.event_ids)
        self.shipment.write({"state": "in_transit"})
        self.assertEqual(
            len(self.shipment.event_ids), count,
            "Writing the current status again must not add an event",
        )

    def test_full_journey_builds_a_coherent_timeline(self):
        for state in ("goods_received", "departed", "in_transit", "arrived", "delivered"):
            self.shipment.state = state

        published = self.shipment.event_ids.filtered("visible_to_customer")
        self.assertEqual(len(published), 5)
        statuses = published.sorted(key=lambda e: (e.event_date, e.id)).mapped("status")
        self.assertEqual(
            statuses,
            ["goods_received", "departed", "in_transit", "arrived", "delivered"],
        )

    # ─── Counters ─────────────────────────────────────────────────────

    def test_event_counters(self):
        self.Event.create({
            "shipment_id": self.shipment.id, "status": "preparing",
            "description": "internal one", "visible_to_customer": False,
        })
        self.Event.create({
            "shipment_id": self.shipment.id, "status": "departed",
            "description": "public one", "visible_to_customer": True,
        })
        self.assertEqual(self.shipment.event_count, 2)
        self.assertEqual(self.shipment.public_event_count, 1)

    def test_last_public_event(self):
        self.Event.create({
            "shipment_id": self.shipment.id,
            "event_date": "2026-01-01 08:00:00",
            "status": "goods_received", "description": "Older public",
            "visible_to_customer": True,
        })
        newest = self.Event.create({
            "shipment_id": self.shipment.id,
            "event_date": "2026-02-01 08:00:00",
            "status": "departed", "description": "Newer public",
            "visible_to_customer": True,
        })
        self.Event.create({
            "shipment_id": self.shipment.id,
            "event_date": "2026-03-01 08:00:00",
            "status": "preparing", "description": "Newest internal",
            "visible_to_customer": False,
        })
        self.assertEqual(self.shipment.last_public_event_id, newest)

    # ─── Cascade ──────────────────────────────────────────────────────

    def test_events_are_removed_with_the_shipment(self):
        event = self.Event.create({
            "shipment_id": self.shipment.id, "status": "preparing",
            "description": "will be removed",
        })
        self.shipment.unlink()          # draft: deletion allowed
        self.assertFalse(event.exists())

    def test_company_is_inherited_from_the_shipment(self):
        event = self.Event.create({
            "shipment_id": self.shipment.id, "status": "preparing",
            "description": "company check",
        })
        self.assertEqual(event.company_id, self.shipment.company_id)


@tagged("post_install", "-at_install", "dally")
class TestTrackingApiUserRights(TransactionCase):
    """The tracking API user must be unable to reach anything confidential.

    This is the first of the three confidentiality layers: not a filter applied
    afterwards, but rights that prevent the data from being loaded at all.
    """

    def setUp(self):
        super().setUp()
        self.api_user = self.env.ref("dally_tracking.user_dally_api_tracking")
        self.partner = self.env["res.partner"].create({"name": "Rights Customer"})
        self.shipment = self.env["dally.shipment"].create({
            "partner_id": self.partner.id,
            "transport_mode": "air",
            "direction": "export",
            "supplier_cost": 4242.0,
            "internal_notes": "LEAK-CANARY internal note",
        })
        self.Event = self.env["dally.shipment.event"]

    def test_api_user_is_in_no_dallytrading_business_group(self):
        """Membership of group_dally_readonly would expose internal_notes."""
        for group in (
            "dally_core.group_dally_readonly",
            "dally_core.group_dally_commercial",
            "dally_core.group_dally_finance",
            "dally_core.group_dally_logistics",
            "dally_core.group_dally_manager",
            "dally_core.group_dally_admin",
            "base.group_system",
        ):
            self.assertFalse(
                self.api_user.has_group(group),
                "The tracking API user must not hold %s" % group,
            )
        self.assertTrue(
            self.api_user.has_group("dally_tracking.group_dally_tracking_api")
        )

    def test_api_user_can_read_a_shipment(self):
        shipment = self.shipment.with_user(self.api_user)
        self.assertEqual(shipment.reference, self.shipment.reference)

    def test_api_user_cannot_read_supplier_cost(self):
        with self.assertRaises(AccessError):
            self.shipment.with_user(self.api_user).read(["supplier_cost"])

    def test_api_user_cannot_read_internal_notes(self):
        with self.assertRaises(AccessError):
            self.shipment.with_user(self.api_user).read(["internal_notes"])

    def test_restricted_fields_are_not_even_described(self):
        available = self.env["dally.shipment"].with_user(self.api_user).fields_get()
        for field in ("supplier_cost", "margin", "internal_notes"):
            self.assertNotIn(field, available)

    def test_api_user_cannot_write(self):
        with self.assertRaises(AccessError):
            self.shipment.with_user(self.api_user).write({"origin_city": "Nope"})

    def test_api_user_cannot_create_a_shipment(self):
        with self.assertRaises(AccessError):
            self.env["dally.shipment"].with_user(self.api_user).create({
                "partner_id": self.partner.id,
                "transport_mode": "sea",
                "direction": "import",
            })

    def test_record_rule_hides_internal_events_entirely(self):
        """The second layer: a search with no domain still returns nothing internal."""
        self.Event.create({
            "shipment_id": self.shipment.id, "status": "departed",
            "description": "Public departure", "visible_to_customer": True,
        })
        self.Event.create({
            "shipment_id": self.shipment.id, "status": "preparing",
            "description": "INTERNAL-CANARY do not publish",
            "visible_to_customer": False,
        })

        visible = self.Event.with_user(self.api_user).search([])
        descriptions = visible.mapped("description")
        self.assertTrue(any("Public departure" in d for d in descriptions))
        self.assertFalse(
            any("INTERNAL-CANARY" in d for d in descriptions),
            "The record rule must hide internal events from the API user",
        )

    def test_api_user_cannot_read_an_internal_event_by_id(self):
        """Even addressed directly, an internal event stays out of reach."""
        internal = self.Event.create({
            "shipment_id": self.shipment.id, "status": "preparing",
            "description": "INTERNAL by id", "visible_to_customer": False,
        })
        with self.assertRaises(AccessError):
            internal.with_user(self.api_user).read(["description"])

    def test_payload_built_as_api_user_is_clean(self):
        """End to end, with the rights the endpoint actually runs under."""
        import json
        self.Event.create({
            "shipment_id": self.shipment.id, "status": "departed",
            "description": "Public departure", "visible_to_customer": True,
        })
        self.Event.create({
            "shipment_id": self.shipment.id, "status": "preparing",
            "description": "INTERNAL-CANARY", "visible_to_customer": False,
        })

        payload = self.shipment.with_user(self.api_user)._dally_public_payload()
        serialised = json.dumps(payload)

        self.assertNotIn("INTERNAL-CANARY", serialised)
        self.assertNotIn("LEAK-CANARY", serialised)
        self.assertNotIn("4242", serialised)
        self.assertNotIn("Rights Customer", serialised)
        self.assertIn("Public departure", serialised)
