# -*- coding: utf-8 -*-
import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestOpenConsolidationsEndpoint(HttpCase):

    def setUp(self):
        super().setUp()
        self.sync_user = self.env.ref("dally_freight_billing.user_dally_freight_sync_integration")
        self.key = self.env["dally.api.key"].create({
            "name": "Open Consolidations Test Key",
            "scopes": "freight:write",
            "allowed_ips": "",
            "user_id": self.sync_user.id,
        })
        self.consolidation = self.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-2099-HTTP",
            "transport_mode": "air", "direction": "export", "state": "collecting",
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_city": "Paris", "destination_location": "CDG",
        })

    def test_bodyless_get_returns_open_rows(self):
        response = self.url_open(
            "/api/v1/freight/consolidations/open",
            headers={"X-API-Key": self.key.key_to_display},
            timeout=30,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]["consolidations"]
        self.assertIn(self.consolidation.name, [row["name"] for row in data])
        self.assertNotIn("client", json.dumps(data))

    def test_bodyless_get_without_key_is_unauthorized(self):
        response = self.url_open("/api/v1/freight/consolidations/open", timeout=30)
        self.assertEqual(response.status_code, 401)
