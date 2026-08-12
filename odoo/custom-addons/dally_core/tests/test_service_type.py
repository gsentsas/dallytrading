# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from psycopg2 import IntegrityError
from odoo.tools import mute_logger


@tagged("post_install", "-at_install", "dally")
class TestDallyServiceType(TransactionCase):
    """The service catalogue is the contract between the website and Odoo.

    Its codes end up in URLs and stored payloads, so the guarantees tested here
    (uniqueness, format, resolvability of archived entries) are what keep old
    records readable.
    """

    def setUp(self):
        super().setUp()
        self.ServiceType = self.env["dally.service.type"]

    def test_seeded_services_are_present(self):
        """The activities listed in the specification must ship with the module."""
        expected_codes = {
            "import_export", "logistics", "freight_sea", "freight_air",
            "freight_vehicle", "freight_groupage", "trade", "sourcing",
            "ecommerce", "agrobusiness", "business_solutions", "other",
        }
        found = set(self.ServiceType.search([]).mapped("code"))
        self.assertTrue(
            expected_codes.issubset(found),
            "Missing seeded service codes: %s" % (expected_codes - found),
        )

    def test_code_must_be_unique(self):
        """Two services sharing a code would make routing ambiguous."""
        self.ServiceType.create({
            "name": "Test Service",
            "code": "test_unique_code",
            "category": "other",
        })
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.ServiceType.create({
                "name": "Another Service",
                "code": "test_unique_code",
                "category": "other",
            })
            self.env.flush_all()

    def test_code_rejects_uppercase(self):
        with self.assertRaises(ValidationError):
            self.ServiceType.create({
                "name": "Bad Code",
                "code": "Freight_Sea",
                "category": "freight",
            })

    def test_code_rejects_special_characters(self):
        """Codes travel in URLs and JSON: no spaces, dashes or punctuation."""
        for bad_code in ("freight sea", "freight-sea", "freight/sea", "fret!"):
            with self.subTest(code=bad_code), self.assertRaises(ValidationError):
                self.ServiceType.create({
                    "name": "Bad Code",
                    "code": bad_code,
                    "category": "freight",
                })

    def test_code_accepts_valid_format(self):
        service = self.ServiceType.create({
            "name": "Valid",
            "code": "valid_code_123",
            "category": "other",
        })
        self.assertEqual(service.code, "valid_code_123")

    def test_get_by_code_resolves_known_service(self):
        service = self.ServiceType._get_by_code("freight_sea")
        self.assertTrue(service, "freight_sea should resolve")
        self.assertEqual(service.code, "freight_sea")

    def test_get_by_code_returns_empty_for_unknown(self):
        """Unknown codes must not raise: the API turns this into a 422."""
        self.assertFalse(self.ServiceType._get_by_code("does_not_exist"))
        self.assertFalse(self.ServiceType._get_by_code(False))
        self.assertFalse(self.ServiceType._get_by_code(""))

    def test_get_by_code_still_resolves_archived_service(self):
        """A lead created last year points at a service since withdrawn.

        If archiving broke resolution, historical records would fail to load.
        """
        service = self.ServiceType.create({
            "name": "Withdrawn Service",
            "code": "withdrawn_service",
            "category": "other",
        })
        service.active = False
        self.assertFalse(
            self.ServiceType.search([("code", "=", "withdrawn_service")]),
            "A plain search must not see archived records",
        )
        self.assertEqual(
            self.ServiceType._get_by_code("withdrawn_service"),
            service,
            "_get_by_code must still resolve archived services",
        )
