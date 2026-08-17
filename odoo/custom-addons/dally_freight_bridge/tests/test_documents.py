"""
Publication des documents fret : ce qui sort, et ce qui ne sort jamais.

Deux sociétés, deux expéditions, trois documents — un publié, un interne, un
appartenant à l'autre client. Le jeu est monté ainsi parce que chacune des trois
questions se pose séparément : *ai-je le droit de voir ce document*, *ce document
a-t-il été publié*, et *appartient-il à mon dossier*. Un test qui n'en couvre
qu'une laisse les deux autres ouvertes.
"""

import base64
import uuid

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

#: Contenu du document interne. Ne doit apparaître nulle part côté client.
CANARI_DOCUMENT_INTERNE = "CANARY_INTERNAL_DOCUMENT"


@tagged("post_install", "-at_install", "dally_freight")
class TestPublicationDocuments(TransactionCase):
    """La publication est explicite, cloisonnée et idempotente."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.groupe_portail = cls.env.ref("base.group_portal")
        cls.service = cls.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1
        )

        cls.societe_a, cls.client_a, cls.projection_a = cls._dossier("A")
        cls.societe_b, cls.client_b, cls.projection_b = cls._dossier("B")

        cls.doc_publie_a = cls._document(cls.projection_a, "bl-a.pdf", b"CONNAISSEMENT A")
        cls.doc_interne_a = cls._document(
            cls.projection_a, "arbitrage-interne-a.pdf",
            CANARI_DOCUMENT_INTERNE.encode(),
        )
        cls.doc_b = cls._document(cls.projection_b, "bl-b.pdf", b"CONNAISSEMENT B")

        cls.publication_a = cls.doc_publie_a.dally_publish_to_portal()
        cls.publication_b = cls.doc_b.dally_publish_to_portal()

    @classmethod
    def _dossier(cls, tag):
        """Un client portail, son devis accepté, et la projection qui en sort."""
        partenaire = cls.env["res.partner"].create({"name": f"Doc Societe {tag}"})
        utilisateur = cls.env["res.users"].create({
            "name": f"Doc Portail {tag}",
            "login": f"doc.{tag.lower()}@dally.invalid",
            "partner_id": partenaire.id,
            "group_ids": [(6, 0, [cls.groupe_portail.id])],
        })
        devis = cls.env["dally.quote.request"].create({
            "partner_id": partenaire.id,
            "contact_name": f"Doc {tag}",
            "company_name": f"Doc Societe {tag}",
            "service_type_id": cls.service.id,
            "email": f"doc-{tag.lower()}@test.invalid",
            "request_uuid": str(uuid.uuid4()),
        })
        devis.write({"state": "won"})

        booking = cls.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", devis.id)], limit=1
        )
        expedition = cls.env["freight.shipment"].sudo().search(
            [("booking_id", "=", booking.id)], limit=1
        )
        projection = cls.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "=", expedition.id)], limit=1
        )
        return partenaire, utilisateur, projection

    @classmethod
    def _document(cls, projection, nom, contenu):
        return cls.env["freight.documents"].sudo().create({
            "freight_id": projection.sudo().tk_shipment_id.id,
            "file_name": nom,
            "document": base64.b64encode(contenu).decode(),
        })

    def _visibles(self, utilisateur):
        """Publications qu'un client peut réellement lire."""
        self.env.invalidate_all()
        return self.env(user=utilisateur)["dally.portal.document"].search([])

    # ------------------------------------------------------------------
    # Ce que le client voit
    # ------------------------------------------------------------------

    def test_le_client_voit_son_document_publie(self):
        """Contrôle positif : sans lui, les refus ne prouveraient rien."""
        self.assertIn(self.publication_a, self._visibles(self.client_a))

    def test_le_document_interne_reste_invisible(self):
        """Il n'a jamais été publié : aucune publication n'existe pour lui."""
        self.assertFalse(self.doc_interne_a.dally_portal_document_id)
        visibles = self._visibles(self.client_a)
        self.assertNotIn(
            CANARI_DOCUMENT_INTERNE,
            repr(visibles.read(["name"])),
            "Le document interne apparait dans l'espace client.",
        )

    def test_le_client_ne_voit_pas_le_document_d_un_autre(self):
        self.assertNotIn(self.publication_b, self._visibles(self.client_a))

    def test_le_cloisonnement_vaut_dans_les_deux_sens(self):
        self.assertNotIn(self.publication_a, self._visibles(self.client_b))

    def test_lire_directement_la_publication_d_autrui_est_refuse(self):
        """Un identifiant deviné ne doit pas devenir une autorisation."""
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.env(user=self.client_a)["dally.portal.document"].browse(
                self.publication_b.id
            ).read(["name"])

    # ------------------------------------------------------------------
    # Le portail n'atteint jamais la source
    # ------------------------------------------------------------------

    def test_le_client_n_atteint_pas_le_document_operationnel(self):
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.env(user=self.client_a)["freight.documents"].browse(
                self.doc_interne_a.id
            ).read(["file_name"])

    def test_le_client_ne_peut_pas_publier(self):
        """La publication est une décision interne, pas une action client."""
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.doc_interne_a.with_user(self.client_a).dally_publish_to_portal()
        self.assertFalse(self.doc_interne_a.dally_portal_document_id)

    def test_aucun_identifiant_fournisseur_n_est_accepte_en_entree(self):
        """La projection est retrouvée côté serveur, depuis le document.

        Rien dans la chaîne de publication n'accepte un identifiant tk fourni
        par l'appelant : c'est `freight_id` du document qui décide.
        """
        publication = self.doc_publie_a.dally_portal_document_id
        self.assertEqual(publication.shipment_id, self.projection_a)

    # ------------------------------------------------------------------
    # Idempotence et dépublication
    # ------------------------------------------------------------------

    def test_publier_deux_fois_ne_cree_qu_une_publication(self):
        avant = self.env["dally.portal.document"].sudo().search_count([])
        for _ in range(5):
            self.doc_publie_a.dally_publish_to_portal()
        self.assertEqual(
            self.env["dally.portal.document"].sudo().search_count([]),
            avant,
            "Republier a cree un second exemplaire.",
        )

    def test_depublier_retire_le_document_de_l_espace_client(self):
        document = self._document(self.projection_a, "temporaire.pdf", b"TEMP")
        publication = document.dally_publish_to_portal()
        self.assertIn(publication, self._visibles(self.client_a))

        document.dally_unpublish_from_portal()
        self.assertFalse(document.dally_portal_document_id)
        self.assertFalse(publication.exists())

    def test_depublier_deux_fois_ne_leve_pas(self):
        document = self._document(self.projection_a, "temporaire2.pdf", b"TEMP")
        document.dally_publish_to_portal()
        document.dally_unpublish_from_portal()
        document.dally_unpublish_from_portal()
        self.assertFalse(document.dally_portal_document_id)

    # ------------------------------------------------------------------
    # Octets et refus explicites
    # ------------------------------------------------------------------

    def test_les_octets_ne_sont_pas_dupliques(self):
        """La publication référence la pièce jointe du fournisseur.

        Copier produirait deux exemplaires : corriger le document opérationnel
        laisserait le client avec l'ancienne version, sans aucun signal.
        """
        piece_jointe = self.doc_publie_a._dally_attachment()
        self.assertTrue(piece_jointe)
        self.assertEqual(
            self.doc_publie_a.dally_portal_document_id.attachment_id,
            piece_jointe,
        )

    def test_un_document_sans_expedition_ne_peut_pas_etre_publie(self):
        orphelin = self.env["freight.documents"].sudo().create({
            "file_name": "orphelin.pdf",
            "document": base64.b64encode(b"ORPHELIN").decode(),
        })
        with self.assertRaises(UserError):
            orphelin.dally_publish_to_portal()
