# -*- coding: utf-8 -*-
"""Régression : les photos Ops restent privées mais deviennent visibles au CRM."""

import uuid

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally", "dally_ops_mobile")
class TestOpsPhotoCRM(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env["res.company"].create({"name": "CRM Photo Autre"})
        cls.partner = cls.env["res.partner"].create({
            "name": "Client photo CRM",
            "company_id": cls.company.id,
        })
        cls.shipment = cls.env["dally.shipment"].create({
            "partner_id": cls.partner.id,
            "company_id": cls.company.id,
            "external_reference": "OPS-PHOTO-CRM-001",
            "transport_mode": "air",
            "direction": "export",
        })
        cls.attachment = cls.env["ir.attachment"].sudo().create({
            "name": "produit.jpg",
            "raw": b"photo-crm-test",
            "mimetype": "image/jpeg",
            "res_model": "dally.ops.photo",
            "res_id": 0,
            "company_id": cls.company.id,
            "public": False,
        })
        cls.photo = cls.env["dally.ops.photo"].sudo().create({
            "photo_uuid": str(uuid.uuid4()),
            "company_id": cls.company.id,
            "shipment_id": cls.shipment.id,
            "attachment_id": cls.attachment.id,
            "kind": "reception",
            "operator_user_id": cls.env.user.id,
        })
        cls.attachment.write({"res_id": cls.photo.id})

        cls.other_partner = cls.env["res.partner"].sudo().create({
            "name": "Client photo autre société",
            "company_id": cls.other_company.id,
        })
        cls.other_shipment = cls.env["dally.shipment"].sudo().create({
            "partner_id": cls.other_partner.id,
            "company_id": cls.other_company.id,
            "external_reference": "OPS-PHOTO-CRM-OTHER",
            "transport_mode": "air",
            "direction": "export",
        })
        cls.other_attachment = cls.env["ir.attachment"].sudo().create({
            "name": "autre.jpg",
            "raw": b"other-company-photo",
            "mimetype": "image/jpeg",
            "res_model": "dally.ops.photo",
            "res_id": 0,
            "company_id": cls.other_company.id,
            "public": False,
        })
        cls.other_photo = cls.env["dally.ops.photo"].sudo().create({
            "photo_uuid": str(uuid.uuid4()),
            "company_id": cls.other_company.id,
            "shipment_id": cls.other_shipment.id,
            "attachment_id": cls.other_attachment.id,
            "kind": "reception",
            "operator_user_id": cls.env.user.id,
        })
        cls.other_attachment.write({"res_id": cls.other_photo.id})

        cls.crm_user = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "CRM Photo Reader",
                "login": "crm.photo.reader@test.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("dally_core.group_dally_readonly").id])],
                "company_id": cls.company.id,
                "company_ids": [(6, 0, [cls.company.id])],
            })
        cls.portal_user = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Portal Photo Sentinel",
                "login": "portal.photo.sentinel@test.invalid",
                "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
                "company_id": cls.company.id,
                "company_ids": [(6, 0, [cls.company.id])],
            })

    def test_crm_reader_sees_photo_from_shipment(self):
        shipment = self.shipment.with_user(self.crm_user)
        self.assertEqual(shipment.ops_photo_ids.ids, [self.photo.id])

    def test_crm_reader_can_render_private_attachment_without_duplication(self):
        values = self.photo.with_user(self.crm_user).read([
            "image_data", "filename", "mime_type", "kind", "operator_user_id",
        ])[0]
        self.assertEqual(values["image_data"], self.attachment.sudo().datas)
        self.assertEqual(values["filename"], "produit.jpg")
        self.assertEqual(values["mime_type"], "image/jpeg")
        self.assertFalse(self.attachment.sudo().public)
        self.assertEqual(self.env["ir.attachment"].sudo().search_count([
            ("res_model", "=", "dally.ops.photo"),
            ("res_id", "=", self.photo.id),
        ]), 1)

    def test_removed_photo_is_not_shown_on_shipment(self):
        self.photo.sudo().write({"active": False})
        shipment = self.shipment.with_user(self.crm_user)
        self.assertFalse(shipment.ops_photo_ids)

    def test_other_company_photo_is_hidden(self):
        found = self.env["dally.ops.photo"].with_user(self.crm_user).search([
            ("id", "=", self.other_photo.id),
        ])
        self.assertFalse(found)

    def test_crm_reader_cannot_modify_ops_photo(self):
        with self.assertRaises(AccessError):
            self.photo.with_user(self.crm_user).write({"kind": "package"})

    def test_portal_cannot_read_ops_photo(self):
        with self.assertRaises(AccessError):
            self.photo.with_user(self.portal_user).read(["kind"])

    def test_shipment_form_contains_internal_photo_tab(self):
        view = self.env.ref(
            "dally_ops_mobile.dally_shipment_view_form_ops_photos")
        self.assertIn("Photos Ops", view.arch_db)
        self.assertIn("image_data", view.arch_db)
        self.assertIn("dally_core.group_dally_readonly", view.arch_db)
