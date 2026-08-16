# -*- coding: utf-8 -*-
"""Première mutation portail : profil, et fermeture des chemins concurrents."""

import json

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged


PORTAL_PASSWORD = "PortalProfileTest!2026"


class ProfileFixture:

    @classmethod
    def _profile_users(cls):
        Partner = cls.env["res.partner"]
        Users = cls.env["res.users"]
        portal_group = cls.env.ref("base.group_portal")
        internal_group = cls.env.ref("base.group_user")
        contact_manager_group = cls.env.ref("base.group_partner_manager")

        cls.company_a = Partner.create({
            "name": "PROFILE Société A", "is_company": True,
        })
        cls.company_b = Partner.create({
            "name": "PROFILE Société B", "is_company": True,
        })
        cls.contact_a = Partner.create({
            "name": "PROFILE Contact A",
            "parent_id": cls.company_a.id,
            "email": "profile.a@portal-test.invalid",
            "phone": "+221 70 000 00 01",
            "street": "Rue A",
            "zip": "10000",
            "city": "Dakar",
        })
        cls.contact_b = Partner.create({
            "name": "PROFILE Contact B",
            "parent_id": cls.company_b.id,
            "email": "profile.b@portal-test.invalid",
            "phone": "+221 70 000 00 02",
            "city": "Thiès",
        })
        cls.login_a = "profile.a@portal-test.invalid"
        cls.login_b = "profile.b@portal-test.invalid"
        cls.user_a = Users.create({
            "name": cls.contact_a.name,
            "login": cls.login_a,
            "password": PORTAL_PASSWORD,
            "partner_id": cls.contact_a.id,
            "group_ids": [(6, 0, [portal_group.id])],
        })
        cls.user_b = Users.create({
            "name": cls.contact_b.name,
            "login": cls.login_b,
            "password": PORTAL_PASSWORD,
            "partner_id": cls.contact_b.id,
            "group_ids": [(6, 0, [portal_group.id])],
        })
        cls.login_staff = "profile.staff@portal-test.invalid"
        cls.staff = Users.create({
            "name": "PROFILE Staff",
            "login": cls.login_staff,
            "password": PORTAL_PASSWORD,
            "group_ids": [(6, 0, [
                internal_group.id, contact_manager_group.id,
            ])],
        })


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestPortalProfileOrm(ProfileFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._profile_users()

    def test_dedicated_method_updates_only_authenticated_contact(self):
        company_name = self.company_a.name
        changed = self.contact_a.with_user(
            self.user_a,
        )._dally_portal_update_profile({
            "name": "  PROFILE Contact A modifié  ",
            "phone": "  +221 77 123 45 67  ",
            "street": "  Rue synthétique 42  ",
            "street2": "",
            "zip": "  11000  ",
            "city": "  Dakar Plateau  ",
        })
        self.assertEqual(
            set(changed), {"name", "phone", "street", "street2", "zip", "city"},
        )
        self.assertEqual(self.contact_a.name, "PROFILE Contact A modifié")
        self.assertEqual(self.contact_a.phone, "+221 77 123 45 67")
        self.assertFalse(self.contact_a.street2)
        self.assertEqual(self.company_a.name, company_name)
        self.assertEqual(self.contact_a.email, "profile.a@portal-test.invalid")

    def test_unknown_key_rejects_the_entire_payload(self):
        before = self.contact_a.phone
        with self.assertRaises(ValidationError):
            self.contact_a.with_user(
                self.user_a,
            )._dally_portal_update_profile({
                "phone": "+221 77 999 99 99",
                "company_id": self.env.company.id,
                "group_ids": [self.env.ref("base.group_user").id],
                "parent_id": self.company_b.id,
                "credit_limit": 999999,
            })
        self.assertEqual(self.contact_a.phone, before)

    def test_invalid_values_are_rejected(self):
        invalid = (
            {},
            {"name": "   "},
            {"name": "x" * 121},
            {"phone": "call-me<script>"},
            {"street": "<b>Rue</b>"},
            {"city": "Dakar\nInjected"},
            {"zip": 10000},
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                self.contact_a.with_user(
                    self.user_a,
                )._dally_portal_update_profile(payload)

    def test_portal_b_cannot_update_a(self):
        with self.assertRaises(AccessError):
            self.contact_a.with_user(
                self.user_b,
            )._dally_portal_update_profile({"phone": "+221 77 000 00 00"})

    def test_staff_cannot_use_portal_profile_method(self):
        with self.assertRaises(AccessError):
            self.staff.partner_id.with_user(
                self.staff,
            )._dally_portal_update_profile({"phone": "+221 77 000 00 00"})

    def test_native_partner_write_access_remains_denied(self):
        with self.assertRaises(AccessError):
            self.contact_a.with_user(self.user_a).check_access("write")

    def test_generic_write_is_refused_on_own_contact_and_both_companies(self):
        for target in (self.contact_a, self.company_a, self.company_b):
            with self.subTest(target=target.name), self.assertRaises(AccessError):
                target.with_user(self.user_a).write({
                    "phone": "+221 77 111 11 11",
                })

    def test_internal_staff_write_is_not_regressed(self):
        self.contact_a.with_user(self.staff).write({"city": "Dakar Staff"})
        self.assertEqual(self.contact_a.city, "Dakar Staff")


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestPortalProfileHttp(ProfileFixture, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._profile_users()

    def _patch(self, payload, headers=None):
        return self.url_open(
            "/api/v1/portal/profile",
            json=payload,
            method="PATCH",
            headers={
                "Content-Type": "application/json",
                "X-Request-ID": "profile-http-test",
                **(headers or {}),
            },
            allow_redirects=False,
        )

    def _call_kw(self, model, method, args, kwargs=None):
        return self.url_open(
            "/web/dataset/call_kw",
            data=json.dumps({
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "model": model,
                    "method": method,
                    "args": args,
                    "kwargs": kwargs or {},
                },
            }),
            headers={"Content-Type": "application/json"},
        )

    def test_valid_profile_update_returns_confirmed_projection(self):
        self.authenticate(self.login_a, PORTAL_PASSWORD)
        company_name = self.company_a.name
        response = self._patch({
            "phone": "+221 77 222 33 44",
            "street": "42 rue E2E",
            "street2": "Étage 2",
            "zip": "11000",
            "city": "Dakar Plateau",
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["phone"], "+221 77 222 33 44")
        self.assertEqual(data["street"], "42 rue E2E")
        self.assertEqual(data["city"], "Dakar Plateau")
        self.assertEqual(data["email"], self.contact_a.email)
        self.assertEqual(data["company"], company_name)
        self.assertEqual(self.company_a.name, company_name)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_empty_payload_is_explicitly_rejected(self):
        self.authenticate(self.login_a, PORTAL_PASSWORD)
        response = self._patch({})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    def test_unknown_and_mass_assignment_keys_are_rejected(self):
        self.authenticate(self.login_a, PORTAL_PASSWORD)
        for payload in (
            {"partner_id": self.contact_b.id},
            {"phone": "+221 77 999 99 99", "company_id": self.env.company.id},
            {"groups_id": [self.env.ref("base.group_user").id]},
            {"parent_id": self.company_b.id},
            {"credit_limit": 500000},
        ):
            with self.subTest(payload=payload):
                response = self._patch(payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json()["error"]["code"], "invalid_request",
                )

    def test_too_long_and_non_text_values_are_rejected(self):
        self.authenticate(self.login_a, PORTAL_PASSWORD)
        for payload in ({"city": "x" * 129}, {"zip": 12345}):
            with self.subTest(payload=payload):
                self.assertEqual(self._patch(payload).status_code, 400)

    def test_staff_is_refused(self):
        self.authenticate(self.login_staff, PORTAL_PASSWORD)
        response = self._patch({"phone": "+221 77 000 00 00"})
        self.assertEqual(response.status_code, 403)

    def test_no_session_and_forged_session_are_refused(self):
        self.authenticate(None, None)
        self.assertNotEqual(
            self._patch({"phone": "+221 77 000 00 00"}).status_code, 200,
        )
        self.opener.cookies["session_id"] = "0" * 40
        self.assertNotEqual(
            self._patch({"phone": "+221 77 000 00 00"}).status_code, 200,
        )

    def test_generic_rpc_write_is_refused_everywhere(self):
        self.authenticate(self.login_a, PORTAL_PASSWORD)
        for target in (self.contact_a, self.company_a, self.company_b):
            with self.subTest(target=target.name):
                body = self._call_kw(
                    "res.partner", "write",
                    [[target.id], {"phone": "+221 77 555 55 55"}],
                ).json()
                self.assertIn(
                    "error", body,
                    f"res.partner.write générique autorisé sur {target.name}",
                )

    def test_private_profile_method_is_not_rpc_callable(self):
        self.authenticate(self.login_a, PORTAL_PASSWORD)
        body = self._call_kw(
            "res.partner",
            "_dally_portal_update_profile",
            [[self.contact_a.id], {"phone": "+221 77 555 55 55"}],
        ).json()
        self.assertIn("error", body)

    def test_portal_b_update_does_not_change_a(self):
        self.authenticate(self.login_b, PORTAL_PASSWORD)
        before = self.contact_a.phone
        response = self._patch({"phone": "+221 77 888 88 88"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.contact_a.phone, before)
        self.assertEqual(self.contact_b.phone, "+221 77 888 88 88")
