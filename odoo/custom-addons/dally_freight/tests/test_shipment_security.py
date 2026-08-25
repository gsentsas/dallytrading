# -*- coding: utf-8 -*-
"""ACL and field-group tests (§91).

The specification requires that access rights be *tested*, not merely declared.
These tests are the ones that matter most in this module: they prove that supplier
costs, margins and internal notes are unreachable for users who should not see
them — enforced by the ORM, before any API layer gets involved.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestShipmentAccessRights(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Shipment = self.env["dally.shipment"]
        self.partner = self.env["res.partner"].create({"name": "ACL Customer"})

        self.shipment = self.Shipment.create({
            "partner_id": self.partner.id,
            "transport_mode": "sea",
            "direction": "import",
            "supplier_cost": 1500.0,
            "internal_notes": "Agent margin negotiated down, do not disclose.",
        })

        self.readonly_user = self._user("readonly", ["dally_core.group_dally_readonly"])
        self.logistics_user = self._user("logistics", ["dally_core.group_dally_logistics"])
        self.commercial_user = self._user("commercial", ["dally_core.group_dally_commercial"])
        self.finance_user = self._user("finance", ["dally_core.group_dally_finance"])
        self.manager_user = self._user("manager", ["dally_core.group_dally_manager"])
        # A plain internal user, in no DallyTrading group at all. This is the
        # shape of the tracking API's integration user.
        self.plain_user = self._user("plain", [])

    def _user(self, login, group_xml_ids):
        groups = [self.env.ref("base.group_user").id]
        for xml_id in group_xml_ids:
            groups.append(self.env.ref(xml_id).id)
        return self.env["res.users"].create({
            "name": "Test %s" % login,
            "login": "dally_test_%s" % login,
            "group_ids": [(6, 0, groups)],
        })

    # ─── Model-level access ───────────────────────────────────────────

    def test_readonly_user_can_read(self):
        shipment = self.shipment.with_user(self.readonly_user)
        self.assertEqual(shipment.reference, self.shipment.reference)

    def test_readonly_user_cannot_write(self):
        with self.assertRaises(AccessError):
            self.shipment.with_user(self.readonly_user).write({"origin_city": "Nope"})

    def test_readonly_user_cannot_create(self):
        with self.assertRaises(AccessError):
            self.Shipment.with_user(self.readonly_user).create({
                "partner_id": self.partner.id,
                "transport_mode": "air",
                "direction": "export",
            })

    def test_logistics_user_can_update_status(self):
        # Le test vérifie l'ACL, pas la mécanique de transition : on choisit
        # une transition adjacente autorisée depuis `draft` pour ne pas
        # interférer avec la garde de workflow (§20).
        shipment = self.shipment.with_user(self.logistics_user)
        shipment.write({"state": "request_received"})
        self.assertEqual(shipment.state, "request_received")

    def test_logistics_user_cannot_delete(self):
        """Deletion is reserved to managers, even for a draft file."""
        with self.assertRaises(AccessError):
            self.shipment.with_user(self.logistics_user).unlink()

    def test_manager_can_delete(self):
        shipment = self.Shipment.create({
            "partner_id": self.partner.id,
            "transport_mode": "air",
            "direction": "export",
        })
        shipment.with_user(self.manager_user).unlink()
        self.assertFalse(shipment.exists())

    def test_plain_user_cannot_read(self):
        """No DallyTrading group means no access to freight files at all."""
        with self.assertRaises(AccessError):
            self.shipment.with_user(self.plain_user).read(["reference"])

    # ─── Field-level confidentiality (§44) ────────────────────────────

    def test_finance_user_sees_supplier_cost(self):
        shipment = self.shipment.with_user(self.finance_user)
        self.assertAlmostEqual(shipment.supplier_cost, 1500.0)

    def test_logistics_user_cannot_read_supplier_cost(self):
        """The ORM strips the field: it is never loaded, not merely hidden."""
        shipment = self.shipment.with_user(self.logistics_user)
        with self.assertRaises(AccessError):
            shipment.read(["supplier_cost"])

    def test_commercial_user_cannot_read_margin(self):
        shipment = self.shipment.with_user(self.commercial_user)
        with self.assertRaises(AccessError):
            shipment.read(["margin"])

    def test_supplier_cost_absent_from_a_full_read(self):
        """A read() with no field list must not slip the restricted columns in.

        This is the case that matters: code that reads "everything" is common, and
        it must not become a leak.
        """
        data = self.shipment.with_user(self.logistics_user).read()[0]
        self.assertNotIn("supplier_cost", data)
        self.assertNotIn("margin", data)

    def test_internal_notes_absent_for_a_user_outside_the_group(self):
        """This is exactly the shape of the tracking API's integration user."""
        fields_available = self.Shipment.with_user(self.plain_user).fields_get()
        self.assertNotIn(
            "internal_notes", fields_available,
            "internal_notes must not even be described to a user outside the group",
        )
        self.assertNotIn("supplier_cost", fields_available)
        self.assertNotIn("margin", fields_available)

    def test_internal_notes_visible_to_staff(self):
        shipment = self.shipment.with_user(self.readonly_user)
        self.assertIn("do not disclose", shipment.internal_notes)

    def test_restricted_fields_cannot_be_written_by_logistics(self):
        with self.assertRaises(AccessError):
            self.shipment.with_user(self.logistics_user).write(
                {"supplier_cost": 1.0}
            )

    # ─── Multi-company record rule ────────────────────────────────────

    def test_shipment_of_another_company_is_invisible(self):
        other_company = self.env["res.company"].create({"name": "Other Co"})
        foreign = self.Shipment.create({
            "partner_id": self.partner.id,
            "transport_mode": "air",
            "direction": "export",
            "company_id": other_company.id,
        })

        # The manager is not allowed into that company, so the rule must hide it.
        visible = self.Shipment.with_user(self.manager_user).search([])
        self.assertNotIn(foreign, visible)
        self.assertIn(self.shipment, visible)

    def test_package_of_another_company_is_invisible(self):
        other_company = self.env["res.company"].create({"name": "Other Co 2"})
        foreign = self.Shipment.create({
            "partner_id": self.partner.id,
            "transport_mode": "air",
            "direction": "export",
            "company_id": other_company.id,
        })
        line = self.env["dally.shipment.package"].create({
            "shipment_id": foreign.id,
            "package_type": "parcel",
            "quantity": 1,
        })
        visible = self.env["dally.shipment.package"].with_user(
            self.manager_user
        ).search([])
        self.assertNotIn(line, visible)
