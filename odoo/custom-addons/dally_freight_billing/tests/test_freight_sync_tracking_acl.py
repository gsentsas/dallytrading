# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightSyncTrackingAcl(TransactionCase):

    def setUp(self):
        super().setUp()
        self.sync_user = self.env.ref(
            "dally_freight_billing.user_dally_freight_sync_integration"
        )
        self.partner = self.env["res.partner"].with_user(self.sync_user).create({
            "name": "Freight Sync Tracking ACL",
        })
        self.shipment = self.env["dally.shipment"].with_user(self.sync_user).create({
            "partner_id": self.partner.id,
            "external_reference": "SYNC-TRACKING-ACL",
            "transport_mode": "air",
            "direction": "export",
        })
        self.shipment._write_state_from_operational_source("request_received")

    def test_sync_user_can_create_automatic_event_on_state_change(self):
        self.shipment.with_user(self.sync_user)._write_state_from_operational_source(
            "goods_received"
        )

        event = self.env["dally.shipment.event"].sudo().search([
            ("shipment_id", "=", self.shipment.id),
            ("status", "=", "goods_received"),
            ("is_automatic", "=", True),
        ], limit=1)

        self.assertTrue(event)
        self.assertTrue(event.visible_to_customer)
