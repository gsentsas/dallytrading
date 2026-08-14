# -*- coding: utf-8 -*-
"""Le modèle documentaire : ce qu'il rend structurellement impossible."""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_portal.models.dally_portal_document import BUSINESS_LINKS


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestPortalDocument(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({
            "name": "DOC-TEST Société", "is_company": True,
        })
        self.contact = self.env["res.partner"].create({
            "name": "DOC-TEST Contact", "parent_id": self.partner.id,
        })
        self.shipment = self.env["dally.shipment"].create({
            "partner_id": self.contact.id,
        })
        self.sourcing = self.env["dally.sourcing.request"].create({
            "product_name": "DOC-TEST produit", "quantity": 1.0,
            "contact_name": "DOC-TEST", "customer_id": self.partner.id,
        })
        self.attachment = self.env["ir.attachment"].create({
            "name": "DOC-TEST.pdf", "datas": b"JVBERi0xLjQK",
        })

    def _document(self, **overrides):
        values = {
            "name": "DOC-TEST document", "attachment_id": self.attachment.id,
            "document_type": "other",
        }
        values.update(overrides)
        return self.env["dally.portal.document"].create(values)

    def test_exactly_five_business_links_are_declared(self):
        """La table de rattachements est le périmètre publiable. Elle est fermée."""
        self.assertEqual(set(BUSINESS_LINKS), {
            "quote_request_id", "sourcing_request_id", "sourcing_proposal_id",
            "trade_opportunity_id", "shipment_id",
        })

    def test_internal_models_have_no_field_to_be_attached_to(self):
        """Publier un document d'offre ou de coût n'est pas interdit : c'est inexprimable.

        Aucun champ ne les accepte. Une liste de modèles autorisés vérifiée quelque
        part protégerait tant que quelqu'un pense à la consulter ; ici il n'y a rien
        à consulter.
        """
        model = self.env["dally.portal.document"]
        for forbidden in (
            "sourcing_offer_id", "sourcing_supplier_id", "trade_cost_id",
            "trade_commission_id", "res_model", "res_id",
        ):
            self.assertNotIn(
                forbidden, model._fields,
                f"le modèle documentaire accepte un rattachement à {forbidden}",
            )

    def test_no_business_link_is_refused(self):
        with self.assertRaises(ValidationError):
            self._document()

    def test_two_business_links_are_refused(self):
        """Deux rattachements feraient dépendre le propriétaire de l'ordre d'évaluation."""
        with self.assertRaises(ValidationError):
            self._document(
                shipment_id=self.shipment.id,
                sourcing_request_id=self.sourcing.id,
            )

    def test_owner_is_derived_not_supplied(self):
        """Le propriétaire remonte à la SOCIÉTÉ, même si le dossier vise un contact."""
        document = self._document(shipment_id=self.shipment.id)
        self.assertEqual(document.commercial_partner_id, self.partner)

    def test_owner_is_derived_whatever_the_field_name(self):
        """`partner_id` ici, `customer_id` là : la table porte la correspondance."""
        by_shipment = self._document(shipment_id=self.shipment.id)
        by_sourcing = self._document(sourcing_request_id=self.sourcing.id)
        self.assertEqual(by_shipment.commercial_partner_id, self.partner)
        self.assertEqual(by_sourcing.commercial_partner_id, self.partner)

    def test_publishing_without_an_owner_is_refused(self):
        orphan_shipment = self.env["dally.shipment"].create({})
        document = self._document(shipment_id=orphan_shipment.id)
        self.assertFalse(document.commercial_partner_id)
        with self.assertRaises(ValidationError):
            document.action_publish()

    def test_publish_and_unpublish_record_who_and_when(self):
        document = self._document(shipment_id=self.shipment.id)
        self.assertFalse(document.published_to_portal)
        document.action_publish()
        self.assertTrue(document.published_to_portal)
        self.assertEqual(document.published_by_id, self.env.user)
        self.assertTrue(document.published_on)
        document.action_unpublish()
        self.assertFalse(document.published_to_portal)
        self.assertFalse(document.published_by_id)

    def test_payload_matches_its_allowlist_and_hides_the_attachment(self):
        document = self._document(shipment_id=self.shipment.id)
        document.action_publish()
        payload = document._dally_portal_payload()
        self.assertEqual(
            set(payload),
            set(self.env["dally.portal.document"].PORTAL_PAYLOAD_KEYS),
        )
        serialised = repr(payload).lower()
        for forbidden in ("attachment", "store_fname", "datas", "res_id", "partner"):
            self.assertNotIn(
                forbidden, serialised,
                f"'{forbidden}' apparaît dans la projection client",
            )
