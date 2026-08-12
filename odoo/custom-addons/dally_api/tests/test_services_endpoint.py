# -*- coding: utf-8 -*-
"""HTTP tests for GET /api/v1/services."""

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestServicesEndpoint(HttpCase):

    ENDPOINT = "/api/v1/services"

    def setUp(self):
        super().setUp()
        self.ServiceType = self.env["dally.service.type"]
        self.key = self.env["dally.api.key"].create({
            "name": "Catalogue test key",
            "scopes": "services:read",
            "allowed_ips": "",
        })
        self.raw_key = self.key.key_to_display

    def _get(self, api_key=None):
        headers = {}
        key = self.raw_key if api_key is None else api_key
        if key:
            headers["X-API-Key"] = key
        return self.url_open(self.ENDPOINT, headers=headers, timeout=30)

    # ─── Permission and scope ─────────────────────────────────────────

    def test_requires_an_api_key(self):
        response = self._get(api_key=False)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "missing_api_key")

    def test_rejects_an_invalid_key(self):
        self.assertEqual(self._get(api_key="wrong").status_code, 401)

    def test_rejects_a_key_without_the_scope(self):
        other = self.env["dally.api.key"].create({
            "name": "Leads only", "scopes": "leads:write", "allowed_ips": "",
        })
        response = self._get(api_key=other.key_to_display)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "insufficient_scope")

    # ─── Payload ──────────────────────────────────────────────────────

    def test_returns_the_catalogue(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)

        services = response.json()["data"]["services"]
        self.assertGreater(len(services), 5)

        codes = {service["code"] for service in services}
        self.assertIn("freight_sea", codes)
        self.assertIn("freight_air", codes)
        self.assertIn("sourcing", codes)

    def test_each_entry_carries_the_contract_keys(self):
        expected = {
            "code", "name", "description", "active", "sort_order",
            "requires_origin", "requires_destination", "requires_weight",
            "requires_volume", "requires_vehicle", "requires_budget",
            "requires_goods",
        }
        for service in self._get().json()["data"]["services"]:
            self.assertEqual(set(service), expected, service.get("code"))

    def test_entries_expose_no_internal_field(self):
        body = self._get().text
        for internal in ('"id"', '"category"', '"published"', '"create_uid"'):
            self.assertNotIn(internal, body)

    def test_entries_are_ordered_by_sort_order(self):
        services = self._get().json()["data"]["services"]
        orders = [service["sort_order"] for service in services]
        self.assertEqual(orders, sorted(orders))

    # ─── Active / inactive ────────────────────────────────────────────

    def test_archived_service_is_absent(self):
        service = self.ServiceType.create({
            "name": "Temporary", "code": "temporary_service", "category": "other",
        })
        self.assertIn(
            "temporary_service",
            {s["code"] for s in self._get().json()["data"]["services"]},
        )

        service.active = False
        self.assertNotIn(
            "temporary_service",
            {s["code"] for s in self._get().json()["data"]["services"]},
        )

    def test_unpublished_service_is_absent(self):
        self.ServiceType.create({
            "name": "Internal", "code": "internal_service",
            "category": "other", "published": False,
        })
        self.assertNotIn(
            "internal_service",
            {s["code"] for s in self._get().json()["data"]["services"]},
        )

    # ─── Caching ──────────────────────────────────────────────────────

    def test_response_is_cacheable(self):
        """The one endpoint here that may be cached: identical for every caller."""
        cache_control = self._get().headers.get("Cache-Control", "")
        self.assertIn("max-age", cache_control)
        self.assertNotIn("no-store", cache_control)

    def test_other_endpoints_remain_uncacheable(self):
        """Guard against the cacheable header leaking to per-customer responses."""
        response = self.url_open(
            "/api/v1/health",
            headers={"X-API-Key": self.env["dally.api.key"].create({
                "name": "Health", "scopes": "customers:read", "allowed_ips": "",
            }).key_to_display},
            timeout=30,
        )
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
