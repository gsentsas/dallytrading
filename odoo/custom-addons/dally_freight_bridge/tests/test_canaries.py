"""
Canaris : rien du fournisseur ne doit atteindre le client.

## Pourquoi des canaris plutôt qu'une revue de la liste blanche

`PUBLIC_PAYLOAD_KEYS` est une liste blanche explicite : en théorie, rien
d'autre ne sort. Mais « en théorie » est exactement ce qu'une fuite contredit.
Une liste blanche protège la projection qu'elle gouverne, et rien d'autre — pas
un champ recopié par mégarde dans un libellé, pas une valeur passée dans un
message de suivi, pas une description projetée depuis le fournisseur.

Un canari est une chaîne unique, impossible à produire par hasard. On la plante
dans les champs internes de l'expédition opérationnelle, puis on relit **tout**
ce que le client peut obtenir. Si la chaîne apparaît quelque part, la fuite est
prouvée ; si elle n'apparaît nulle part, la liste blanche a réellement tenu sur
ce chemin.

Le contrôle vaut aussi comme non-régression : le jour où quelqu'un ajoute un
champ à la projection, ces tests le voient passer.
"""

import base64
import uuid

from odoo.tests import TransactionCase, tagged

#: Marqueurs plantés dans les champs internes du fournisseur.
CANARIS = {
    "CANARY_VENDOR_COST": "cout fournisseur",
    "CANARY_MARGIN": "marge",
    "CANARY_SUPPLIER": "fournisseur",
    "CANARY_COMMISSION": "commission",
    "CANARY_INTERNAL_NOTE": "note interne",
    "CANARY_INTERNAL_DOCUMENT": "document interne",
}


