# -*- coding: utf-8 -*-
"""Access rights and cost confidentiality (§17, §25, §26, §48).

If any test in this file fails, purchase prices, margins or supplier identities are
reachable by someone who should not have them. The checks are deliberately blunt: they
plant distinctive values in the confidential fields and assert the ORM refuses them,
rather than trusting that a view happens to hide them.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestSourcingAccessRights(TransactionCase):

    SECRET_NOTE = "SOURCING-LEAK-CANARY-internal-note"

    def setUp(self):
        super().setUp()
        self.Request = self.env["dally.sourcing.request"]
        self.Offer = self.env["dally.sourcing.offer"]
        self.Proposal = self.env["dally.sourcing.proposal"]

        self.customer = self.env["res.partner"].create({
            "name": "Security Customer", "email": "security@example.com",
        })
        self.factory = self.env["res.partner"].create({
            "name": "Secret Factory Ltd", "is_company": True,
        })

        self.request = self.Request.create({
            "product_name": "Confidential product",
            "quantity": 10.0,
            "contact_email": "security@example.com",
            "customer_id": self.customer.id,
            "internal_notes": self.SECRET_NOTE,
        })
        self.supplier = self.env["dally.sourcing.supplier"].create({
            "request_id": self.request.id, "partner_id": self.factory.id,
        })
        self.offer = self.Offer.create({
            "request_id": self.request.id,
            "supplier_id": self.supplier.id,
            "quantity": 10.0,
            "unit_price": 777.77,
            "internal_notes": "SECRET-OFFER-NOTE agent unreliable",
        })
        self.proposal = self.Proposal.create({
            "request_id": self.request.id,
            "product_name": "Confidential product",
            "quantity": 10.0,
            "selling_unit_price": 1000.0,
            "cost_basis": 7777.7,
        })

        self.sourcing_user = self._user("sourcing", ["dally_core.group_dally_sourcing"])
        self.sourcing_manager = self._user(
            "srcmanager", ["dally_sourcing.group_dally_sourcing_manager"],
        )
        self.commercial_user = self._user(
            "commercial", ["dally_core.group_dally_commercial"],
        )
        self.finance_user = self._user("finance", ["dally_core.group_dally_finance"])
        self.readonly_user = self._user("readonly", ["dally_core.group_dally_readonly"])
        self.manager_user = self._user("manager", ["dally_core.group_dally_manager"])
        self.tracking_api_user = self.env.ref(
            "dally_tracking.user_dally_api_tracking",
        )
        self.sourcing_api_user = self.env.ref(
            "dally_sourcing.user_dally_api_sourcing",
        )
        # A plain internal user, in no DallyTrading group at all.
        self.plain_user = self._user("plain", [])

    def _user(self, login, group_xml_ids):
        groups = [self.env.ref("base.group_user").id]
        for xml_id in group_xml_ids:
            groups.append(self.env.ref(xml_id).id)
        return self.env["res.users"].create({
            "name": "Sourcing test %s" % login,
            "login": "dally_src_test_%s" % login,
            "groups_id": [(6, 0, groups)],
        })

    # ─── The API user's group membership ──────────────────────────────

    def test_sourcing_api_user_is_in_no_business_group(self):
        """Membership of group_dally_readonly would expose internal_notes."""
        for group in (
            "dally_core.group_dally_readonly",
            "dally_core.group_dally_commercial",
            "dally_core.group_dally_sourcing",
            "dally_sourcing.group_dally_sourcing_manager",
            "dally_core.group_dally_finance",
            "dally_core.group_dally_manager",
            "dally_core.group_dally_admin",
            "base.group_system",
        ):
            self.assertFalse(
                self.sourcing_api_user.has_group(group),
                "The sourcing API user must not hold %s" % group,
            )
        self.assertTrue(
            self.sourcing_api_user.has_group("dally_sourcing.group_dally_sourcing_api")
        )

    # ─── Requests ─────────────────────────────────────────────────────

    def test_sourcing_user_can_read_and_write_requests(self):
        request = self.request.with_user(self.sourcing_user)
        self.assertEqual(request.product_name, "Confidential product")
        request.write({"specifications": "Updated"})

    def test_commercial_user_can_read_but_not_write_requests(self):
        """Commercial staff follow the case; they do not run the research."""
        request = self.request.with_user(self.commercial_user)
        self.assertEqual(request.reference, self.request.reference)
        with self.assertRaises(AccessError):
            request.write({"specifications": "Nope"})

    def test_readonly_user_cannot_write_requests(self):
        with self.assertRaises(AccessError):
            self.request.with_user(self.readonly_user).write({"quantity": 1.0})

    def test_plain_user_cannot_read_requests(self):
        with self.assertRaises(AccessError):
            self.request.with_user(self.plain_user).read(["reference"])

    def test_tracking_api_user_cannot_read_requests(self):
        """Each API user is scoped to its own endpoints."""
        with self.assertRaises(AccessError):
            self.request.with_user(self.tracking_api_user).read(["reference"])

    def test_sourcing_api_user_can_create_but_not_write(self):
        created = self.Request.with_user(self.sourcing_api_user).create({
            "product_name": "API created",
            "quantity": 1.0,
            "contact_email": "api@example.com",
        })
        self.assertTrue(created.id)
        with self.assertRaises(AccessError):
            created.write({"quantity": 2.0})

    def test_sourcing_api_user_sees_only_its_own_records(self):
        """The record rule: a flaw in the controller still cannot reach staff records."""
        created = self.Request.with_user(self.sourcing_api_user).create({
            "product_name": "API own record",
            "quantity": 1.0,
            "contact_email": "api-own@example.com",
        })
        visible = self.Request.with_user(self.sourcing_api_user).search([])
        self.assertIn(created, visible)
        self.assertNotIn(
            self.request, visible,
            "The API user must not see requests entered by staff",
        )

    def test_internal_notes_hidden_from_the_sourcing_api_user(self):
        available = self.Request.with_user(self.sourcing_api_user).fields_get()
        self.assertNotIn("internal_notes", available)

    def test_internal_notes_visible_to_sourcing_staff(self):
        request = self.request.with_user(self.sourcing_user)
        self.assertIn("LEAK-CANARY", request.internal_notes)

    # ─── Offers: the confidential model ──────────────────────────────

    def test_sourcing_user_can_read_offers(self):
        offer = self.offer.with_user(self.sourcing_user)
        self.assertAlmostEqual(offer.unit_price, 777.77)

    def test_commercial_user_has_no_access_to_offers_at_all(self):
        """Not a filtered view — no model access. §17 is a hard requirement."""
        with self.assertRaises(AccessError):
            self.offer.with_user(self.commercial_user).read(["unit_price"])

    def test_readonly_user_has_no_access_to_offers(self):
        with self.assertRaises(AccessError):
            self.offer.with_user(self.readonly_user).read(["unit_price"])

    def test_tracking_api_user_has_no_access_to_offers(self):
        with self.assertRaises(AccessError):
            self.offer.with_user(self.tracking_api_user).read(["unit_price"])

    def test_sourcing_api_user_has_no_access_to_offers(self):
        with self.assertRaises(AccessError):
            self.offer.with_user(self.sourcing_api_user).read(["unit_price"])

    def test_commercial_user_cannot_search_offers(self):
        """A search with no domain must not leak their existence either."""
        with self.assertRaises(AccessError):
            self.Offer.with_user(self.commercial_user).search([])

    def test_finance_user_can_read_offers_but_not_write(self):
        offer = self.offer.with_user(self.finance_user)
        self.assertAlmostEqual(offer.unit_price, 777.77)
        with self.assertRaises(AccessError):
            offer.write({"unit_price": 1.0})

    # ─── Candidate suppliers ─────────────────────────────────────────

    def test_commercial_user_has_no_access_to_candidate_suppliers(self):
        """Which factories were approached is commercial information."""
        with self.assertRaises(AccessError):
            self.supplier.with_user(self.commercial_user).read(["partner_id"])

    def test_sourcing_user_can_manage_candidate_suppliers(self):
        supplier = self.supplier.with_user(self.sourcing_user)
        self.assertEqual(supplier.partner_id, self.factory)
        supplier.write({"status": "contacted"})

    # ─── Proposals and margin ────────────────────────────────────────

    def test_commercial_user_can_read_a_proposal(self):
        """They present it to the customer, so they must be able to read it."""
        proposal = self.proposal.with_user(self.commercial_user)
        self.assertAlmostEqual(proposal.total_amount, 10000.0)

    def test_commercial_user_cannot_read_the_cost_basis(self):
        with self.assertRaises(AccessError):
            self.proposal.with_user(self.commercial_user).read(["cost_basis"])

    def test_commercial_user_cannot_read_the_margin(self):
        with self.assertRaises(AccessError):
            self.proposal.with_user(self.commercial_user).read(["margin"])

    def test_sourcing_user_cannot_read_the_margin(self):
        """A sourcing user records offers; a manager decides the selling price."""
        with self.assertRaises(AccessError):
            self.proposal.with_user(self.sourcing_user).read(["margin"])

    def test_sourcing_manager_can_read_the_margin(self):
        proposal = self.proposal.with_user(self.sourcing_manager)
        self.assertAlmostEqual(proposal.cost_basis, 7777.7, places=1)

    def test_finance_user_can_read_the_margin(self):
        proposal = self.proposal.with_user(self.finance_user)
        self.assertAlmostEqual(proposal.cost_basis, 7777.7, places=1)

    def test_full_read_does_not_slip_restricted_fields_in(self):
        """Code that reads "everything" is common; it must not become a leak."""
        data = self.proposal.with_user(self.commercial_user).read()[0]
        self.assertNotIn("cost_basis", data)
        self.assertNotIn("margin", data)
        self.assertNotIn("margin_rate", data)
        self.assertNotIn("source_offer_id", data)

    def test_restricted_fields_not_described_to_a_commercial_user(self):
        available = self.Proposal.with_user(self.commercial_user).fields_get()
        for field in ("cost_basis", "margin", "margin_rate", "source_offer_id"):
            self.assertNotIn(field, available)

    def test_selected_offer_hidden_from_a_commercial_user(self):
        """Which supplier was chosen may be information DallyTrading withholds."""
        available = self.Request.with_user(self.commercial_user).fields_get()
        self.assertNotIn("selected_offer_id", available)

    # ─── Multi-company ───────────────────────────────────────────────

    def test_request_of_another_company_is_invisible(self):
        other_company = self.env["res.company"].create({"name": "Other Sourcing Co"})
        foreign = self.Request.create({
            "product_name": "Foreign",
            "quantity": 1.0,
            "contact_email": "foreign@example.com",
            "company_id": other_company.id,
        })
        visible = self.Request.with_user(self.manager_user).search([])
        self.assertNotIn(foreign, visible)
        self.assertIn(self.request, visible)

    def test_offer_of_another_company_is_invisible(self):
        other_company = self.env["res.company"].create({"name": "Other Sourcing Co 2"})
        foreign_request = self.Request.create({
            "product_name": "Foreign", "quantity": 1.0,
            "contact_email": "foreign2@example.com",
            "company_id": other_company.id,
        })
        foreign_supplier = self.env["dally.sourcing.supplier"].create({
            "request_id": foreign_request.id, "partner_id": self.factory.id,
        })
        foreign_offer = self.Offer.create({
            "request_id": foreign_request.id,
            "supplier_id": foreign_supplier.id,
            "quantity": 1.0, "unit_price": 1.0,
        })
        visible = self.Offer.with_user(self.sourcing_user).search([])
        self.assertNotIn(foreign_offer, visible)
