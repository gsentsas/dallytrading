# -*- coding: utf-8 -*-
"""Le complément de fret après facture principale comptabilisée.

## Le cas que ces tests protègent

De la marchandise arrive **après** l'émission de la facture. Le colis est réel,
il partira avec le départ, et le refuser laisserait la base plus fausse que la
facture ne l'était. Mais la pièce comptabilisée, elle, ne se réécrit pas.

La sortie est donc un second document : une commande et une facture brouillon
qui ne portent **que** les colis arrivés depuis. La facture principale reste
identique au centime près, et les anciens colis restent immuables.

## Ce que ces tests refusent aussi

Que l'exception devienne une porte. Une facture principale encore en brouillon
n'ouvre rien — la réinitialiser reste le bon geste. Une création ORM ordinaire
n'ouvre rien non plus. Et tant qu'un complément brouillon existe, la
marchandise suivante attend : un brouillon fige un périmètre que Finance a
sous les yeux.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.dally_freight_billing.models.billing_lock import (
    SUPPLEMENT_PRICING_CONTEXT,
)


@tagged("post_install", "-at_install", "dally")
class TestFreightPostedInvoiceSupplement(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # `AccountTestInvoicingCommon` tourne avec son propre utilisateur
        # comptable : il porte les droits de facturation, aucun des ACL Freight.
        # On ajoute donc les seuls rôles dont ce scénario a besoin, dans la
        # fixture transactionnelle — les ACL du module et les utilisateurs
        # d'intégration ne sont pas touchés.
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.eur = cls.setup_other_currency("EUR")
        cls.Sync = cls.env["dally.freight.sync.service"]
        cls.Package = cls.env["dally.shipment.package"]

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def _payload(self, reference="SUPP-001", lines=None):
        return {
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
            "source": "google_sheets",
            "goods_received_on": "2026-08-21",
            "customer_segment": "individual",
            "client": {
                "name": "Supplement Customer",
                "email": "supplement@example.invalid",
                "phone": "+221 77 000 00 00",
            },
            "lines": lines if lines is not None else [self._line(reference, 1, 10.0)],
        }

    def _line(self, reference, index, weight):
        return {
            "external_line_key": "%s|A|%s" % (reference, index),
            "description": "Article %s" % index,
            "quantity": 1,
            "exact_weight_kg": weight,
            "billing_method": "real",
            "tariff_family_code": "food",
        }

    def _dossier_avec_facture_postee(self, reference="SUPP-001"):
        """Un dossier dont la facture principale est comptabilisée."""
        _data, shipment = self.Sync.upsert(self._payload(reference))
        invoice = shipment.action_prepare_native_freight_invoice()
        self.assertEqual(invoice.state, "draft")
        invoice.action_post()
        self.assertEqual(invoice.state, "posted")
        self.assertTrue(shipment.billing_locked)
        return shipment, invoice

    def _ajouter_colis(self, shipment, reference, index, weight):
        """Ajoute une ligne neuve par le chemin Freight sync."""
        payload = self._payload(reference, lines=[self._line(reference, index, weight)])
        _data, same = self.Sync.upsert(payload)
        self.assertEqual(same, shipment)
        return shipment.package_ids.filtered(
            lambda p: p.external_line_key == "%s|A|%s" % (reference, index))

    # ------------------------------------------------------------------
    # 1 à 5 — le verrou reste un verrou
    # ------------------------------------------------------------------

    def test_a_draft_primary_invoice_still_refuses_a_new_line(self):
        """Rien n'est comptabilisé : réinitialiser reste le bon geste."""
        _data, shipment = self.Sync.upsert(self._payload("SUPP-DRAFT"))
        invoice = shipment.action_prepare_native_freight_invoice()
        self.assertEqual(invoice.state, "draft")

        with self.assertRaises(UserError):
            self.Sync.upsert(self._payload(
                "SUPP-DRAFT", lines=[self._line("SUPP-DRAFT", 2, 4.0)]))

    def test_a_plain_orm_create_is_still_refused_after_posting(self):
        """L'exception appartient au chemin de synchronisation, pas à l'ORM."""
        shipment, _invoice = self._dossier_avec_facture_postee("SUPP-ORM")
        with self.assertRaises(UserError):
            self.Package.create({
                "shipment_id": shipment.id,
                "external_line_key": "SUPP-ORM|A|9",
                "package_type": "parcel",
                "quantity": 1,
                "unit_weight_kg": 3.0,
            })

    def test_a_new_line_through_freight_sync_is_allowed_after_posting(self):
        shipment, invoice = self._dossier_avec_facture_postee("SUPP-NEW")
        avant = len(shipment.package_ids)

        colis = self._ajouter_colis(shipment, "SUPP-NEW", 2, 6.0)

        self.assertTrue(colis)
        self.assertEqual(len(shipment.package_ids), avant + 1)
        self.assertEqual(invoice.state, "posted")

    def test_an_invoiced_package_cannot_be_modified(self):
        shipment, _invoice = self._dossier_avec_facture_postee("SUPP-IMMUT")
        ancien = shipment.package_ids[0]
        with self.assertRaises(UserError):
            ancien.write({"unit_weight_kg": 99.0})

    def test_an_invoiced_package_cannot_be_deleted(self):
        shipment, _invoice = self._dossier_avec_facture_postee("SUPP-UNLINK")
        ancien = shipment.package_ids[0]
        with self.assertRaises(UserError):
            ancien.unlink()

    # ------------------------------------------------------------------
    # 6 à 11 — la pièce complémentaire
    # ------------------------------------------------------------------

    def test_a_single_draft_supplement_covers_only_the_new_package(self):
        shipment, principale = self._dossier_avec_facture_postee("SUPP-ONE")
        total_principal = principale.amount_total
        colis = self._ajouter_colis(shipment, "SUPP-ONE", 2, 6.0)

        complement, created, kind = shipment._prepare_freight_invoice()

        self.assertTrue(created)
        self.assertEqual(kind, "supplement")
        self.assertEqual(complement.state, "draft")
        self.assertNotEqual(complement, principale)

        # 7. La facture principale est intacte.
        self.assertEqual(shipment.invoice_id, principale)
        self.assertEqual(principale.state, "posted")
        self.assertEqual(principale.amount_total, total_principal)

        # 8. Le complément ne porte que le nouveau colis, sans aucun frais.
        colis_couverts = complement.invoice_line_ids.mapped(
            "sale_line_ids.dally_freight_package_id")
        self.assertEqual(colis_couverts, colis)
        self.assertEqual(len(complement.invoice_line_ids), 1)

        # Le montant se verifie contre des valeurs ECRITES, jamais contre un
        # produit derive du prix : un colis non tarife donnerait 0 = 0 et
        # l'assertion passerait sans rien prouver. C'est exactement ce qui
        # masquait le complement a 0,00 EUR.
        self.assertGreater(colis.applied_unit_price_eur, 0.0,
                           "le colis complementaire doit etre tarife")
        self.assertAlmostEqual(colis.applied_unit_price_eur, 3.50, places=2)
        self.assertAlmostEqual(colis.billable_weight_kg, 6.0, places=2)
        self.assertAlmostEqual(complement.amount_untaxed, 21.00, places=2)

        # 10. covered_line_keys ne cite que le nouveau colis.
        self.assertEqual(
            shipment._invoice_covered_line_keys(complement),
            ["SUPP-ONE|A|2"])
        self.assertEqual(
            shipment._invoice_covered_line_keys(principale),
            ["SUPP-ONE|A|1"])

        # 11. La nature de chaque pièce est correctement nommée.
        self.assertEqual(
            shipment._invoice_covered_line_keys(principale), ["SUPP-ONE|A|1"])

    def test_the_supplement_carries_no_dossier_or_other_fees(self):
        """Les frais ont été portés par la pièce principale, une fois pour toutes."""
        # Les frais doivent exister AVANT la facture : c'est la piece principale
        # qui les porte. Les ajouter apres serait de toute facon refuse par le
        # verrou, et ne reproduirait pas le cas reel.
        payload = self._payload("SUPP-FEES")
        payload["dossier_fee_eur"] = 25.0
        payload["other_fees_eur"] = 10.0
        _data, shipment = self.Sync.upsert(payload)
        principale = shipment.action_prepare_native_freight_invoice()
        principale.action_post()
        self.assertAlmostEqual(shipment.dossier_fee_eur, 25.0, places=2)
        self.assertAlmostEqual(shipment.other_fees_eur, 10.0, places=2)
        self.assertGreater(len(principale.invoice_line_ids), 1,
                           "la principale porte le transport ET les frais")

        colis = self._ajouter_colis(shipment, "SUPP-FEES", 2, 6.0)

        complement, _created, _kind = shipment._prepare_freight_invoice()

        lignes = complement.invoice_line_ids
        self.assertEqual(len(lignes), 1, "aucune ligne de frais ne doit apparaître")
        self.assertGreater(colis.applied_unit_price_eur, 0.0)
        self.assertAlmostEqual(colis.applied_unit_price_eur, 3.50, places=2)
        self.assertAlmostEqual(colis.billable_weight_kg, 6.0, places=2)
        # 21,00 = 6 kg x 3,50. Les 25,00 de dossier et 10,00 d'autres frais
        # sont portes par la principale et ne reapparaissent pas ici.
        self.assertAlmostEqual(complement.amount_untaxed, 21.00, places=2)
        self.assertNotIn("dossier", " ".join(lignes.mapped("name")).lower())

        # La principale, elle, n'a pas bouge.
        self.assertEqual(principale.state, "posted")
        self.assertAlmostEqual(principale.amount_untaxed, 35.0 + 25.0 + 10.0, places=2)

    def test_a_retry_returns_the_same_supplement_without_duplicating(self):
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-RETRY")
        self._ajouter_colis(shipment, "SUPP-RETRY", 2, 6.0)
        premier, created_1, _kind = shipment._prepare_freight_invoice()
        self.assertTrue(created_1)

        second, created_2, kind_2 = shipment._prepare_freight_invoice()

        self.assertEqual(second, premier)
        self.assertFalse(created_2)
        self.assertEqual(kind_2, "supplement")
        self.assertEqual(len(shipment._supplement_invoices()), 1)
        self.assertEqual(len(shipment._supplement_orders()), 1)

    def test_the_primary_invoice_is_returned_as_primary(self):
        shipment, principale = self._dossier_avec_facture_postee("SUPP-KIND")
        facture, created, kind = shipment._prepare_freight_invoice()
        self.assertEqual(facture, principale)
        self.assertFalse(created)
        self.assertEqual(kind, "primary")

    # ------------------------------------------------------------------
    # 12 et 13 — un brouillon à la fois, puis un second complément
    # ------------------------------------------------------------------

    def test_a_draft_supplement_blocks_the_next_new_package(self):
        """Un brouillon fige un périmètre : la marchandise suivante attend."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-BLOCK")
        self._ajouter_colis(shipment, "SUPP-BLOCK", 2, 6.0)
        complement, _created, _kind = shipment._prepare_freight_invoice()
        self.assertEqual(complement.state, "draft")

        with self.assertRaises(UserError):
            self.Sync.upsert(self._payload(
                "SUPP-BLOCK", lines=[self._line("SUPP-BLOCK", 3, 2.0)]))

    def test_a_second_supplement_is_possible_once_the_first_is_posted(self):
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-TWO")
        self._ajouter_colis(shipment, "SUPP-TWO", 2, 6.0)
        premier, _created, _kind = shipment._prepare_freight_invoice()
        premier.action_post()
        self.assertEqual(premier.state, "posted")

        colis3 = self._ajouter_colis(shipment, "SUPP-TWO", 3, 4.0)
        second, created, kind = shipment._prepare_freight_invoice()

        self.assertTrue(created)
        self.assertEqual(kind, "supplement")
        self.assertNotEqual(second, premier)
        self.assertEqual(
            second.invoice_line_ids.mapped("sale_line_ids.dally_freight_package_id"),
            colis3)
        self.assertEqual(len(shipment._supplement_invoices()), 2)

    # ------------------------------------------------------------------
    # La portée du contexte de tarification
    # ------------------------------------------------------------------

    def test_the_new_package_is_priced_like_any_other(self):
        """Sans cela, la pièce complémentaire sortirait à 0,00 EUR."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-PRICED")
        colis = self._ajouter_colis(shipment, "SUPP-PRICED", 2, 6.0)
        self.assertGreater(colis.applied_unit_price_eur, 0.0)
        self.assertAlmostEqual(colis.applied_unit_price_eur, 3.50, places=2)
        self.assertEqual(colis.pricing_type_snapshot, "standard")
        self.assertTrue(colis.tariff_rule_id)

    def test_the_pricing_context_grants_nothing_on_an_old_package(self):
        """Le colis historique porte une ligne de commande : il échoue toujours.

        C'est le discriminant qui rend l'exception inapplicable au passé, même
        présentée avec un contexte parfaitement formé.
        """
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-CTX-OLD")
        ancien = shipment.package_ids[0]
        with self.assertRaises(UserError):
            ancien.with_context(
                **{SUPPLEMENT_PRICING_CONTEXT: ancien.id}
            ).write({"applied_unit_price_eur": 99.0})

    def test_the_pricing_context_does_not_unlock_business_fields(self):
        """Seules les colonnes tarifaires passent ; le poids reste figé."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-CTX-FIELD")
        colis = self._ajouter_colis(shipment, "SUPP-CTX-FIELD", 2, 6.0)
        with self.assertRaises(UserError):
            colis.with_context(
                **{SUPPLEMENT_PRICING_CONTEXT: colis.id}
            ).write({"unit_weight_kg": 42.0})
        with self.assertRaises(UserError):
            colis.with_context(
                **{SUPPLEMENT_PRICING_CONTEXT: colis.id}
            ).write({"applied_unit_price_eur": 9.0, "unit_weight_kg": 42.0})

    def test_the_pricing_context_must_name_this_exact_package(self):
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-CTX-ID")
        ancien = shipment.package_ids[0]
        colis = self._ajouter_colis(shipment, "SUPP-CTX-ID", 2, 6.0)
        with self.assertRaises(UserError):
            colis.with_context(
                **{SUPPLEMENT_PRICING_CONTEXT: ancien.id}
            ).write({"applied_unit_price_eur": 9.0})
        with self.assertRaises(UserError):
            colis.write({"applied_unit_price_eur": 9.0})

    def test_a_package_already_invoiced_by_a_supplement_refreezes(self):
        """Une fois le complément émis, le colis neuf rejoint l'historique."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-REFREEZE")
        colis = self._ajouter_colis(shipment, "SUPP-REFREEZE", 2, 6.0)
        shipment._prepare_freight_invoice()
        with self.assertRaises(UserError):
            colis.with_context(
                **{SUPPLEMENT_PRICING_CONTEXT: colis.id}
            ).write({"applied_unit_price_eur": 7.0})

    # ------------------------------------------------------------------
    # L'identité de la ligne source ne bouge plus une fois facturée
    # ------------------------------------------------------------------

    def test_an_invoiced_package_cannot_change_its_line_key(self):
        """TEST 1 — la clé porte l'idempotence : la changer réinventerait le colis."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-KEY-OLD")
        ancien = shipment.package_ids[0]
        with self.assertRaises(UserError):
            ancien.write({"external_line_key": "SUPP-KEY-HACK"})

    def test_a_supplement_package_cannot_change_its_line_key(self):
        """TEST 2 — le colis tardif reçoit sa clé au `create`, et plus jamais après."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-KEY-NEW")
        colis = self._ajouter_colis(shipment, "SUPP-KEY-NEW", 2, 6.0)
        with self.assertRaises(UserError):
            colis.write({"external_line_key": "SUPP-KEY-HACK"})

    def test_the_pricing_context_cannot_change_the_line_key(self):
        """TEST 3 — le bypass tarifaire ne couvre que des colonnes de prix."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-KEY-CTX")
        colis = self._ajouter_colis(shipment, "SUPP-KEY-CTX", 2, 6.0)
        with self.assertRaises(UserError):
            colis.with_context(
                **{SUPPLEMENT_PRICING_CONTEXT: colis.id}
            ).write({"external_line_key": "SUPP-KEY-HACK"})
        # Glissée à côté d'un champ légitime, la clé fait tomber tout le write.
        with self.assertRaises(UserError):
            colis.with_context(
                **{SUPPLEMENT_PRICING_CONTEXT: colis.id}
            ).write({
                "applied_unit_price_eur": 4.0,
                "external_line_key": "SUPP-KEY-HACK",
            })
        self.assertEqual(colis.external_line_key, "SUPP-KEY-CTX|A|2")

    def test_a_wrong_context_id_cannot_change_the_line_key(self):
        """TEST 4 — un contexte qui nomme un autre colis n'ouvre rien."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-KEY-ID")
        ancien = shipment.package_ids[0]
        colis = self._ajouter_colis(shipment, "SUPP-KEY-ID", 2, 6.0)
        with self.assertRaises(UserError):
            colis.with_context(
                **{SUPPLEMENT_PRICING_CONTEXT: ancien.id}
            ).write({"external_line_key": "SUPP-KEY-HACK"})

    # ------------------------------------------------------------------
    # Le flux de synchronisation reste entier
    # ------------------------------------------------------------------

    def test_a_sync_retry_with_the_same_key_finds_the_same_package(self):
        """TEST 5 — le rejeu réécrit la même clé : aucun changement, aucun refus."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-RETRY-KEY")
        colis = self._ajouter_colis(shipment, "SUPP-RETRY-KEY", 2, 6.0)
        avant = len(shipment.package_ids)

        rejoue = self._ajouter_colis(shipment, "SUPP-RETRY-KEY", 2, 6.0)

        self.assertEqual(rejoue, colis)
        self.assertEqual(len(shipment.package_ids), avant)
        self.assertEqual(
            self.Package.search_count(
                [("external_line_key", "=", "SUPP-RETRY-KEY|A|2")]), 1)

    def test_a_new_key_creates_a_package_when_no_draft_supplement_exists(self):
        """TEST 6 — le chemin nominal du colis tardif reste ouvert."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-NEWKEY")
        avant = len(shipment.package_ids)
        colis = self._ajouter_colis(shipment, "SUPP-NEWKEY", 2, 6.0)
        self.assertTrue(colis)
        self.assertEqual(len(shipment.package_ids), avant + 1)
        self.assertEqual(colis.external_line_key, "SUPP-NEWKEY|A|2")

    def test_a_draft_supplement_blocks_a_new_key(self):
        """TEST 7 — un brouillon fige son périmètre."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-DRAFTKEY")
        self._ajouter_colis(shipment, "SUPP-DRAFTKEY", 2, 6.0)
        complement, _created, _kind = shipment._prepare_freight_invoice()
        self.assertEqual(complement.state, "draft")
        with self.assertRaises(UserError):
            self._ajouter_colis(shipment, "SUPP-DRAFTKEY", 3, 2.0)

    def test_a_new_key_is_accepted_again_once_the_supplement_is_posted(self):
        """TEST 8 — une fois le complément comptabilisé, le cycle peut repartir."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-POSTKEY")
        self._ajouter_colis(shipment, "SUPP-POSTKEY", 2, 6.0)
        premier, _created, _kind = shipment._prepare_freight_invoice()
        premier.action_post()

        colis3 = self._ajouter_colis(shipment, "SUPP-POSTKEY", 3, 4.0)
        second, created, kind = shipment._prepare_freight_invoice()

        self.assertTrue(created)
        self.assertEqual(kind, "supplement")
        self.assertNotEqual(second, premier)
        self.assertEqual(colis3.external_line_key, "SUPP-POSTKEY|A|3")
        self.assertGreater(colis3.applied_unit_price_eur, 0.0)
        self.assertAlmostEqual(second.amount_untaxed, 4.0 * 3.50, places=2)

    # ------------------------------------------------------------------
    # 14 à 18 — le routage du paiement
    # ------------------------------------------------------------------

    def _encaissement(self, shipment, key, cible=None):
        valeurs = {
            "external_payment_key": key,
            "shipment_id": shipment.id,
            "amount": 10.0,
            "currency_id": self.eur.id,
            "payment_date": "2026-09-04",
            "source_method": "wave",
            "source": "google_sheets",
        }
        if cible is not None:
            valeurs["target_invoice_id"] = cible.id
        collection, _created = self.env["dally.freight.collection"].upsert_from_sync(valeurs)
        return collection

    def test_a_payment_without_target_keeps_the_primary_invoice(self):
        shipment, principale = self._dossier_avec_facture_postee("SUPP-PAY1")
        collection = self._encaissement(shipment, "SUPP-PAY1|P|1")
        self.assertFalse(collection.target_invoice_id)
        self.assertEqual(collection.invoice_id, principale)

    def test_a_payment_can_target_the_supplement(self):
        shipment, principale = self._dossier_avec_facture_postee("SUPP-PAY2")
        self._ajouter_colis(shipment, "SUPP-PAY2", 2, 6.0)
        complement, _created, _kind = shipment._prepare_freight_invoice()

        collection = self._encaissement(shipment, "SUPP-PAY2|P|1", cible=complement)

        self.assertEqual(collection.target_invoice_id, complement)
        self.assertEqual(collection.invoice_id, principale,
                         "le lien historique vers la principale reste intact")

    def test_the_post_hook_wakes_collections_targeting_a_supplement(self):
        """Un complément ne porte pas `dally_freight_shipment_id` : le réveil
        ne doit pas dépendre de ce lien, sinon l'encaissement attend pour
        toujours."""
        shipment, _principale = self._dossier_avec_facture_postee("SUPP-PAY3")
        self._ajouter_colis(shipment, "SUPP-PAY3", 2, 6.0)
        complement, _created, _kind = shipment._prepare_freight_invoice()
        self.assertFalse(complement.dally_freight_shipment_id)
        collection = self._encaissement(shipment, "SUPP-PAY3|P|1", cible=complement)
        self.assertEqual(collection.state, "pending")

        complement.action_post()

        # Le moteur a été relancé sur CETTE pièce : l'encaissement n'attend plus
        # la facture. Faute de canal configuré ici, il reste `pending` mais son
        # motif change — il ne parle plus de facture non comptabilisée.
        self.assertNotIn(
            "post", (collection.error_message or "").lower(),
            "le motif ne doit plus etre l'attente de comptabilisation")

    def test_the_target_becomes_immutable_once_paid(self):
        shipment, principale = self._dossier_avec_facture_postee("SUPP-PAY4")
        collection = self._encaissement(shipment, "SUPP-PAY4|P|1", cible=principale)
        collection.sudo().write({"payment_id": self._paiement(shipment).id})

        with self.assertRaises(UserError):
            collection.write({"target_invoice_id": False})

    def _paiement(self, shipment):
        journal = self.env["account.journal"].sudo().search([
            ("type", "=", "bank"), ("company_id", "=", shipment.company_id.id),
        ], limit=1) or self.env["account.journal"].sudo().search(
            [("type", "=", "bank")], limit=1)
        if not journal:
            self.skipTest("aucun journal de banque disponible")
        return self.env["account.payment"].sudo().create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": shipment.partner_id.id,
            "amount": 10.0,
            "journal_id": journal.id,
            "company_id": journal.company_id.id,
        })