@tagged("post_install", "-at_install", "dally_freight")
class TestCanaris(TransactionCase):
    """Aucun canari ne doit apparaître dans une sortie destinée au client."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        service = cls.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1
        )
        partenaire = cls.env["res.partner"].create({"name": "Canari Client"})
        cls.devis = cls.env["dally.quote.request"].create({
            "partner_id": partenaire.id,
            "contact_name": "Canari",
            "company_name": "Canari Client",
            "service_type_id": service.id,
            "email": "canari@test.invalid",
            "request_uuid": str(uuid.uuid4()),
        })
        cls.devis.write({"state": "won"})

        booking = cls.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", cls.devis.id)], limit=1
        )
        cls.expedition = cls.env["freight.shipment"].sudo().search(
            [("booking_id", "=", booking.id)], limit=1
        )
        cls.projection = cls.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "=", cls.expedition.id)], limit=1
        )

        # Plantation : on vise les champs texte libres du fournisseur, ceux qui
        # ont le plus de chances d'être recopiés sans être relus.
        valeurs = {}
        for champ in ("notes", "dangerous_goods_notes", "voyage_no", "obl"):
            if champ in cls.expedition._fields:
                valeurs[champ] = "CANARY_INTERNAL_NOTE canari"
        if valeurs:
            cls.expedition.sudo().write(valeurs)

        # Et dans les montants internes de la projection Dally elle-même, qui
        # existent sur le modele et ne doivent jamais sortir.
        cls.projection.sudo().write({
            "internal_notes": "CANARY_INTERNAL_NOTE CANARY_MARGIN CANARY_SUPPLIER",
        })

        # Un document du dossier opérationnel, jamais publié. Son nom ET son
        # contenu portent le canari : le premier fuirait par une projection
        # trop large, le second par un téléchargement mal contrôlé.
        cls.document_interne = cls.env["freight.documents"].sudo().create({
            "freight_id": cls.expedition.id,
            "file_name": "CANARY_INTERNAL_DOCUMENT-arbitrage.pdf",
            "document": base64.b64encode(b"CANARY_INTERNAL_DOCUMENT").decode(),
        })

    def _scan(self, valeur, chemin):
        """Échoue si un canari apparaît dans la valeur sérialisée."""
        texte = repr(valeur)
        for canari, libelle in CANARIS.items():
            self.assertNotIn(
                canari,
                texte,
                f"Fuite de {libelle} dans {chemin} : {canari} est present.",
            )

    def test_controle_positif_les_canaris_sont_bien_plantes(self):
        """Sans ce test, tous les autres passeraient sur une source vide.

        C'est une erreur déjà commise dans ce chantier : un comptage à zéro
        avait été lu comme « la barrière tient », alors que la table était
        simplement vide. Un canari absent ne prouve rien tant qu'on n'a pas
        prouvé qu'il était présent en amont.
        """
        source = repr(self.expedition.sudo().read())
        self.assertIn(
            "CANARY_INTERNAL_NOTE",
            source,
            "Le canari n'a pas ete plante dans l'expedition du fournisseur : "
            "les tests d'absence qui suivent ne prouveraient rien.",
        )
        self.assertIn(
            "CANARY_MARGIN",
            repr(self.projection.sudo().read(["internal_notes"])),
            "Le canari n'a pas ete plante dans les notes internes.",
        )
        self.assertIn(
            "CANARY_INTERNAL_DOCUMENT",
            repr(self.document_interne.sudo().read(["file_name"])),
            "Le canari n'a pas ete plante dans le document interne.",
        )

    def test_le_document_interne_ne_fuit_dans_aucune_projection(self):
        """Il n'a jamais été publié : il ne doit exister nulle part côté client."""
        self.assertFalse(self.document_interne.dally_portal_document_id)
        for nom, payload in (
            ("portail", self.projection._dally_portal_payload()),
            ("detail", self.projection._dally_portal_detail_payload()),
            ("public", self.projection._dally_public_payload()),
        ):
            self.assertNotIn(
                "CANARY_INTERNAL_DOCUMENT",
                repr(payload),
                f"Le document interne fuit dans la projection {nom}.",
            )

    def test_la_projection_portail_ne_porte_aucun_canari(self):
        self._scan(
            self.projection._dally_portal_payload(),
            "_dally_portal_payload",
        )

    def test_le_detail_portail_ne_porte_aucun_canari(self):
        self._scan(
            self.projection._dally_portal_detail_payload(),
            "_dally_portal_detail_payload",
        )

    def test_le_suivi_public_ne_porte_aucun_canari(self):
        self._scan(
            self.projection._dally_public_payload(),
            "_dally_public_payload",
        )

    def test_aucune_projection_ne_porte_l_identifiant_du_fournisseur(self):
        """`tk_shipment_id` ne doit exister dans aucun contrat client.

        Le portail parle le langage Dally : une référence Dally, un état Dally.
        L'identifiant interne du fournisseur n'y a pas sa place, ne serait-ce
        que parce qu'il invite à l'utiliser comme paramètre d'entrée.
        """
        for nom, payload in (
            ("portail", self.projection._dally_portal_payload()),
            ("detail", self.projection._dally_portal_detail_payload()),
            ("public", self.projection._dally_public_payload()),
        ):
            texte = repr(payload)
            for interdit in ("tk_shipment_id", "tkShipmentId", "freight.shipment"):
                self.assertNotIn(
                    interdit, texte, f"{interdit} present dans la projection {nom}."
                )
            self.assertNotIn(
                str(self.expedition.id),
                str(payload.get("reference", "")),
                f"La reference {nom} expose l'identifiant du fournisseur.",
            )

    def test_les_evenements_projetes_sont_fermes_par_defaut(self):
        """Politique de publication : rien n'est visible tant que ce n'est pas décidé.

        Un événement d'exploitation publié par accident est irrattrapable — le
        client l'a lu. La synchronisation ne publie donc jamais d'elle-même.
        """
        evenements = self.env["dally.shipment.event"].sudo().search(
            [("shipment_id", "=", self.projection.id)]
        )
        publies = evenements.filtered("visible_to_customer")
        self.assertFalse(
            publies,
            "Des evenements ont ete publies automatiquement par la synchronisation.",
        )
