# -*- coding: utf-8 -*-
"""Le ciblage de facture du endpoint paiement, par HTTP réel.

## Pourquoi ce fichier existe

Le premier jeu de tests du complément appelait `upsert_from_sync` au niveau
modèle. Il passait au vert alors que `POST /api/v1/freight/payment` rejetait
`invoice_id` en `422 unknown_fields` : le champ manquait dans `ALLOWED_FIELDS`,
et la validation du contrôleur s'exécute bien avant la logique de ciblage.

Un test modèle ne pouvait pas voir ce défaut. Celui-ci passe par la pile HTTP
complète, avec l'utilisateur d'intégration et ses ACL réelles — c'est aussi ce
qui a révélé que la traversée facture → commande → colis rend une liste vide
sans `sudo`, l'utilisateur d'intégration ne lisant pas `sale.order.line`.
"""

import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightPaymentSupplementEndpoint(HttpCase):

    ENDPOINT = "/api/v1/freight/payment"

    def setUp(self):
        super().setUp()
        self.key = self.env["dally.api.key"].create({
            "name": "Freight Supplement Payment Key",
            "scopes": "freight:payment",
            "allowed_ips": "",
            "user_id": self.env.ref(
                "dally_freight_billing.user_dally_freight_billing_integration").id,
        })
        self.raw_key = self.key.key_to_display
        self.env.ref("base.EUR").active = True
        self.Sync = self.env["dally.freight.sync.service"]

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def _payload_sync(self, reference, index, weight, phone, nom):
        return {
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
            "source": "google_sheets",
            "goods_received_on": "2026-08-21",
            "customer_segment": "individual",
            "client": {
                "name": nom,
                "email": "%s@example.invalid" % reference.lower(),
                "phone": phone,
            },
            "lines": [{
                "external_line_key": "%s|A|%s" % (reference, index),
                "description": "Article %s" % index,
                "quantity": 1,
                "exact_weight_kg": weight,
                "billing_method": "real",
                "tariff_family_code": "food",
            }],
        }

    def _dossier(self, reference, phone="+221 77 000 00 00", nom="HTTP Sup Customer"):
        _d, shipment = self.Sync.upsert(
            self._payload_sync(reference, 1, 10.0, phone, nom))
        invoice = shipment.action_prepare_native_freight_invoice()
        invoice.action_post()
        return shipment, invoice

    def _complement(self, shipment, reference):
        self.Sync.upsert(self._payload_sync(
            reference, 2, 6.0, "+221 77 000 00 00", "HTTP Sup Customer"))
        supplement, _created, _kind = shipment._prepare_freight_invoice()
        return supplement

    def _post(self, **overrides):
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "external_payment_key": "HSUP-%s" % str(uuid.uuid4()),
            "amount": 6.0,
            "currency_code": "EUR",
            "payment_date": "2026-09-04",
            "payment_method": "wave",
            "source": "google_sheets",
        }
        payload.update(overrides)
        return self.url_open(
            self.ENDPOINT,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json", "X-API-Key": self.raw_key},
            timeout=30,
        )

    @staticmethod
    def _erreur(response):
        return response.json()["error"]["code"]

    @staticmethod
    def _data(response):
        return response.json()["data"]

    # ------------------------------------------------------------------
    # A — sans cible : le comportement historique, intact
    # ------------------------------------------------------------------

    def test_a_payment_without_invoice_id_targets_the_primary(self):
        shipment, principale = self._dossier("HTTPSUP-A")
        response = self._post(shipment_id=shipment.id)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self._data(response)["invoice_id"], principale.id)

    # ------------------------------------------------------------------
    # B — la cible complémentaire, acceptée par HTTP
    # ------------------------------------------------------------------

    def test_a_payment_can_target_a_supplement_over_http(self):
        """Le champ doit franchir `ALLOWED_FIELDS`, pas seulement exister."""
        shipment, principale = self._dossier("HTTPSUP-B")
        supplement = self._complement(shipment, "HTTPSUP-B")

        response = self._post(shipment_id=shipment.id, invoice_id=supplement.id)

        self.assertEqual(response.status_code, 201)
        data = self._data(response)
        self.assertEqual(data["invoice_id"], supplement.id)
        self.assertNotEqual(data["invoice_id"], principale.id)
        collection = self.env["dally.freight.collection"].browse(data["collection_id"])
        self.assertEqual(collection.target_invoice_id, supplement)
        self.assertEqual(collection.invoice_id, principale,
                         "le lien historique vers la principale reste intact")

    def test_invoice_id_is_not_rejected_as_an_unknown_field(self):
        """Le défaut exact qui avait échappé : 422 unknown_fields."""
        shipment, principale = self._dossier("HTTPSUP-KNOWN")
        response = self._post(shipment_id=shipment.id, invoice_id=principale.id)
        self.assertNotEqual(response.status_code, 422)
        self.assertEqual(response.status_code, 201)

    # ------------------------------------------------------------------
    # C à F — tout ce qui ne doit jamais être ciblé
    # ------------------------------------------------------------------

    def test_an_invoice_of_another_shipment_is_rejected(self):
        shipment, _principale = self._dossier("HTTPSUP-C1")
        _autre, autre_facture = self._dossier("HTTPSUP-C2")
        response = self._post(shipment_id=shipment.id, invoice_id=autre_facture.id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._erreur(response), "invoice_shipment_mismatch")

    def test_a_missing_invoice_is_rejected(self):
        shipment, _principale = self._dossier("HTTPSUP-D")
        response = self._post(shipment_id=shipment.id, invoice_id=99999999)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._erreur(response), "invoice_not_found")

    def test_a_non_customer_invoice_is_rejected(self):
        shipment, _principale = self._dossier("HTTPSUP-E")
        fournisseur = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": shipment.partner_id.id,
            "invoice_date": "2026-09-04",
        })
        response = self._post(shipment_id=shipment.id, invoice_id=fournisseur.id)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._erreur(response), "invalid_invoice_type")

    def test_an_invoice_of_another_customer_is_rejected(self):
        shipment, _principale = self._dossier("HTTPSUP-F1")
        _autre, autre_facture = self._dossier(
            "HTTPSUP-F2", phone="+221 78 111 22 33", nom="Client Different")
        self.assertNotEqual(autre_facture.partner_id, shipment.partner_id)
        response = self._post(shipment_id=shipment.id, invoice_id=autre_facture.id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._erreur(response), "invoice_partner_mismatch")

    def test_a_malformed_invoice_id_is_rejected(self):
        shipment, _principale = self._dossier("HTTPSUP-BAD")
        response = self._post(shipment_id=shipment.id, invoice_id="pas-un-entier")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._erreur(response), "invalid_invoice_id")

    # ------------------------------------------------------------------
    # G et H — le rejeu
    # ------------------------------------------------------------------

    def test_a_retry_with_the_same_key_and_target_creates_no_duplicate(self):
        shipment, _principale = self._dossier("HTTPSUP-G")
        supplement = self._complement(shipment, "HTTPSUP-G")
        cle = "HSUP-G-STABLE"

        premier = self._post(shipment_id=shipment.id, invoice_id=supplement.id,
                             external_payment_key=cle)
        second = self._post(shipment_id=shipment.id, invoice_id=supplement.id,
                            external_payment_key=cle)

        self.assertEqual(premier.status_code, 201)
        self.assertTrue(self._data(premier)["created"])
        self.assertEqual(second.status_code, 200)
        self.assertFalse(self._data(second)["created"])
        self.assertEqual(self._data(second)["collection_id"],
                         self._data(premier)["collection_id"])
        self.assertEqual(self.env["dally.freight.collection"].search_count([
            ("external_payment_key", "=", cle)]), 1)

    def test_a_pending_collection_may_be_retargeted_but_a_registered_one_may_not(self):
        """Tant que rien n'est comptabilisé, corriger la cible reste permis.

        C'est le même contrat que pour le montant ou le dossier : la garde ne
        se ferme qu'une fois l'encaissement rattaché à un paiement, parce qu'à
        partir de là le déplacer bougerait de l'argent entre deux pièces sans
        écriture pour le dire.
        """
        shipment, principale = self._dossier("HTTPSUP-H")
        supplement = self._complement(shipment, "HTTPSUP-H")
        cle = "HSUP-H-STABLE"

        self._post(shipment_id=shipment.id, invoice_id=supplement.id,
                   external_payment_key=cle)
        redirige = self._post(shipment_id=shipment.id, invoice_id=principale.id,
                              external_payment_key=cle)

        self.assertEqual(redirige.status_code, 200)
        collection = self.env["dally.freight.collection"].browse(
            self._data(redirige)["collection_id"])
        self.assertEqual(collection.target_invoice_id, principale)

        journal = self.env["account.journal"].sudo().search(
            [("type", "=", "bank")], limit=1)
        if not journal:
            self.skipTest("aucun journal de banque disponible")
        paiement = self.env["account.payment"].sudo().create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": shipment.partner_id.id,
            "amount": 6.0,
            "journal_id": journal.id,
            "company_id": journal.company_id.id,
        })
        collection.sudo().write({"payment_id": paiement.id})
        # Le handler HTTP relit la base : sans vidage, `payment_id` resterait
        # dans le cache ORM du test et la garde ne verrait rien a proteger.
        self.env.flush_all()

        fige = self._post(shipment_id=shipment.id, invoice_id=supplement.id,
                          external_payment_key=cle)
        self.assertGreaterEqual(fige.status_code, 400)
        self.assertEqual(collection.target_invoice_id, principale)

    # ------------------------------------------------------------------
    # Absent, renseigné, vidé — trois états, pas deux
    # ------------------------------------------------------------------

    def _collection_ciblant_le_supplement(self, reference, cle):
        shipment, principale = self._dossier(reference)
        supplement = self._complement(shipment, reference)
        premier = self._post(shipment_id=shipment.id, invoice_id=supplement.id,
                             external_payment_key=cle)
        self.assertEqual(premier.status_code, 201)
        collection = self.env["dally.freight.collection"].browse(
            self._data(premier)["collection_id"])
        self.assertEqual(collection.target_invoice_id, supplement)
        return shipment, principale, supplement, collection

    def test_an_absent_invoice_id_leaves_the_existing_target_alone(self):
        """TEST A — la clé absente ne dit rien, donc ne change rien."""
        cle = "HSUP-ABSENT"
        shipment, _principale, supplement, collection = \
            self._collection_ciblant_le_supplement("HTTPSUP-ABS", cle)

        rejeu = self._post(shipment_id=shipment.id, external_payment_key=cle)

        self.assertEqual(rejeu.status_code, 200)
        self.assertFalse(self._data(rejeu)["created"])
        self.assertEqual(self._data(rejeu)["collection_id"], collection.id)
        self.assertEqual(collection.target_invoice_id, supplement,
                         "un rejeu muet ne doit pas retargeter")
        self.assertEqual(self.env["dally.freight.collection"].search_count(
            [("external_payment_key", "=", cle)]), 1)

    def test_an_empty_invoice_id_resets_the_target_to_the_primary(self):
        """TEST B — la clé vide est une instruction : « efface la cible »."""
        cle = "HSUP-VIDE"
        shipment, principale, _supplement, collection = \
            self._collection_ciblant_le_supplement("HTTPSUP-VIDE", cle)

        remise = self._post(shipment_id=shipment.id, invoice_id="",
                            external_payment_key=cle)

        self.assertEqual(remise.status_code, 200)
        self.assertFalse(self._data(remise)["created"])
        self.assertFalse(collection.target_invoice_id,
                         "la cible doit être effacée, pas conservée")
        self.assertEqual(self._data(remise)["invoice_id"], principale.id,
                         "la réponse expose désormais la principale")
        self.assertEqual(self.env["dally.freight.collection"].search_count(
            [("external_payment_key", "=", cle)]), 1)

    def test_an_empty_invoice_id_on_a_primary_collection_stays_primary(self):
        """TEST C — effacer une cible déjà primaire ne casse rien."""
        shipment, principale = self._dossier("HTTPSUP-VIDE2")
        cle = "HSUP-VIDE2"
        premier = self._post(shipment_id=shipment.id, invoice_id=principale.id,
                             external_payment_key=cle)
        self.assertEqual(premier.status_code, 201)
        collection = self.env["dally.freight.collection"].browse(
            self._data(premier)["collection_id"])

        remise = self._post(shipment_id=shipment.id, invoice_id="",
                            external_payment_key=cle)

        self.assertEqual(remise.status_code, 200)
        self.assertFalse(collection.target_invoice_id)
        self.assertEqual(self._data(remise)["invoice_id"], principale.id)

    def test_clearing_the_target_of_a_registered_collection_is_refused(self):
        """TEST D — l'immuabilité protège aussi l'effacement."""
        cle = "HSUP-FIGE"
        shipment, _principale, supplement, collection = \
            self._collection_ciblant_le_supplement("HTTPSUP-FIGE", cle)

        journal = self.env["account.journal"].sudo().search(
            [("type", "=", "bank")], limit=1)
        if not journal:
            self.skipTest("aucun journal de banque disponible")
        paiement = self.env["account.payment"].sudo().create({
            "payment_type": "inbound", "partner_type": "customer",
            "partner_id": shipment.partner_id.id, "amount": 6.0,
            "journal_id": journal.id, "company_id": journal.company_id.id,
        })
        collection.sudo().write({"payment_id": paiement.id})
        self.env.flush_all()

        efface = self._post(shipment_id=shipment.id, invoice_id="",
                            external_payment_key=cle)

        self.assertGreaterEqual(efface.status_code, 400)
        self.assertEqual(collection.target_invoice_id, supplement,
                         "la cible d'un encaissement comptabilisé ne s'efface pas")

    # ------------------------------------------------------------------
    # Une pièce annulée n'est jamais une cible
    # ------------------------------------------------------------------

    def test_a_cancelled_primary_invoice_is_refused(self):
        """TEST E — annulée, elle ne sera jamais comptabilisée."""
        shipment, principale = self._dossier("HTTPSUP-CANC1")
        principale.button_draft()
        principale.button_cancel()
        self.assertEqual(principale.state, "cancel")

        response = self._post(shipment_id=shipment.id, invoice_id=principale.id)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._erreur(response), "invoice_cancelled")

    def test_a_cancelled_supplement_invoice_is_refused(self):
        """TEST F — même verdict pour une pièce complémentaire."""
        shipment, _principale = self._dossier("HTTPSUP-CANC2")
        supplement = self._complement(shipment, "HTTPSUP-CANC2")
        supplement.button_cancel()
        self.assertEqual(supplement.state, "cancel")

        response = self._post(shipment_id=shipment.id, invoice_id=supplement.id)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._erreur(response), "invoice_cancelled")

    def test_a_draft_supplement_invoice_is_still_accepted(self):
        """TEST G — le brouillon reste ouvert : `action_post` réveillera l'encaissement."""
        shipment, _principale = self._dossier("HTTPSUP-DRAFT")
        supplement = self._complement(shipment, "HTTPSUP-DRAFT")
        self.assertEqual(supplement.state, "draft")

        response = self._post(shipment_id=shipment.id, invoice_id=supplement.id)

        self.assertEqual(response.status_code, 201)
        collection = self.env["dally.freight.collection"].browse(
            self._data(response)["collection_id"])
        self.assertEqual(collection.target_invoice_id, supplement)
        self.assertEqual(collection.state, "pending")

    def test_a_posted_supplement_invoice_is_still_accepted(self):
        """TEST H — et le comportement d'une pièce comptabilisée ne bouge pas."""
        shipment, _principale = self._dossier("HTTPSUP-POSTED")
        supplement = self._complement(shipment, "HTTPSUP-POSTED")
        supplement.action_post()
        self.assertEqual(supplement.state, "posted")

        response = self._post(shipment_id=shipment.id, invoice_id=supplement.id)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self._data(response)["invoice_id"], supplement.id)

    # ------------------------------------------------------------------
    # Le réveil après comptabilisation du complément
    # ------------------------------------------------------------------

    def test_posting_the_supplement_wakes_only_its_own_collections(self):
        shipment, principale = self._dossier("HTTPSUP-POST")
        supplement = self._complement(shipment, "HTTPSUP-POST")
        self.assertFalse(supplement.dally_freight_shipment_id,
                         "un complément ne porte pas ce lien")

        response = self._post(shipment_id=shipment.id, invoice_id=supplement.id)
        collection = self.env["dally.freight.collection"].browse(
            self._data(response)["collection_id"])
        self.assertEqual(collection.state, "pending")

        supplement.action_post()

        self.assertEqual(collection.target_invoice_id, supplement)
        self.assertNotEqual(collection.target_invoice_id, principale)
        self.assertNotIn("post", (collection.error_message or "").lower(),
                         "le motif ne doit plus être l'attente de comptabilisation")
