# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_crm.models.res_partner import normalize_phone


@tagged("post_install", "-at_install", "dally")
class TestPhoneNormalization(TransactionCase):
    """Phone matching decides whether a returning customer is recognised.

    Too loose and two customers get merged; too strict and the CRM fills with
    duplicates. These cases pin the boundary.
    """

    def test_strips_formatting(self):
        for value in (
            "+221 77 123 45 67",
            "00221771234567",
            "221771234567",
            "77 123 45 67",
            "77-123-45-67",
            "(77) 123.45.67",
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_phone(value), "771234567")

    def test_returns_none_when_too_short(self):
        """A fragment must never be matched on: "77" would match half the base."""
        for value in ("77", "1234", "12345678", "", None, "abc"):
            with self.subTest(value=value):
                self.assertIsNone(normalize_phone(value))

    def test_distinct_numbers_stay_distinct(self):
        self.assertNotEqual(
            normalize_phone("+221 77 123 45 67"),
            normalize_phone("+221 78 123 45 67"),
        )


@tagged("post_install", "-at_install", "dally")
class TestPartnerDeduplication(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Partner = self.env["res.partner"]

    def test_matches_on_email_case_insensitively(self):
        partner = self.Partner.create({
            "name": "Aminata Diop",
            "email": "Aminata.Diop@example.com",
        })
        self.assertEqual(
            self.Partner._dally_find_existing(email="aminata.diop@example.com"),
            partner,
        )

    def test_matches_on_email_with_surrounding_spaces(self):
        partner = self.Partner.create({
            "name": "Test Contact",
            "email": "spaced@example.com",
        })
        self.assertEqual(
            self.Partner._dally_find_existing(email="  spaced@example.com  "),
            partner,
        )

    def test_matches_on_phone_across_formats(self):
        partner = self.Partner.create({
            "name": "Moussa Fall",
            "phone": "+221 77 987 65 43",
        })
        self.assertEqual(
            self.Partner._dally_find_existing(phone="00221779876543"),
            partner,
            "The same number written differently must match",
        )

    def test_matches_when_whatsapp_hits_stored_phone(self):
        """Customers do not distinguish phone from WhatsApp; matching must not either."""
        partner = self.Partner.create({
            "name": "Fatou Sow",
            "phone": "+221 76 111 22 33",
        })
        self.assertEqual(
            self.Partner._dally_find_existing(whatsapp="76 111 22 33"),
            partner,
        )

    def test_matches_on_stored_whatsapp_field(self):
        partner = self.Partner.create({
            "name": "Ibrahima Ba",
            "dally_whatsapp": "+221 70 555 44 33",
        })
        self.assertEqual(
            self.Partner._dally_find_existing(phone="705554433"),
            partner,
        )

    def test_email_wins_over_phone(self):
        """Email is the more reliable signal and must be tried first."""
        by_email = self.Partner.create({
            "name": "By Email",
            "email": "priority@example.com",
        })
        self.Partner.create({
            "name": "By Phone",
            "phone": "+221 77 000 11 22",
        })
        self.assertEqual(
            self.Partner._dally_find_existing(
                email="priority@example.com", phone="770001122"
            ),
            by_email,
        )

    def test_matches_company_by_exact_name(self):
        company = self.Partner.create({
            "name": "Sahel Logistics SARL",
            "is_company": True,
        })
        self.assertEqual(
            self.Partner._dally_find_existing(company_name="sahel logistics sarl"),
            company,
        )

    def test_does_not_match_individual_on_company_name(self):
        """Only companies are matched by name — homonyms among people are common."""
        self.Partner.create({"name": "Unique Person Name", "is_company": False})
        self.assertFalse(
            self.Partner._dally_find_existing(company_name="Unique Person Name")
        )

    def test_ignores_very_short_company_name(self):
        self.Partner.create({"name": "AB", "is_company": True})
        self.assertFalse(self.Partner._dally_find_existing(company_name="AB"))

    def test_returns_empty_when_nothing_matches(self):
        result = self.Partner._dally_find_existing(
            email="nobody-here@example.com",
            phone="+221 33 999 88 77",
            company_name="No Such Company Ltd",
        )
        self.assertFalse(result)
        self.assertEqual(
            result._name, "res.partner",
            "Must return an empty recordset, not None, so callers can chain",
        )

    def test_returns_empty_on_no_criteria(self):
        self.assertFalse(self.Partner._dally_find_existing())

    def test_never_modifies_the_matched_partner(self):
        """Deduplication links; it must not edit existing customer data (§28)."""
        partner = self.Partner.create({
            "name": "Original Name",
            "email": "original@example.com",
            "phone": "+221 77 444 55 66",
        })
        self.Partner._dally_find_existing(
            email="original@example.com",
            phone="+221 78 000 00 00",
            company_name="Some Other Company",
        )
        self.assertEqual(partner.name, "Original Name")
        self.assertEqual(partner.phone, "+221 77 444 55 66")
