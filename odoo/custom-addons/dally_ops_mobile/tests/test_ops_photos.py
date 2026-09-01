# -*- coding: utf-8 -*-
"""Les preuves photographiques d'un dossier de terrain.

## Ce que ces tests protègent

**Le contenu.** Le type est déduit des octets et les dimensions d'un en-tête
borné. Un fichier HTML renommé `.jpg` et une image de soixante mille pixels de
côté sont refusés pour la même raison : ce qu'un envoyeur annonce n'engage que
lui.

**La portée.** Une photo appartient à un dossier Ops natif d'une société. Un
dossier repris du tableur, un dossier historique, un dossier d'une autre
société : le même refus, sans distinction, pour qu'un essai ne renseigne pas.

**Le rejeu.** Le réseau d'un entrepôt coupe pendant l'envoi d'une image bien
plus souvent que pendant celui de trois lignes de texte. Le même geste renvoyé
ne doit produire ni seconde photo, ni seconde pièce jointe, ni second audit.

**La preuve elle-même.** Rien ne se supprime : une photo retirée reste, avec
son auteur et l'heure de son retrait. C'est la différence entre corriger une
erreur et effacer une trace.

## Sur les images de test

Les fixtures JPEG, PNG et WebP sont de **vrais** fichiers produits par un
encodeur, réduits à quelques dizaines d'octets. La fixture HEIC est construite
ici selon ISO/IEC 23008-12 : aucun encodeur HEIC n'est disponible dans ce
dépôt, et le lecteur d'en-têtes ne regarde de toute façon que le conteneur —
validé par ailleurs sur un fichier ISOBMFF produit par libheif.
"""

import base64
import struct
import uuid
from unittest.mock import patch

from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError
from odoo.addons.dally_ops_mobile.models.ops_photo_service import (
    MAX_ACTIVE_PHOTOS,
    MAX_FILE_BYTES,
    MAX_RETAINED_PHOTOS,
)

#: Vrais fichiers, produits par un encodeur, en 48 × 32.
JPEG_REEL = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAAAAAAD/2wBDACgcHiMeGSgjISMtKygwPGRBPDc3PHtYXUlkkYCZlo"
    "+AjIqgtObDoKrarYqMyP/L2u71////m8H////6/+b9//j/2wBDASstLTw1PHZBQXb4pYyl+Pj4"
    "+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj/wAARCAAgADAD"
    "ASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QA"
    "FgEBAQEAAAAAAAAAAAAAAAAAAAIE/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8A"
    "kANiQAAAAAAAAAH/2Q==")
PNG_REEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAADAAAAAgAQMAAABuGmlfAAAAIGNIUk0AAHomAACAhAAA+gAAAIDo"
    "AAB1MAAA6mAAADqYAAAXcJy6UTwAAAAGUExURQAAgP///0iAKeYAAAABYktHRAH/Ai3eAAAAB3RJ"
    "TUUH6ggfFwAJI7STHQAAAAxJREFUCNdjYBjeAAAA4AABhiDhrgAAAABJRU5ErkJggg==")
WEBP_REEL = base64.b64decode(
    "UklGRkYAAABXRUJQVlA4IDoAAAAwAwCdASowACAAPpFGnkslo6KhpWgAsBIJZwDOOA8KmggAAP73"
    "WS//yU//P7/n9z3XJ+rB/0+EaAAA")


def _boite(nom, corps):
    return struct.pack(">I", len(corps) + 8) + nom + corps


def heic(largeur=48, hauteur=32, marque=b"heic"):
    """Un conteneur HEIC minimal, conforme à ISO/IEC 23008-12.

    `ispe` — *image spatial extent* — est la boîte que la norme impose pour tout
    élément image, et la seule façon d'obtenir des dimensions sans toucher au
    flux codé.
    """
    ispe = _boite(b"ispe", b"\x00\x00\x00\x00" + struct.pack(">II", largeur, hauteur))
    ipco = _boite(b"ipco", ispe)
    iprp = _boite(b"iprp", ipco)
    meta = _boite(b"meta", b"\x00\x00\x00\x00" + iprp)
    ftyp = _boite(b"ftyp", marque + b"\x00\x00\x00\x00" + marque)
    return ftyp + meta + _boite(b"mdat", b"\x00" * 8)


def heic_ispe(*mesures, marque=b"heic"):
    """Un conteneur portant plusieurs `ispe` — vignette et image, ou piège."""
    ipco = _boite(b"ipco", b"".join(
        _boite(b"ispe", b"\x00\x00\x00\x00" + struct.pack(">II", l, h))
        for l, h in mesures))
    meta = _boite(b"meta", b"\x00\x00\x00\x00" + _boite(b"iprp", ipco))
    return _boite(b"ftyp", marque + b"\x00\x00\x00\x00" + marque) + meta


def png(largeur, hauteur):
    """Un PNG dont l'en-tête annonce les dimensions demandées."""
    ihdr = struct.pack(">II", largeur, hauteur) + b"\x08\x02\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + b"IHDR"
            + ihdr + b"\x00\x00\x00\x00")


