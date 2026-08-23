# -*- coding: utf-8 -*-
"""Regression: notification snapshots must not widen tracking-link access."""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestTrackingLinkSnapshot(TransactionCase):

    def setUp(self):
        super().setUp()
        self.client = self.env["res.partner"].create({
            "name": "Client snapshot suivi",
            "email": "snapshot@example.invalid",
        })
        self.service = self.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1
        )
        self.shipment = self.env["dally.shipment"].create({
            "partner_id": self.client.id,
            "service_type_id": self.service.id,
            "transport_mode": "sea",
        })
        self.tracking_user = self.env.ref("dally_tracking.user_dally_api_tracking")

    def test_restricted_api_user_can_enqueue_without_reading_tracking_link(self):
        event = self.env["dally.shipment.event"].create({
            "shipment_id": self.shipment.id,
            "status": "in_transit",
            "description": "Evénement de régression",
            "visible_to_customer": True,
            "is_automatic": False,
        })

        with self.assertRaises(AccessError):
            self.shipment.with_user(self.tracking_user).read(["public_tracking_url"])

        event.with_user(self.tracking_user)._dally_enqueue_notification()

        notification = self.env["dally.shipment.notification"].sudo().search([
            ("event_id", "=", event.id),
        ], limit=1)
        self.assertTrue(notification)
        self.assertIn("/tracking?ref=", notification.tracking_url)
