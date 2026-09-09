# -*- coding: utf-8 -*-
"""Flux HTTP reels des ecrans d'authentification DallyTrading."""

from urllib.parse import urlencode

from lxml import html

from odoo.tests import HttpCase, tagged

from ..controllers.main import normalized_host


CRM_HOST = "crm.dallytrading.com"
TEST_LOGIN = "branding.staff@test.invalid"
TEST_PASSWORD = "BrandingTest!2026"


@tagged("post_install", "-at_install", "dally", "dally_web_branding")
class TestDallyWebBranding(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        parameters = cls.env["ir.config_parameter"].sudo()
        parameters.set_param("auth_signup.invitation_scope", "b2c")
        parameters.set_param("auth_signup.reset_password", "True")
        cls.env["website"].search([], limit=1).write({
            "auth_signup_uninvited": "b2c",
        })
        cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Branding Staff",
            "login": TEST_LOGIN,
            "password": TEST_PASSWORD,
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })

    @staticmethod
    def _document(response):
        return html.fromstring(response.content)

    def _get_login(self, path="/web/login", host=CRM_HOST):
        return self.url_open(path, headers={"Host": host})

    def _csrf_token(self, host=CRM_HOST):
        document = self._document(self._get_login(host=host))
        tokens = document.xpath(
            "//form[contains(concat(' ', normalize-space(@class), ' '), "
            "' oe_login_form ')]//input[@name='csrf_token']/@value"
        )
        self.assertEqual(len(tokens), 1)
        self.assertTrue(tokens[0])
        return tokens[0]

    def _post_login(self, login, password, allow_redirects=False):
        data = urlencode({
            "csrf_token": self._csrf_token(),
            "login": login,
            "password": password,
            "type": "password",
            "redirect": "",
        })
        return self.url_open(
            "/web/login",
            data=data,
            headers={
                "Host": CRM_HOST,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            allow_redirects=allow_redirects,
        )

    def test_crm_root_redirects_to_native_login(self):
        for host in (CRM_HOST, "CRM.DALLYTRADING.COM:443", f"{CRM_HOST}."):
            with self.subTest(host=host):
                response = self.url_open(
                    "/", headers={"Host": host}, allow_redirects=False
                )
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers.get("Location"), "/web/login")

    def test_host_normalization_is_strict(self):
        self.assertEqual(normalized_host(CRM_HOST), CRM_HOST)
        self.assertEqual(normalized_host("CRM.DALLYTRADING.COM:443"), CRM_HOST)
        self.assertEqual(normalized_host(f"{CRM_HOST}."), CRM_HOST)
        self.assertEqual(normalized_host(f"user@{CRM_HOST}"), "")
        self.assertEqual(normalized_host(f"{CRM_HOST}:invalid"), "")

    def test_other_host_keeps_website_homepage(self):
        response = self.url_open(
            "/", headers={"Host": "www.dallytrading.com"}, allow_redirects=False
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.headers.get("Location"), "/web/login")
        self.assertNotIn(b"dally-auth-shell", response.content)

    def test_post_root_is_never_redirected_by_branding_controller(self):
        response = self.url_open(
            "/",
            data="probe=1",
            headers={
                "Host": CRM_HOST,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            allow_redirects=False,
        )
        self.assertNotEqual(response.headers.get("Location"), "/web/login")

    def test_login_page_keeps_native_form_and_csrf(self):
        response = self._get_login()
        self.assertEqual(response.status_code, 200)
        document = self._document(response)
        self.assertEqual(document.xpath("string(//title)"), "DallyTrading CRM")
        self.assertEqual(document.xpath("count(//body[contains(@class, 'dally-auth-page')])"), 1.0)
        self.assertEqual(document.xpath("count(//form[contains(@class, 'oe_login_form')])"), 1.0)
        self.assertEqual(document.xpath("count(//input[@name='csrf_token' and @value])"), 1.0)
        self.assertEqual(document.xpath("count(//input[@name='login'])"), 1.0)
        self.assertEqual(document.xpath("count(//input[@name='password'])"), 1.0)
        self.assertEqual(document.xpath("count(//input[@name='redirect'])"), 1.0)
        self.assertEqual(document.xpath("count(//input[@name='webauthn_response'])"), 1.0)
        self.assertEqual(
            document.xpath(
                "count(//img[@src='/dally_web_branding/static/src/img/"
                "dallytrading-logo.png'])"
            ),
            1.0,
        )
        self.assertEqual(
            document.xpath(
                "count(//link[@rel='icon' and contains(@href, 'favicon-32.png')])"
            ),
            1.0,
        )
        self.assertEqual(document.xpath("count(//header | //footer)"), 0.0)
        self.assertNotIn(b"Powered by", response.content)
        self.assertNotIn(b"odoo_logo_tiny", response.content)

    def test_reset_signup_and_passkey_remain_available(self):
        login = self._document(self._get_login())
        self.assertEqual(login.xpath("count(//a[starts-with(@href, '/web/reset_password')])"), 1.0)
        self.assertEqual(login.xpath("count(//a[starts-with(@href, '/web/signup')])"), 1.0)
        self.assertEqual(login.xpath("count(//a[contains(@class, 'passkey_login_link')])"), 1.0)

        reset = self._document(self._get_login("/web/reset_password"))
        signup = self._document(self._get_login("/web/signup"))
        self.assertEqual(reset.xpath("count(//body[contains(@class, 'dally-auth-page')])"), 1.0)
        self.assertEqual(reset.xpath("count(//form[contains(@class, 'oe_reset_password_form')])"), 1.0)
        self.assertEqual(signup.xpath("count(//body[contains(@class, 'dally-auth-page')])"), 1.0)
        self.assertEqual(signup.xpath("count(//form[contains(@class, 'oe_signup_form')])"), 1.0)

    def test_invalid_login_keeps_visible_error_in_branded_layout(self):
        response = self._post_login("invalid@test.invalid", "wrong-password")
        self.assertEqual(response.status_code, 200)
        document = self._document(response)
        alerts = document.xpath(
            "//p[contains(concat(' ', normalize-space(@class), ' '), "
            "' alert-danger ') and normalize-space()]"
        )
        self.assertEqual(len(alerts), 1)
        self.assertEqual(document.xpath("count(//div[contains(@class, 'dally-auth-shell')])"), 1.0)

    def test_valid_login_opens_backend_without_branding_shell(self):
        response = self._post_login(TEST_LOGIN, TEST_PASSWORD)
        self.assertEqual(response.status_code, 303)
        self.assertRegex(response.headers.get("Location", ""), r"^/(odoo|web)")

        backend = self.url_open("/odoo", headers={"Host": CRM_HOST})
        self.assertEqual(backend.status_code, 200)
        self.assertIn(b"o_web_client", backend.content)
        self.assertNotIn(b"dally-auth-shell", backend.content)
        self.assertNotIn(b"dally-auth-page", backend.content)

    def test_logout_returns_to_branded_login(self):
        self.assertEqual(
            self._post_login(TEST_LOGIN, TEST_PASSWORD).status_code, 303
        )
        logout = self.url_open(
            "/web/session/logout?redirect=/web/login",
            headers={"Host": CRM_HOST},
            allow_redirects=False,
        )
        self.assertEqual(logout.status_code, 303)
        self.assertEqual(logout.headers.get("Location"), "/web/login")

        login = self._get_login()
        self.assertIn(b"dally-auth-shell", login.content)
        self.assertIn(b"oe_login_form", login.content)

    def test_debug_assets_keeps_complete_login_page(self):
        response = self._get_login("/web/login?debug=assets")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"DallyTrading CRM", response.content)
        self.assertIn(b"dally-auth-shell", response.content)
        self.assertIn(b"oe_login_form", response.content)
        self.assertIn(b"csrf_token", response.content)
        self.assertIn(b"/debug/web.assets_frontend", response.content)