@tagged("post_install", "-at_install", "dally")
class TestOpsPhotos(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.societe = cls.env.company
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Photo Autre"})

        cls.gilles = cls._compte(
            "photo.gilles", "dally_ops_mobile.group_dally_ops_logistician")
        cls.mariama = cls._compte(
            "photo.mariama", "dally_ops_mobile.group_dally_ops_logistician")
        cls.responsable = cls._compte(
            "photo.resp", "dally_ops_mobile.group_dally_ops_supervisor")
        cls.temoin = cls._compte("photo.temoin", "base.group_user")

        Famille = cls.env["dally.freight.tariff.family"]
        Regle = cls.env["dally.freight.tariff.rule"]
        cls.famille = Famille.search([("code", "=", "non_food")], limit=1)
        if not cls.famille:
            cls.famille = Famille.create(
                {"name": "Photo Non alimentaire", "code": "non_food"})
        if not Regle.search([("family_id", "=", cls.famille.id),
                             ("transport_mode", "=", "air")], limit=1):
            Regle.create({
                "name": "Photo non_food air", "transport_mode": "air",
                "family_id": cls.famille.id, "customer_segment": "all",
                "price_per_kg_eur": 5.0,
            })

        cls.partner = cls.env["res.partner"].create({
            "name": "Aissatou Photo", "company_id": cls.societe.id,
            "phone": "+221770000031",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.depart = cls._consolidation("AIR-DSS-CDG-PHOTO-001")

    # ─── Fabriques ───────────────────────────────────────────────────

    @classmethod
    def _compte(cls, prefixe, groupe):
        return cls.env["res.users"].create({
            "name": prefixe, "login": "%s.%s" % (prefixe, uuid.uuid4().hex[:6]),
            "group_ids": [(6, 0, [cls.env.ref(groupe).id])],
            "company_id": cls.env.company.id,
            "company_ids": [(6, 0, [cls.env.company.id])],
            "dally_ops_cash_actor": "Gilles",
        })

    @classmethod
    def _consolidation(cls, reference, societe=None):
        return cls.env["dally.freight.consolidation"].create({
            "name": reference, "state": "collecting", "active": True,
            "company_id": (societe or cls.env.company).id,
            "transport_mode": "air", "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })

    def _creer_dossier(self, consolidation=None):
        resultat = (self.env["dally.ops.intake.service"]
                    .with_user(self.gilles).with_company(self.societe)
                    .create_intake({
                        "request_uuid": str(uuid.uuid4()),
                        "consolidation_reference": (consolidation or self.depart).name,
                        "customer_reference": self.handle.token,
                        "received_on": "2026-08-29",
                        "line": {
                            "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                            "goods_category": "Non alimentaire", "description": "Savon",
                            "quantity": 1, "announced_weight_kg": None,
                            "exact_weight_kg": 13.5, "length_cm": None,
                            "width_cm": None, "height_cm": None,
                            "billing_method": "real",
                            "tariff_family_code": self.famille.code,
                            "customs_value_xof": 25000,
                        },
                    }))
        return resultat["intake"]["reference"]

    def _dossier_ancien(self, reference, societe=None):
        return self.env["dally.shipment"].sudo().create({
            "partner_id": self.partner.id,
            "company_id": (societe or self.societe).id,
            "external_reference": reference,
            "transport_mode": "air", "direction": "export",
        })

    def _shipment(self, reference):
        return self.env["dally.shipment"].sudo().search(
            [("external_reference", "=", reference)], limit=1)

    def _service(self, utilisateur=None, societe=None):
        return (self.env["dally.ops.photo.service"]
                .with_user(utilisateur or self.gilles)
                .with_company(societe or self.societe))

    def _etat(self, reference, etat):
        """Amène un dossier à l'état voulu par le chemin normal quand il existe."""
        service = (self.env["dally.ops.intake.state.service"]
                   .with_user(self.gilles).with_company(self.societe))
        if etat in ("preparing", "ready"):
            service.advance_state(reference, {
                "request_uuid": str(uuid.uuid4()),
                "expected_state": "goods_received", "target_state": "preparing"})
        if etat == "ready":
            service.advance_state(reference, {
                "request_uuid": str(uuid.uuid4()),
                "expected_state": "preparing", "target_state": "ready"})
        return self._shipment(reference)

    _ABSENT = object()

    def _ajouter(self, reference, contenu=None, kind="reception",
                 request_uuid=_ABSENT, filename="photo.jpg", utilisateur=None):
        return self._service(utilisateur).add_photo(
            reference,
            (str(uuid.uuid4()) if request_uuid is self._ABSENT else request_uuid),
            kind,
            filename,
            JPEG_REEL if contenu is None else contenu,
        )

    def _supprimer(self, reference, photo_uuid, request_uuid=_ABSENT,
                   utilisateur=None):
        return self._service(utilisateur).delete_photo(
            reference, photo_uuid,
            (str(uuid.uuid4()) if request_uuid is self._ABSENT else request_uuid))

    def _lister(self, reference, utilisateur=None):
        return self._service(utilisateur).list_photos(reference)

    def _photos(self, shipment):
        return self.env["dally.ops.photo"].sudo().with_context(
            active_test=False).search([("shipment_id", "=", shipment.id)])

    def _audits(self, action):
        return self.env["dally.ops.audit.event"].sudo().search([
            ("company_id", "=", self.societe.id), ("action", "=", action)])

    def _photo_par_uuid(self, photo_uuid):
        return self.env["dally.ops.photo"].sudo().with_context(
            active_test=False).search([("photo_uuid", "=", photo_uuid)], limit=1)

    # ─── P01 à P04 · les quatre formats ──────────────────────────────

    def test_P01_un_jpeg_est_accepte(self):
        reference = self._creer_dossier()
        resultat = self._ajouter(reference, JPEG_REEL)
        self.assertEqual(resultat["status"], "added")
        self.assertEqual(resultat["photo"]["mime_type"], "image/jpeg")

    def test_P02_un_png_est_accepte(self):
        reference = self._creer_dossier()
        resultat = self._ajouter(reference, PNG_REEL)
        self.assertEqual(resultat["photo"]["mime_type"], "image/png")

    def test_P03_un_webp_est_accepte(self):
        reference = self._creer_dossier()
        resultat = self._ajouter(reference, WEBP_REEL)
        self.assertEqual(resultat["photo"]["mime_type"], "image/webp")

    def test_P04_un_heic_est_accepte_avec_ses_dimensions(self):
        """HEIC est accepté **parce que** ses dimensions sont lisibles.

        Pillow 10.2.0, dans l'image Odoo, n'enregistre aucune extension HEIF :
        l'accepter sans lire `ispe` reviendrait à l'accepter sans contrôle.
        """
        reference = self._creer_dossier()
        resultat = self._ajouter(reference, heic(48, 32))
        self.assertEqual(resultat["photo"]["mime_type"], "image/heic")

    # ─── P05 à P08 · ce que l'envoyeur annonce n'engage que lui ──────

    def test_P05_le_type_est_lu_dans_les_octets_pas_dans_le_nom(self):
        reference = self._creer_dossier()
        resultat = self._ajouter(reference, PNG_REEL, filename="preuve.jpg")
        self.assertEqual(resultat["photo"]["mime_type"], "image/png")

    def test_P06_un_html_renomme_jpg_est_refuse(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, b"<html><body>bonjour</body></html>",
                          filename="photo.jpg")
        self.assertEqual(leve.exception.code, "photo_type_not_allowed")

    def test_P07_un_svg_est_refuse(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference,
                          b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>',
                          filename="photo.jpg")
        self.assertEqual(leve.exception.code, "photo_type_not_allowed")

    def test_P08_un_pdf_est_refuse(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        self.assertEqual(leve.exception.code, "photo_type_not_allowed")

    # ─── P09 à P11 · taille et dimensions ────────────────────────────

    def test_P09_un_fichier_trop_lourd_est_refuse(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, JPEG_REEL + b"\x00" * MAX_FILE_BYTES)
        self.assertEqual(leve.exception.code, "photo_too_large")

    def test_P10_une_image_de_cinquante_millions_de_pixels_est_refusee(self):
        """La bombe de décompression : minuscule sur le disque, énorme en RAM."""
        reference = self._creer_dossier()
        bombe = png(9000, 9000)  # 81 mégapixels, en soixante-dix octets
        self.assertLess(len(bombe), 100)
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, bombe)
        self.assertEqual(leve.exception.code, "photo_dimensions_too_large")

    def test_P11_une_dimension_superieure_a_douze_mille_est_refusee(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, png(20000, 10))
        self.assertEqual(leve.exception.code, "photo_dimensions_too_large")

    def test_P11b_une_image_sans_dimensions_lisibles_est_refusee(self):
        """Ni accepté sans contrôle, ni deviné : refusé."""
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, heic(48, 32)[:20] + b"\x00" * 40)
        self.assertIn(leve.exception.code,
                      ("photo_dimensions_unreadable", "photo_type_not_allowed"))

    # ─── P12 à P15 · portée ──────────────────────────────────────────

    def test_P12_un_dossier_historique_refuse_toute_photo(self):
        self._dossier_ancien("AIR-DSS-CDG-2019-042")
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter("AIR-DSS-CDG-2019-042")
        self.assertEqual(leve.exception.code, "intake_not_found")

    def test_P13_un_dossier_repris_du_tableur_refuse_toute_photo(self):
        dossier = self._dossier_ancien("AIR-DSS-CDG-SHEET-001")
        dossier.sudo().write({"sync_source": "google_sheets",
                              "sync_source_key": "sheet:A002"})
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter("AIR-DSS-CDG-SHEET-001")
        self.assertEqual(leve.exception.code, "intake_not_found")

    def test_P14_un_dossier_d_une_autre_societe_est_invisible(self):
        """La clause de société, isolée.

        Un dossier Ops complet — clé `ops:`, origine back-office, consolidation
        d'entrée — déplacé dans une autre société. Seule la clause de société
        peut alors l'exclure : c'est ce qui rend ce test capable de détecter sa
        disparition.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        self.assertTrue(shipment.sync_source_key.startswith("ops:"))
        self.assertEqual(shipment.sync_source, "backoffice")
        shipment.write({"company_id": self.autre_societe.id})
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference)
        self.assertEqual(leve.exception.code, "intake_not_found")

    def test_P15_un_dossier_annule_refuse_toute_photo(self):
        reference = self._creer_dossier()
        # `goods_received → cancelled` est une transition légale et sans porte
        # métier : le dossier s'annule par le chemin normal.
        self._shipment(reference).sudo().write({"state": "cancelled"})
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference)
        self.assertEqual(leve.exception.code, "photo_state_not_allowed")

    # ─── P16 à P19 · matrice d'états ─────────────────────────────────

    def test_P16_goods_received_accepte(self):
        reference = self._creer_dossier()
        self.assertEqual(self._ajouter(reference)["status"], "added")

    def test_P17_preparing_accepte(self):
        reference = self._creer_dossier()
        self._etat(reference, "preparing")
        self.assertEqual(self._ajouter(reference, kind="preparation")["status"],
                         "added")

    def test_P18_ready_accepte_encore_une_preuve(self):
        """À `ready` les articles sont figés ; la preuve, non.

        C'est le moment où l'emballage terminé se photographie. Aligner la
        photo sur la règle des articles priverait le dossier de la seule image
        qui compte.
        """
        reference = self._creer_dossier()
        self._etat(reference, "ready")
        self.assertEqual(self._ajouter(reference, kind="package")["status"],
                         "added")

    def test_P19_departed_refuse(self):
        reference = self._creer_dossier()
        self._etat(reference, "ready")
        # Le départ porte une gate financière qui n'a rien à voir avec ce qu'on
        # mesure ici : on pose l'état par l'entrée de reprise historique, qui
        # exige d'être Manager — ce qu'est le compte de la classe de test.
        self._shipment(reference).sudo(False)._write_historical_state("departed")
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference)
        self.assertEqual(leve.exception.code, "photo_state_not_allowed")

    def test_P19b_une_nature_inconnue_est_refusee(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, kind="selfie")
        self.assertEqual(leve.exception.code, "photo_kind_invalid")

    # ─── P20 à P24 · rejeu ───────────────────────────────────────────

    def test_P20_le_meme_geste_renvoye_rend_la_meme_photo(self):
        reference = self._creer_dossier()
        geste = str(uuid.uuid4())
        premier = self._ajouter(reference, request_uuid=geste)
        second = self._ajouter(reference, request_uuid=geste)
        self.assertEqual(premier["status"], "added")
        self.assertEqual(second["status"], "replayed")
        self.assertEqual(second["photo"]["photo_uuid"],
                         premier["photo"]["photo_uuid"])

    def test_P21_le_meme_identifiant_sur_un_autre_fichier_est_un_conflit(self):
        reference = self._creer_dossier()
        geste = str(uuid.uuid4())
        self._ajouter(reference, JPEG_REEL, request_uuid=geste)
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, PNG_REEL, request_uuid=geste)
        self.assertEqual(leve.exception.code, "idempotency_conflict")

    def test_P21b_le_meme_identifiant_sur_une_autre_nature_est_un_conflit(self):
        reference = self._creer_dossier()
        geste = str(uuid.uuid4())
        self._ajouter(reference, kind="reception", request_uuid=geste)
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, kind="damage", request_uuid=geste)
        self.assertEqual(leve.exception.code, "idempotency_conflict")

    def test_P22_un_rejeu_ne_cree_pas_une_seconde_photo(self):
        reference = self._creer_dossier()
        geste = str(uuid.uuid4())
        self._ajouter(reference, request_uuid=geste)
        self._ajouter(reference, request_uuid=geste)
        self.assertEqual(len(self._photos(self._shipment(reference))), 1)

    def test_P23_un_rejeu_ne_cree_pas_une_seconde_piece_jointe(self):
        reference = self._creer_dossier()
        geste = str(uuid.uuid4())
        self._ajouter(reference, request_uuid=geste)
        self._ajouter(reference, request_uuid=geste)
        pieces = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", "dally.ops.photo"),
            ("res_id", "in", self._photos(self._shipment(reference)).ids)])
        self.assertEqual(len(pieces), 1)

    def test_P24_un_rejeu_ne_cree_pas_un_second_audit(self):
        reference = self._creer_dossier()
        geste = str(uuid.uuid4())
        avant = len(self._audits("photo_added"))
        self._ajouter(reference, request_uuid=geste)
        self._ajouter(reference, request_uuid=geste)
        self.assertEqual(len(self._audits("photo_added")), avant + 1)

    # ─── P25 à P28 · stockage et frontières ──────────────────────────

    def test_P25_la_piece_jointe_n_est_jamais_publique(self):
        reference = self._creer_dossier()
        self._ajouter(reference)
        photo = self._photos(self._shipment(reference))
        self.assertFalse(photo.attachment_id.sudo().public)

    def test_P26_la_piece_jointe_porte_la_societe_et_son_ancrage(self):
        reference = self._creer_dossier()
        self._ajouter(reference)
        photo = self._photos(self._shipment(reference))
        piece = photo.attachment_id.sudo()
        self.assertEqual(piece.company_id.id, self.societe.id)
        self.assertEqual(piece.res_model, "dally.ops.photo")
        self.assertEqual(piece.res_id, photo.id)

    def test_P27_aucun_document_portail_n_est_cree(self):
        """Une preuve d'exploitation n'a aucun chemin vers le client."""
        reference = self._creer_dossier()
        avant = self.env["dally.portal.document"].sudo().search_count([])
        self._ajouter(reference)
        self.assertEqual(
            self.env["dally.portal.document"].sudo().search_count([]), avant)

    def test_P28_aucune_projection_tableur_et_aucun_evenement_de_suivi(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        outbox_avant = self.env["dally.ops.sheet.outbox"].sudo().search_count([
            ("resource_id", "=", shipment.id)])
        suivi_avant = self.env["dally.shipment.event"].sudo().search_count([
            ("shipment_id", "=", shipment.id)])
        self._ajouter(reference)
        self.assertEqual(
            self.env["dally.ops.sheet.outbox"].sudo().search_count([
                ("resource_id", "=", shipment.id)]), outbox_avant)
        self.assertEqual(
            self.env["dally.shipment.event"].sudo().search_count([
                ("shipment_id", "=", shipment.id)]), suivi_avant)

    # ─── P29 à P31 · quotas ──────────────────────────────────────────

    def test_P29_le_nombre_de_photos_actives_est_plafonne(self):
        reference = self._creer_dossier()
        for index in range(MAX_ACTIVE_PHOTOS):
            self._ajouter(reference, JPEG_REEL + bytes([index % 251]))
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, JPEG_REEL + b"\xfe")
        self.assertEqual(leve.exception.code, "photo_quota_active")

    def test_P30_les_photos_retirees_comptent_dans_le_plafond_conserve(self):
        """Sans cela, ajouter et retirer en boucle contournerait la limite."""
        reference = self._creer_dossier()
        for index in range(MAX_RETAINED_PHOTOS):
            resultat = self._ajouter(reference, JPEG_REEL + bytes([index % 251]))
            if index >= MAX_ACTIVE_PHOTOS - 1:
                self._supprimer(reference, resultat["photo"]["photo_uuid"])
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, JPEG_REEL + b"\xfd")
        self.assertEqual(leve.exception.code, "photo_quota_retained")

    def test_P31_le_volume_conserve_est_plafonne(self):
        """Le plafond d'octets se mesure sur la somme réellement stockée."""
        reference = self._creer_dossier()
        self._ajouter(reference)
        # La règle vit dans `_motif_quota`, que l'écriture et l'affichage
        # appellent tous deux : c'est là qu'elle se vérifie.
        source = __import__("inspect").getsource(
            type(self.env["dally.ops.photo.service"])._motif_quota)
        self.assertIn("MAX_RETAINED_BYTES", source)
        self.assertIn("file_size", source)
        with patch(
            "odoo.addons.dally_ops_mobile.models.ops_photo_service"
            ".MAX_RETAINED_BYTES", 1,
        ):
            with self.assertRaises(DallyOpsError) as leve:
                self._ajouter(reference, JPEG_REEL + b"\x01")
        self.assertEqual(leve.exception.code, "photo_quota_bytes")

    # ─── P32 à P36 · retrait ─────────────────────────────────────────

    def test_P32_un_logisticien_retire_sa_propre_photo(self):
        reference = self._creer_dossier()
        photo = self._ajouter(reference)["photo"]
        resultat = self._supprimer(reference, photo["photo_uuid"])
        self.assertEqual(resultat["status"], "deleted")
        self.assertEqual(self._lister(reference)["photos"], [])

    def test_P33_un_logisticien_ne_retire_pas_la_photo_d_un_collegue(self):
        reference = self._creer_dossier()
        photo = self._ajouter(reference, utilisateur=self.gilles)["photo"]
        with self.assertRaises(DallyOpsError) as leve:
            self._supprimer(reference, photo["photo_uuid"],
                            utilisateur=self.mariama)
        self.assertEqual(leve.exception.code, "photo_delete_not_allowed")

    def test_P34_un_logisticien_ne_retire_plus_rien_a_ready(self):
        reference = self._creer_dossier()
        photo = self._ajouter(reference)["photo"]
        self._etat(reference, "ready")
        with self.assertRaises(DallyOpsError) as leve:
            self._supprimer(reference, photo["photo_uuid"])
        self.assertEqual(leve.exception.code, "photo_delete_not_allowed")

    def test_P35_un_responsable_retire_a_ready_la_photo_d_un_autre(self):
        reference = self._creer_dossier()
        photo = self._ajouter(reference, utilisateur=self.gilles)["photo"]
        self._etat(reference, "ready")
        resultat = self._supprimer(reference, photo["photo_uuid"],
                                   utilisateur=self.responsable)
        self.assertEqual(resultat["status"], "deleted")

    def test_P36_le_retrait_conserve_la_piece_jointe_et_son_auteur(self):
        reference = self._creer_dossier()
        photo = self._ajouter(reference)["photo"]
        piece_avant = self._photos(self._shipment(reference)).attachment_id
        self._supprimer(reference, photo["photo_uuid"])
        enregistrement = self._photos(self._shipment(reference))
        self.assertFalse(enregistrement.active)
        self.assertTrue(enregistrement.deleted_at)
        self.assertEqual(enregistrement.deleted_by_user_id.id, self.gilles.id)
        self.assertEqual(enregistrement.attachment_id.id, piece_avant.id)
        self.assertTrue(enregistrement.attachment_id.sudo().exists())

    # ─── P37 à P39 · ce qu'on ne voit plus, et ce qu'on ne voit pas ──

    def test_P37_une_photo_retiree_disparait_de_la_liste(self):
        reference = self._creer_dossier()
        photo = self._ajouter(reference)["photo"]
        self._ajouter(reference, PNG_REEL, kind="package")
        self._supprimer(reference, photo["photo_uuid"])
        restantes = [p["photo_uuid"] for p in self._lister(reference)["photos"]]
        self.assertNotIn(photo["photo_uuid"], restantes)
        self.assertEqual(len(restantes), 1)

    def test_P38_une_photo_retiree_n_est_plus_lisible(self):
        reference = self._creer_dossier()
        photo = self._ajouter(reference)["photo"]
        self._supprimer(reference, photo["photo_uuid"])
        with self.assertRaises(DallyOpsError) as leve:
            self._service().read_photo(reference, photo["photo_uuid"])
        self.assertEqual(leve.exception.code, "photo_not_found")

    def test_P39_une_photo_d_un_autre_dossier_repond_introuvable(self):
        premier = self._creer_dossier()
        second = self._creer_dossier()
        photo = self._ajouter(premier)["photo"]
        with self.assertRaises(DallyOpsError) as leve:
            self._service().read_photo(second, photo["photo_uuid"])
        self.assertEqual(leve.exception.code, "photo_not_found")

    # ─── P40 à P44 · contrat, auteur, rejeu du retrait, verrou ───────

    def test_P40_le_contrat_ne_publie_aucun_identifiant_technique(self):
        reference = self._creer_dossier()
        self._ajouter(reference)
        rendu = str(self._lister(reference))
        photo = self._photos(self._shipment(reference))
        for interdit in ("attachment_id", "res_id", "res_model", "user_id",
                         "company_id", "store_fname", "checksum", "datas",
                         "/web/content", "filename", "shipment_id"):
            self.assertNotIn(interdit, rendu, interdit)
        self.assertNotIn(str(photo.attachment_id.id), rendu)
        dto = self._lister(reference)["photos"][0]
        self.assertEqual(set(dto), {
            "photo_uuid", "kind", "mime_type", "created_at", "created_by",
            "can_delete"})

    def test_P41_l_auteur_vient_du_serveur_pas_de_la_demande(self):
        reference = self._creer_dossier()
        resultat = self._ajouter(reference, utilisateur=self.mariama)
        self.assertEqual(resultat["photo"]["created_by"], self.mariama.name)
        self.assertEqual(
            self._photos(self._shipment(reference)).operator_user_id.id,
            self.mariama.id)

    def test_P42_le_retrait_rejoue_reste_stable(self):
        reference = self._creer_dossier()
        photo = self._ajouter(reference)["photo"]
        geste = str(uuid.uuid4())
        premier = self._supprimer(reference, photo["photo_uuid"], request_uuid=geste)
        second = self._supprimer(reference, photo["photo_uuid"], request_uuid=geste)
        self.assertEqual(premier["status"], "deleted")
        self.assertEqual(second["status"], "replayed")
        self.assertEqual(len(self._audits("photo_deleted")), 1)

    def test_P43_un_retrait_au_meme_identifiant_sur_une_autre_photo_est_un_conflit(self):
        reference = self._creer_dossier()
        premiere = self._ajouter(reference, JPEG_REEL)["photo"]
        seconde = self._ajouter(reference, PNG_REEL, kind="package")["photo"]
        geste = str(uuid.uuid4())
        self._supprimer(reference, premiere["photo_uuid"], request_uuid=geste)
        with self.assertRaises(DallyOpsError) as leve:
            self._supprimer(reference, seconde["photo_uuid"], request_uuid=geste)
        self.assertEqual(leve.exception.code, "idempotency_conflict")

    def test_P44_le_verrou_du_dossier_precede_le_comptage_des_quotas(self):
        """L'ordre est la garantie, et il se mesure.

        Deux envois simultanés compteraient les mêmes dix-neuf photos et
        écriraient chacun la vingtième. La ligne du dossier doit être prise
        **avant** le comptage — pas après, pas pendant.

        La sentinelle prouve l'ordre ; le second contrôle épingle la primitive,
        qu'un corps vidé de sa clause bloquante rendrait inopérante sans que la
        sentinelle s'en aperçoive.
        """
        import inspect
        import re

        reference = self._creer_dossier()
        service = type(self.env["dally.ops.photo.service"])

        sentinelle = RuntimeError("verrou de dossier atteint")
        with patch.object(service, "_verrouiller_dossier", side_effect=sentinelle):
            with self.assertRaises(RuntimeError) as leve:
                self._ajouter(reference)
        self.assertIs(leve.exception, sentinelle)

        source = re.sub(
            r"\s+", " ", inspect.getsource(service._verrouiller_dossier)).upper()
        self.assertIn("FOR UPDATE", source,
                      "le verrou de dossier ne verrouille plus rien")
        self.assertIn("FROM DALLY_SHIPMENT", source)
        self.assertLess(source.index("FROM DALLY_SHIPMENT"),
                        source.index("FOR UPDATE"))

    # ─── P45 à P48 · identité de la trace et plafonds annoncés ───────

    def test_P45_l_evenement_d_ajout_designe_la_photo_pas_le_dossier(self):
        """`entity_res_id` doit désigner l'enregistrement que `entity_model` nomme.

        Y poser l'identifiant du dossier ferait pointer la trace vers une photo
        qui n'a rien à voir — celle dont la clé primaire vaut celle du
        dossier — et une reprise d'audit se tromperait de pièce.
        """
        reference = self._creer_dossier()
        dto = self._ajouter(reference)["photo"]
        photo = self._photo_par_uuid(dto["photo_uuid"])
        shipment = self._shipment(reference)

        evenements = self._audits("photo_added")
        self.assertEqual(len(evenements), 1)
        self.assertEqual(evenements.entity_model, "dally.ops.photo")
        self.assertEqual(evenements.entity_res_id, photo.id)
        self.assertEqual(evenements.shipment_id.id, shipment.id)
        # Et le dossier n'est pas confondu avec la photo.
        self.assertNotEqual(evenements.entity_res_id, shipment.id)

    def test_P46_l_evenement_de_retrait_designe_aussi_la_photo(self):
        reference = self._creer_dossier()
        dto = self._ajouter(reference)["photo"]
        photo = self._photo_par_uuid(dto["photo_uuid"])
        shipment = self._shipment(reference)
        self._supprimer(reference, dto["photo_uuid"])

        evenements = self._audits("photo_deleted")
        self.assertEqual(len(evenements), 1)
        self.assertEqual(evenements.entity_model, "dally.ops.photo")
        self.assertEqual(evenements.entity_res_id, photo.id)
        self.assertEqual(evenements.shipment_id.id, shipment.id)
        self.assertNotEqual(evenements.entity_res_id, shipment.id)

    def test_P47_deux_photos_laissent_deux_traces_distinctes(self):
        """Un événement par geste, et chacun sur sa propre pièce."""
        reference = self._creer_dossier()
        premiere = self._photo_par_uuid(
            self._ajouter(reference, JPEG_REEL)["photo"]["photo_uuid"])
        seconde = self._photo_par_uuid(
            self._ajouter(reference, PNG_REEL, kind="package")["photo"]["photo_uuid"])

        cibles = self._audits("photo_added").mapped("entity_res_id")
        self.assertEqual(sorted(cibles), sorted([premiere.id, seconde.id]))

    def test_P48_can_add_tombe_quand_le_plafond_conserve_est_atteint(self):
        """L'écran ne doit pas proposer ce que le serveur refusera.

        On atteint le plafond des conservées par le seul chemin qui le permet
        sans jamais dépasser celui des actives : ajouter puis retirer. Les
        photos retirées comptent toujours — c'est justement ce qui empêche la
        boucle — et `can_add` doit le dire.
        """
        reference = self._creer_dossier()
        for index in range(MAX_RETAINED_PHOTOS):
            resultat = self._ajouter(reference, JPEG_REEL + bytes([index % 251]))
            if index >= MAX_ACTIVE_PHOTOS - 1:
                self._supprimer(reference, resultat["photo"]["photo_uuid"])

        detail = self._lister(reference)
        self.assertFalse(detail["can_add"])
        # Et le refus annoncé est bien celui que l'écriture prononce.
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, JPEG_REEL + b"\xfc")
        self.assertEqual(leve.exception.code, "photo_quota_retained")

    def test_P48b_can_add_tombe_aussi_sur_le_volume_conserve(self):
        reference = self._creer_dossier()
        self._ajouter(reference)
        self.assertTrue(self._lister(reference)["can_add"])
        with patch(
            "odoo.addons.dally_ops_mobile.models.ops_photo_service"
            ".MAX_RETAINED_BYTES", 1,
        ):
            self.assertFalse(self._lister(reference)["can_add"])

    def test_P48c_can_add_et_le_refus_lisent_la_meme_regle(self):
        """Une seule formulation : l'affichage appelle ce que l'écriture lève."""
        import inspect
        service = type(self.env["dally.ops.photo.service"])
        propose = inspect.getsource(service._peut_ajouter)
        exige = inspect.getsource(service._exiger_quotas)
        self.assertIn("_motif_quota", propose)
        self.assertIn("_motif_quota", exige)
        # Aucun plafond recopié dans la fonction d'affichage.
        for plafond in ("MAX_ACTIVE_PHOTOS", "MAX_RETAINED_PHOTOS",
                        "MAX_RETAINED_BYTES"):
            self.assertNotIn(plafond, propose, plafond)

    # ─── H01 à H12 · conteneurs ISOBMFF adversariaux ─────────────────

    def _refus_heic(self, contenu, reference=None):
        reference = reference or self._creer_dossier()
        with self.assertRaises(DallyOpsError) as leve:
            self._ajouter(reference, contenu)
        return leve.exception

    def test_H01_plusieurs_ispe_sont_toutes_relevees(self):
        """Une vignette et une image principale : le conteneur reste valide."""
        reference = self._creer_dossier()
        resultat = self._ajouter(reference, heic_ispe((32, 32), (48, 64)))
        self.assertEqual(resultat["status"], "added")

    def test_H02_une_vignette_sage_ne_couvre_pas_une_image_enorme(self):
        """Le piège que « faire confiance au premier ispe » laisserait passer.

        Trente pixels annoncés d'abord, soixante mille ensuite : mesuré sur la
        première boîte, le fichier passerait ; stocké, il vaudrait des
        gigaoctets une fois décodé.
        """
        erreur = self._refus_heic(heic_ispe((30, 30), (60000, 60000)))
        self.assertEqual(erreur.code, "photo_dimensions_too_large")

    def test_H02b_le_pire_cas_est_pris_dimension_par_dimension(self):
        """20000 × 1 puis 1 × 20000 : aucune n'excède en surface, les deux en côté."""
        erreur = self._refus_heic(heic_ispe((20000, 1), (1, 20000)))
        self.assertEqual(erreur.code, "photo_dimensions_too_large")

    def test_H03_une_taille_de_boite_32_bits_impossible_est_refusee(self):
        conteneur = bytearray(heic(48, 32))
        conteneur[0:4] = struct.pack(">I", 3)  # plus petite que son en-tête
        erreur = self._refus_heic(bytes(conteneur))
        self.assertEqual(erreur.code, "photo_dimensions_unreadable")

    def test_H04_une_taille_etendue_64_bits_tronquee_est_refusee(self):
        conteneur = bytearray(heic(48, 32))
        conteneur[0:4] = struct.pack(">I", 1)  # annonce une taille 64 bits…
        erreur = self._refus_heic(bytes(conteneur[:12]) + b"\x00" * 4)
        self.assertEqual(erreur.code, "photo_dimensions_unreadable")

    def test_H05_une_boite_qui_deborde_du_fichier_est_refusee(self):
        conteneur = bytearray(heic(48, 32))
        conteneur[0:4] = struct.pack(">I", len(conteneur) + 4096)
        erreur = self._refus_heic(bytes(conteneur))
        self.assertEqual(erreur.code, "photo_dimensions_unreadable")

    def test_H06_une_imbrication_excessive_est_refusee(self):
        corps = _boite(b"ispe", b"\x00\x00\x00\x00" + struct.pack(">II", 48, 32))
        for _niveau in range(12):
            corps = _boite(b"ipco", corps)
        meta = _boite(b"meta", b"\x00\x00\x00\x00" + _boite(b"iprp", corps))
        conteneur = _boite(b"ftyp", b"heic" + b"\x00" * 4 + b"heic") + meta
        erreur = self._refus_heic(conteneur)
        self.assertEqual(erreur.code, "photo_dimensions_unreadable")

    def test_H07_un_parcours_excessif_est_borne(self):
        """Dix mille boîtes vides : le lecteur s'arrête, il ne rame pas."""
        remplissage = b"".join(_boite(b"free", b"") for _ in range(10000))
        conteneur = (_boite(b"ftyp", b"heic" + b"\x00" * 4 + b"heic")
                     + remplissage
                     + heic(48, 32)[len(_boite(b"ftyp", b"heic" + b"\x00" * 4 + b"heic")):])
        erreur = self._refus_heic(conteneur)
        self.assertEqual(erreur.code, "photo_dimensions_unreadable")

    def test_H08_une_taille_nulle_imbriquee_est_refusee(self):
        """« Jusqu'à la fin du fichier » n'a de sens qu'à la racine."""
        ispe = _boite(b"ispe", b"\x00\x00\x00\x00" + struct.pack(">II", 48, 32))
        ipco = bytearray(_boite(b"ipco", ispe))
        ipco[0:4] = struct.pack(">I", 0)
        meta = _boite(b"meta", b"\x00\x00\x00\x00" + _boite(b"iprp", bytes(ipco)))
        conteneur = _boite(b"ftyp", b"heic" + b"\x00" * 4 + b"heic") + meta
        erreur = self._refus_heic(conteneur)
        self.assertEqual(erreur.code, "photo_dimensions_unreadable")

    def test_H09_un_conteneur_tronque_est_refuse(self):
        erreur = self._refus_heic(heic(48, 32)[:-6])
        self.assertEqual(erreur.code, "photo_dimensions_unreadable")

    def test_H09b_un_conteneur_sans_ispe_est_refuse(self):
        conteneur = (_boite(b"ftyp", b"heic" + b"\x00" * 4 + b"heic")
                     + _boite(b"meta", b"\x00" * 4)
                     + _boite(b"mdat", b"\x00" * 8))
        erreur = self._refus_heic(conteneur)
        self.assertEqual(erreur.code, "photo_dimensions_unreadable")

    def test_H10_une_dimension_nulle_est_refusee(self):
        erreur = self._refus_heic(heic_ispe((0, 32)))
        self.assertEqual(erreur.code, "photo_dimensions_unreadable")

    def test_H11_la_surface_au_dela_de_cinquante_megapixels_est_refusee(self):
        erreur = self._refus_heic(heic_ispe((10000, 6000)))
        self.assertEqual(erreur.code, "photo_dimensions_too_large")

    def test_H12_un_cote_au_dela_de_douze_mille_est_refuse(self):
        erreur = self._refus_heic(heic_ispe((12001, 10)))
        self.assertEqual(erreur.code, "photo_dimensions_too_large")

    # ─── Rôle ────────────────────────────────────────────────────────

    def test_un_compte_sans_role_ops_est_refuse(self):
        from odoo.exceptions import AccessError
        reference = self._creer_dossier()
        with self.assertRaises(AccessError):
            self._ajouter(reference, utilisateur=self.temoin)

    def test_la_capacite_photo_est_ouverte_aux_deux_roles(self):
        for compte in (self.gilles, self.responsable):
            capacites = (self.env["res.users"].with_user(compte)
                         ._dally_ops_capabilities())
            self.assertTrue(capacites["photo_manage"], compte.name)
