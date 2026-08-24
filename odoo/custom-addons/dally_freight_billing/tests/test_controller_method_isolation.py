# -*- coding: utf-8 -*-
"""Regression coverage for Odoo HTTP controller method-name collisions."""

import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestControllerMethodIsolation(HttpCase):
    """Loading Freight Billing must not change the public quote validator."""

    def setUp(self):
        super().setUp()
        self.key = self.env["dally.api.key"].create({
            "name": "Controller isolation quote key",
            "scopes": "quotes:write",
            "allowed_ips": "",
        })
        self.raw_key = self.key.key_to_display

    def test_quote_payload_does_not_use_freight_sync_cleaner(self):
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "service_code": "freight_sea",
            "first_name": "Awa",
            "last_name": "Diallo",
            "email": "controller-isolation-%s@example.com" % uuid.uuid4().hex[:8],
            "phone": "+221 77 555 44 33",
            "origin_city": "Le Havre",
            "origin_country_code": "FR",
            "destination_city": "Dakar",
            "destination_country_code": "SN",
            "goods_description": "Textile",
            "weight_kg": 480,
        }
        response = self.url_open(
            "/api/v1/quotes",
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self.raw_key,
            },
            timeout=30,
        )

        self.assertEqual(
            response.status_code,
            201,
            response.text,
        )
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["service"], "freight_sea")
