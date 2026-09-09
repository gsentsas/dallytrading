# -*- coding: utf-8 -*-
"""Regression tests for internal-user invitation and reset links."""

from lxml import html

from odoo.tests import TransactionCase, tagged


CRM_BASE_URL = "https://crm.dallytrading.com"
PUBLIC_BASE_URL = "https://www.dallytrading.com"


@tagged("post_install", "-at_install", "dally", "dally_web_branding")
class TestInternalInvitationUrls(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "dally.crm.base_url", CRM_BASE_URL
        )
        website = cls.env["website"].search([], limit=1)
        website.write({"domain": PUBLIC_BASE_URL})

        cls.internal_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create({
            "name": "Internal Invitation Test",
            "login": "internal.invite@test.invalid",
            "email": "internal.invite@test.invalid",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.internal_user.partner_id.write({"company_id": cls.env.company.id})
        cls.internal_user.partner_id.signup_prepare("signup")

        cls.public_partner = cls.env["res.partner"].create({
            "name": "Public Partner Test",
            "company_id": cls.env.company.id,
        })

        cls.portal_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create({
            "name": "Portal Invitation Sentinel",
            "login": "portal.invite@test.invalid",
            "email": "portal.invite@test.invalid",
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
        })
        cls.portal_user.partner_id.write({"company_id": cls.env.company.id})

    def test_internal_user_and_partner_use_crm_base(self):
        self.assertEqual(self.internal_user.get_base_url(), CRM_BASE_URL)
        self.assertEqual(self.internal_user.partner_id.get_base_url(), CRM_BASE_URL)

    def test_internal_invitation_template_uses_crm_for_web_links(self):
        template = self.env.ref("auth_signup.set_password_email").sudo()
        body = template._render_field(
            "body_html", [self.internal_user.id], compute_lang=True
        )[self.internal_user.id]
        document = html.fromstring(body)
        hrefs = document.xpath("//a/@href")
        web_links = [href for href in hrefs if "/web/" in href]

        self.assertTrue(web_links)
        self.assertTrue(all(href.startswith(CRM_BASE_URL) for href in web_links))
        self.assertIn(CRM_BASE_URL, hrefs)
        self.assertNotIn(f"{PUBLIC_BASE_URL}/web/login", hrefs)

    def test_public_and_portal_bases_are_not_forced_to_crm(self):
        self.assertEqual(self.public_partner.get_base_url(), PUBLIC_BASE_URL)
        self.assertEqual(self.portal_user.get_base_url(), PUBLIC_BASE_URL)
        self.assertEqual(self.portal_user.partner_id.get_base_url(), PUBLIC_BASE_URL)
