# -*- coding: utf-8 -*-
"""Le reçu remis au client au dépôt.

## Les trois propriétés que ces tests protègent

**Un reçu n'est pas une facture.** Le générer ne crée, ne poste et ne modifie
aucune pièce comptable. Plusieurs tests ne vérifient rien d'autre que cette
absence — et une absence, personne ne la remarque avant le rapprochement.

**Le client vient du dossier.** Aucun paramètre du navigateur ne le désigne,
si bien que le reçu d'Aissatou ne peut pas porter le nom de Fatou.

**Aucun solde inventé.** Un total en euros et un encaissement en francs ne se
soustraient pas ; le solde n'apparaît que lorsqu'il est exact.
"""

import io
import json
import re
import uuid

from odoo.tests import HttpCase, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.dally_ops_mobile.models.ops_errors import (
    DallyOpsError,
    DallyOpsNotFound,
)


@tagged("post_install", "-at_install", "dally")
class TestOpsReceipts(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.xof = cls.setup_other_currency("XOF")
        cls.eur = cls.setup_other_currency("EUR")
        cls.societe = cls.env.company
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Reçu Autre"})
        cls.societe.sudo().write({"dally_ops_wave_beneficiary": "Gilles"})

        cls.gilles = cls._compte(
            "recu.gilles", "Gilles Reçu",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Gilles")
        cls.responsable = cls._compte(
            "recu.resp", "Dalanda Responsable",
            "dally_ops_mobile.group_dally_ops_supervisor", acteur="Dalanda")
        cls.non_ops = cls._compte("recu.autre", "Sans rôle", "base.group_user")

        cls.canal_wave = cls._canal("wave", "Wave", cls.xof)
        cls.canal_eur = cls._canal("cash", "Espèces", cls.eur)

        cls.familles = {}
        Famille = cls.env["dally.freight.tariff.family"]
        Regle = cls.env["dally.freight.tariff.rule"]
        for code, nom in (("food", "Alimentaire standard"), ("seafood", "Halieutiques"),
                          ("honey", "Miel"), ("clothing", "Habits"),
                          ("non_food", "Non alimentaire")):
            famille = Famille.search([("code", "=", code)], limit=1)
            if not famille:
                famille = Famille.create({"name": "Reçu %s" % nom, "code": code})
            cls.familles[code] = famille
            for mode, prix in (("air", 5.0), ("sea", 3.0)):
                if not Regle.search([("family_id", "=", famille.id),
                                     ("transport_mode", "=", mode)], limit=1):
                    Regle.create({
                        "name": "Reçu %s %s" % (code, mode), "transport_mode": mode,
                        "family_id": famille.id, "customer_segment": "all",
                        "price_per_kg_eur": prix,
                    })

        cls.partner = cls.env["res.partner"].create({
            "name": "Aissatou Reçu", "company_id": cls.societe.id,
            "phone": "+221770000009", "email": "aissatou@example.test",
            "street": "Rue 10", "city": "Dakar",
        })
        cls.autre_partner = cls.env["res.partner"].create({
            "name": "Fatou Reçu", "company_id": cls.societe.id,
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.air = cls._consolidation("AIR-DSS-CDG-RECU-001", "air")
        cls.sea = cls._consolidation("SEA-DKR-LEH-RECU-001", "sea")

    # ─── Fabriques ───────────────────────────────────────────────────

    @classmethod
    def _compte(cls, login, nom, groupe, acteur=None):
        valeurs = {
            "name": nom, "login": login,
            "group_ids": [(6, 0, [cls.env.ref(groupe).id])],
            "company_id": cls.env.company.id,
            "company_ids": [(6, 0, [cls.env.company.id])],
        }
        if acteur:
            valeurs["dally_ops_cash_actor"] = acteur
        return cls.env["res.users"].create(valeurs)

    @classmethod
    def _canal(cls, code, nom, devise):
        journal = cls.company_data["default_journal_bank"]
        return cls.env["dally.freight.payment.channel"].create({
            "name": nom, "code": code, "company_id": cls.env.company.id,
            "currency_id": devise.id, "journal_id": journal.id,
            "payment_method_line_id": journal.inbound_payment_method_line_ids[:1].id,
            "active": True,
        })

    @classmethod
    def _consolidation(cls, reference, mode):
        return cls.env["dally.freight.consolidation"].create({
            "name": reference, "state": "collecting", "active": True,
            "company_id": cls.env.company.id, "transport_mode": mode,
            "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })

    # ─── Outils ──────────────────────────────────────────────────────

    def _service(self, utilisateur=None, societe=None):
        return (self.env["dally.ops.receipt.service"]
                .with_user(utilisateur or self.gilles)
                .with_company(societe or self.societe))

    def _recu(self, reference, utilisateur=None):
        """Le contrat, sorti de son enveloppe."""
        return self._service(utilisateur).receipt_dto(reference)["receipt"]

    def _pdf(self, reference, utilisateur=None):
        """Le PDF, réellement rendu — sans aucun aménagement de test.

        Le service remet un document HTML autonome à `_run_wkhtmltopdf`, que
        `--test-enable` ne court-circuite pas. Ces tests exercent donc le même
        chemin qu'en production, avec le vrai binaire présent dans l'image
        `odoo:19.0`. C'est la seule façon d'affirmer qu'un PDF a été produit.
        """
        return self._service(utilisateur).receipt_pdf(reference)

    def _creer_dossier(self, consolidation=None, famille="non_food", **ligne):
        saisie = {
            "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
            "goods_category": "Non alimentaire", "description": "Savon",
            "quantity": 1, "announced_weight_kg": None, "exact_weight_kg": 13.5,
            "length_cm": None, "width_cm": None, "height_cm": None,
            "billing_method": "real",
            "tariff_family_code": self.familles[famille].code,
            "customs_value_xof": 25000,
        }
        saisie.update(ligne)
        return (self.env["dally.ops.intake.service"]
                .with_user(self.gilles).with_company(self.societe)
                .create_intake({
                    "request_uuid": str(uuid.uuid4()),
                    "consolidation_reference": (consolidation or self.air).name,
                    "customer_reference": self.handle.token,
                    "received_on": "2026-08-30",
                    "line": saisie,
                }))["intake"]["reference"]

    def _shipment(self, reference):
        return self.env["dally.shipment"].sudo().search(
            [("external_reference", "=", reference)], limit=1)

    def _encaisser(self, reference, montant=100000.0, wave="TWRECU001"):
        return (self.env["dally.ops.wave.payment.service"]
                .with_user(self.gilles).with_company(self.societe)
                .record_wave_payment(reference, {
                    "request_uuid": str(uuid.uuid4()), "amount": montant,
                    "currency": "XOF", "wave_reference": wave,
                    "paid_at": "2026-08-30", "note": "",
                }))

    def _ajouter_article(self, reference, description, poids, famille="non_food"):
        return (self.env["dally.ops.intake.line.service"]
                .with_user(self.gilles).with_company(self.societe)
                .add_line(reference, {
                    "request_uuid": str(uuid.uuid4()),
                    "line": {
                        "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                        "goods_category": "Non alimentaire",
                        "description": description, "quantity": 1,
                        "announced_weight_kg": None, "exact_weight_kg": poids,
                        "length_cm": None, "width_cm": None, "height_cm": None,
                        "billing_method": "real",
                        "tariff_family_code": self.familles[famille].code,
                        "customs_value_xof": 10000,
                    },
                }))

    # ─── Le rôle et le périmètre ─────────────────────────────────────

    def test_un_compte_sans_role_ops_n_obtient_aucun_recu(self):
        reference = self._creer_dossier()
        for appel in (
            lambda: self._recu(reference, self.non_ops),
            lambda: self._pdf(reference, self.non_ops),
        ):
            with self.assertRaises(Exception):
                appel()

    def test_le_logisticien_et_le_responsable_obtiennent_le_recu(self):
        reference = self._creer_dossier()
        for compte in (self.gilles, self.responsable):
            recu = self._recu(reference, compte)
            self.assertEqual(recu["reference"], reference)

    def test_un_dossier_d_une_autre_societe_est_introuvable(self):
        reference = self._creer_dossier()
        etranger = self.env["res.users"].create({
            "name": "Ops Ailleurs", "login": "recu.ailleurs",
            "group_ids": [(6, 0, [self.env.ref(
                "dally_ops_mobile.group_dally_ops_logistician").id])],
            "company_id": self.autre_societe.id,
            "company_ids": [(6, 0, [self.autre_societe.id])],
        })
        with self.assertRaises(Exception):
            self._service(etranger, self.autre_societe).receipt_dto(reference)

    def test_un_dossier_annule_ne_donne_aucun_recu(self):
        """Un reçu remis sur un dossier annulé atteste d'une prise en charge
        qui n'existe plus. Le refus est explicite, jamais un 404 : le
        logisticien doit comprendre que le dossier existe et qu'il est annulé.
        """
        reference = self._creer_dossier()
        self._shipment(reference).sudo().write({"state": "cancelled"})
        for appel in (lambda: self._recu(reference),
                      lambda: self._pdf(reference)):
            with self.assertRaises(DallyOpsError) as capture:
                appel()
            self.assertEqual(capture.exception.code, "intake_cancelled")
            self.assertEqual(capture.exception.status, 409)

    def test_le_contrat_arrive_dans_une_enveloppe_nommee(self):
        """La forme exacte de la charge utile, et rien d'autre.

        Le BFF la lit avec un schéma strict. Une enveloppe renommée ou retirée
        ferait échouer la lecture côté navigateur — et comme l'écran se replie
        silencieusement sur le dossier, personne ne verrait la cause. C'est
        arrivé : le contrat sortait nu quand le schéma attendait `receipt`.
        """
        reference = self._creer_dossier()
        charge = self._service().receipt_dto(reference)
        self.assertEqual(sorted(charge), ["receipt"])
        self.assertEqual(charge["receipt"]["reference"], reference)

    def test_la_reference_du_recu_est_celle_que_le_serveur_a_attribuee(self):
        """Jamais un numéro né dans le téléphone."""
        reference = self._creer_dossier()
        recu = self._recu(reference)
        self.assertRegex(recu["reference"], r"^AIR-DSS-CDG-RECU-001-A\d{3}$")
        self.assertFalse(recu["reference"].startswith("LOCAL-"))
        self.assertNotIn("LOCAL-", json.dumps(recu, ensure_ascii=False))

    def test_un_dossier_qui_n_est_pas_une_saisie_ops_n_a_pas_de_recu(self):
        """Le domaine imposé, éprouvé sur un dossier qui existe vraiment.

        Une référence inventée ne prouve rien : elle ne désigne rien de toute
        façon. Ce dossier-ci existe, dans la bonne société, avec une référence
        bien formée — mais il vient du classeur, pas du terrain. Le reçu de
        Dally Ops n'a pas à parler pour lui.
        """
        reference = self._creer_dossier()
        # Le reçu existe tant que le dossier est une saisie Ops…
        self.assertEqual(self._recu(reference)["reference"], reference)

        # …et disparaît dès que son origine dit autre chose. On part d'un
        # dossier réel plutôt que d'en forger un : `sync_source_key` et
        # `intake_consolidation_id` sont immuables une fois posés — un
        # garde-fou plus fort encore que ce domaine, et qui interdit de
        # fabriquer le cas autrement.
        self._shipment(reference).sudo().write({"sync_source": "google_sheets"})
        with self.assertRaises(DallyOpsNotFound):
            self._recu(reference)

    def test_une_reference_locale_ne_donne_aucun_recu(self):
        """Une file hors connexion n'invente pas de dossier."""
        for valeur in ("LOCAL-abcdef", "A001", "", "  ", "AIR-INCONNU-A001"):
            with self.assertRaises(Exception):
                self._recu(valeur)

    # ─── Le contenu ──────────────────────────────────────────────────

    def test_le_recu_porte_le_dossier_le_depart_et_la_route(self):
        reference = self._creer_dossier(self.air)
        recu = self._recu(reference)
        self.assertEqual(recu["reference"], reference)
        self.assertEqual(recu["local_reference"],
                         self._shipment(reference).collection_local_ref)
        self.assertEqual(recu["transport_mode"], "air")
        self.assertEqual(recu["transport_mode_label"], "Aérien")
        self.assertEqual(recu["consolidation"]["reference"], self.air.name)
        self.assertEqual(recu["consolidation"]["origin"], "Dakar")
        self.assertEqual(recu["consolidation"]["destination"], "Paris")
        self.assertEqual(recu["received_on"], "2026-08-30")

    def test_un_dossier_maritime_est_annonce_comme_tel(self):
        recu = self._recu(self._creer_dossier(self.sea))
        self.assertEqual(recu["transport_mode"], "sea")
        self.assertEqual(recu["transport_mode_label"], "Maritime")

    def test_le_client_vient_du_dossier(self):
        reference = self._creer_dossier()
        recu = self._recu(reference)
        self.assertEqual(recu["customer"]["name"], "Aissatou Reçu")
        self.assertEqual(recu["customer"]["phone"], "+221770000009")
        self.assertEqual(recu["customer"]["email"], "aissatou@example.test")
        self.assertIn("Dakar", recu["customer"]["address"])
        # Aucun paramètre ne permet d'en désigner un autre : la seule entrée
        # du service est la référence du dossier.
        self.assertNotEqual(recu["customer"]["name"], "Fatou Reçu")

    def test_deux_dossiers_ne_partagent_pas_le_meme_client(self):
        """La preuve que le client est *dérivé*, et non retrouvé.

        Un seul dossier ne prouve rien : n'importe quelle recherche renverrait
        le bon nom par hasard. Il en faut deux, portant des clients
        différents — c'est le cas où le reçu d'Aissatou porterait le nom de
        Fatou.
        """
        autre_handle = self.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": self.autre_partner.id, "company_id": self.societe.id,
        })
        premier = self._creer_dossier()
        second = (self.env["dally.ops.intake.service"]
                  .with_user(self.gilles).with_company(self.societe)
                  .create_intake({
                      "request_uuid": str(uuid.uuid4()),
                      "consolidation_reference": self.air.name,
                      "customer_reference": autre_handle.token,
                      "received_on": "2026-08-30",
                      "line": {
                          "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                          "goods_category": "Non alimentaire",
                          "description": "Tissu", "quantity": 1,
                          "announced_weight_kg": None, "exact_weight_kg": 4.0,
                          "length_cm": None, "width_cm": None, "height_cm": None,
                          "billing_method": "real",
                          "tariff_family_code": self.familles["non_food"].code,
                          "customs_value_xof": 10000,
                      },
                  }))["intake"]["reference"]

        self.assertEqual(self._recu(premier)["customer"]["name"], "Aissatou Reçu")
        self.assertEqual(self._recu(second)["customer"]["name"], "Fatou Reçu")

    def test_le_recu_nomme_l_operateur_qui_a_receptionne(self):
        recu = self._recu(self._creer_dossier())
        self.assertEqual(recu["operator"]["name"], "Gilles Reçu")

    def test_le_receptionnaire_n_est_pas_celui_qui_imprime(self):
        """Le responsable rééditera le reçu ; il n'a pas réceptionné pour autant.

        Sans cette distinction, le document attribuerait la prise en charge à
        la dernière personne qui a ouvert l'écran.
        """
        reference = self._creer_dossier()
        recu = self._recu(reference, self.responsable)
        self.assertEqual(recu["operator"]["name"], "Gilles Reçu")
        self.assertNotEqual(recu["operator"]["name"], self.responsable.name)

    def test_chaque_article_a_sa_ligne(self):
        reference = self._creer_dossier()
        self._ajouter_article(reference, "Tissu", 3.55)
        self._ajouter_article(reference, "Habits", 6.75)
        recu = self._recu(reference)
        self.assertEqual(len(recu["articles"]), 3)
        self.assertEqual(recu["totals"]["articles_count"], 3)
        descriptions = [a["description"] for a in recu["articles"]]
        self.assertEqual(descriptions, ["Savon", "Tissu", "Habits"])
        self.assertAlmostEqual(recu["totals"]["weight_kg"], 23.8, places=2)

    def test_les_cinq_familles_sont_lisibles_par_le_client(self):
        attendues = {
            "food": "Alimentaire standard", "seafood": "Halieutiques",
            "honey": "Miel", "clothing": "Habits / Vêtements",
            "non_food": "Non alimentaire",
        }
        for code, libelle in attendues.items():
            recu = self._recu(self._creer_dossier(famille=code))
            self.assertEqual(recu["articles"][0]["tariff_family"], libelle)

    def test_la_valeur_douaniere_declaree_figure_au_recu(self):
        recu = self._recu(self._creer_dossier())
        self.assertEqual(recu["articles"][0]["customs_value_xof"], 25000)

    def test_le_tarif_affiche_est_celui_qu_odoo_a_applique(self):
        reference = self._creer_dossier()
        colis = self._shipment(reference).package_ids[0]
        recu = self._recu(reference)
        article = recu["articles"][0]
        self.assertEqual(article["applied_unit_price_eur"],
                         colis.applied_unit_price_eur)
        self.assertEqual(article["transport_amount_eur"],
                         colis.transport_amount_eur)
        self.assertEqual(recu["totals"]["transport_amount_eur"],
                         colis.transport_amount_eur)

    def test_un_tarif_special_est_affiche_sans_son_motif_interne(self):
        """Le client voit ce qu'il paie, pas pourquoi la maison l'a décidé."""
        reference = self._creer_dossier()
        colis = self._shipment(reference).package_ids[0]
        colis.sudo().write({
            "manual_unit_price_eur": 3.0,
            "applied_unit_price_eur": 3.0,
            "pricing_type_snapshot": "special",
            "pricing_reason": "Geste commercial interne",
        })
        recu = self._recu(reference)
        article = recu["articles"][0]
        # Un prix décidé à la main reste un prix : il figure au reçu.
        self.assertEqual(article["applied_unit_price_eur"], 3.0)
        self.assertEqual(article["transport_amount_eur"], 40.5)
        self.assertEqual(recu["totals"]["transport_amount_eur"], 40.5)
        rendu = json.dumps(recu, ensure_ascii=False)
        self.assertNotIn("Geste commercial interne", rendu)
        self.assertNotIn("pricing_reason", rendu)
        self.assertNotIn("special", rendu)

    def test_un_article_offert_n_est_pas_un_article_sans_prix(self):
        """Zéro euro est une décision ; l'absence de prix n'en est pas une."""
        reference = self._creer_dossier()
        colis = self._shipment(reference).package_ids[0]
        colis.sudo().write({
            "manual_unit_price_eur": 0.0, "applied_unit_price_eur": 0.0,
        })
        recu = self._recu(reference)
        self.assertEqual(recu["articles"][0]["transport_amount_eur"], 0.0)
        self.assertEqual(recu["totals"]["transport_amount_eur"], 0.0)

    # ─── Paiements et solde ──────────────────────────────────────────

    def test_un_dossier_sans_paiement_le_dit(self):
        recu = self._recu(self._creer_dossier())
        self.assertEqual(recu["payments"], [])
        self.assertEqual(recu["totals"]["paid"], [])
        # Aucun encaissement n'a été inventé pour faire joli.
        self.assertEqual(
            self.env["dally.freight.collection"].sudo().search_count([
                ("shipment_id", "=", self._shipment(recu["reference"]).id)]), 0)

    def test_un_paiement_wave_figure_avec_son_encaisseur(self):
        reference = self._creer_dossier()
        self._encaisser(reference)
        recu = self._recu(reference)
        self.assertEqual(len(recu["payments"]), 1)
        paiement = recu["payments"][0]
        self.assertEqual(paiement["amount"], 100000.0)
        self.assertEqual(paiement["currency_code"], "XOF")
        self.assertEqual(paiement["method"], "Wave")
        self.assertEqual(paiement["collected_by"], "Gilles")
        self.assertEqual(paiement["wave_reference"], "TWRECU001")

    def test_deux_paiements_partiels_restent_deux_mouvements(self):
        reference = self._creer_dossier()
        self._encaisser(reference, 100000.0, "TWPART001")
        self._encaisser(reference, 50000.0, "TWPART002")
        recu = self._recu(reference)
        self.assertEqual(len(recu["payments"]), 2)
        self.assertEqual(sorted(p["amount"] for p in recu["payments"]),
                         [50000.0, 100000.0])
        # Le résumé conserve le total sans effacer le détail.
        self.assertEqual(recu["totals"]["paid"], [{
            "currency_code": "XOF", "amount": 150000.0,
            "display": "150 000 FCFA",
        }])

    def test_un_encaissement_annule_ne_figure_plus_au_recu(self):
        """Une collecte annulée ne raconte plus rien d'utile au client.

        La laisser passer ferait figurer sur le papier de l'argent que la
        maison n'a pas reçu — et gonflerait le total encaissé d'autant.
        """
        reference = self._creer_dossier()
        self._encaisser(reference, 100000.0, "TWANN001")
        self._encaisser(reference, 25000.0, "TWANN002")
        collection = self.env["dally.freight.collection"].sudo().search([
            ("shipment_id", "=", self._shipment(reference).id),
            ("amount", "=", 25000.0),
        ], limit=1)
        self.assertTrue(collection)
        collection.write({"state": "cancelled"})

        recu = self._recu(reference)
        self.assertEqual([p["amount"] for p in recu["payments"]], [100000.0])
        self.assertEqual(recu["totals"]["paid"], [{
            "currency_code": "XOF", "amount": 100000.0,
            "display": "100 000 FCFA",
        }])

    def test_aucun_solde_n_est_calcule_entre_deux_devises(self):
        """L'erreur la plus tentante, et la plus coûteuse."""
        reference = self._creer_dossier()
        self._encaisser(reference, 100000.0)
        recu = self._recu(reference)
        du = self._shipment(reference).package_ids[0].transport_amount_eur
        self.assertTrue(du, "sans tarif résolu, le test ne prouverait rien")
        self.assertEqual(recu["totals"]["transport_amount_eur"], du)
        self.assertEqual(recu["totals"]["paid"], [{
            "currency_code": "XOF", "amount": 100000.0,
            "display": "100 000 FCFA",
        }])
        self.assertIsNone(recu["totals"]["balance_eur"])
        self.assertEqual(recu["totals"]["balance_reason"], "currency_mismatch")

    def test_le_solde_est_calcule_quand_les_montants_sont_comparables(self):
        reference = self._creer_dossier()
        (self.env["dally.ops.payment.service"]
         .with_user(self.gilles).with_company(self.societe)
         .record_payment(reference, {
             "request_uuid": str(uuid.uuid4()), "amount": 40.0,
             "payment_date": "2026-08-30", "payment_method": "cash",
             "currency_code": "EUR",
         }))
        du = self._shipment(reference).package_ids[0].transport_amount_eur
        self.assertTrue(du, "sans tarif résolu, le test ne prouverait rien")
        recu = self._recu(reference)
        self.assertEqual(recu["totals"]["transport_amount_eur"], du)
        self.assertEqual(recu["totals"]["balance_eur"], round(du - 40.0, 2))
        self.assertIsNone(recu["totals"]["balance_reason"])

    def test_un_total_partiel_ne_devient_jamais_un_solde(self):
        reference = self._creer_dossier(famille="non_food")
        colis = self._shipment(reference).package_ids[0]
        colis.sudo().write({"billing_method": "quote"})
        # Le moteur de facturation écrit 0,00 € pour un article sur devis.
        # Recopié tel quel, ce zéro se lirait « rien à payer ».
        self.assertEqual(colis.transport_amount_eur, 0.0)
        recu = self._recu(reference)
        self.assertIsNone(recu["articles"][0]["transport_amount_eur"])
        self.assertIsNone(recu["totals"]["transport_amount_eur"])
        self.assertIsNone(recu["totals"]["balance_eur"])
        self.assertEqual(recu["totals"]["balance_reason"], "pricing_incomplete")

    # ─── Reçu ≠ facture ──────────────────────────────────────────────

    def test_le_document_ne_se_presente_jamais_comme_une_facture(self):
        recu = self._recu(self._creer_dossier())
        self.assertEqual(recu["document"]["title"], "REÇU DE PRISE EN CHARGE")
        self.assertNotIn("FACTURE", recu["document"]["title"].upper())
        self.assertEqual(recu["invoice_number"], "")

    def test_generer_un_recu_ne_cree_aucune_facture(self):
        reference = self._creer_dossier()
        avant = self.env["account.move"].sudo().search_count([])
        self._recu(reference)
        self._pdf(reference)
        self.assertEqual(self.env["account.move"].sudo().search_count([]), avant)
        self.assertFalse(self._shipment(reference).invoice_id)

    def test_une_facture_brouillon_reste_brouillon(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        facture = self.env["account.move"].sudo().create({
            "move_type": "out_invoice", "partner_id": self.partner.id,
            "company_id": self.societe.id, "invoice_date": "2026-08-30",
            "currency_id": self.eur.id,
        })
        # Un brouillon porte « / » tant qu'il n'est pas comptabilisé. Lui
        # donner un nom retire ce filet et met à l'épreuve le vrai garde-fou :
        # l'état. Sans quoi le reçu annoncerait un numéro qui n'engage rien.
        facture.sudo().write({"name": "BROUILLON/2026/00001"})
        shipment.sudo().write({"invoice_id": facture.id})
        avant = self.env["account.move"].sudo().search_count([])

        recu = self._recu(reference)
        self._pdf(reference)

        facture.invalidate_recordset(["state", "name"])
        self.assertEqual(facture.state, "draft")
        self.assertEqual(facture.name, "BROUILLON/2026/00001")
        self.assertEqual(self.env["account.move"].sudo().search_count([]), avant)
        self.assertEqual(shipment.invoice_id, facture)
        # Une facture non comptabilisée n'a pas de numéro à annoncer.
        self.assertEqual(recu["invoice_number"], "")

    def test_le_numero_d_une_facture_comptabilisee_est_une_simple_reference(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        facture = self.env["account.move"].sudo().create({
            "move_type": "out_invoice", "partner_id": self.partner.id,
            "company_id": self.societe.id, "invoice_date": "2026-08-30",
            "currency_id": self.eur.id,
            "invoice_line_ids": [(0, 0, {
                "name": "Transport", "quantity": 1, "price_unit": 100.0,
            })],
        })
        facture.action_post()
        shipment.sudo().write({"invoice_id": facture.id})
        recu = self._recu(reference)
        self.assertEqual(recu["invoice_number"], facture.name)
        # Le document reste un reçu.
        self.assertEqual(recu["document"]["title"], "REÇU DE PRISE EN CHARGE")

    # ─── Ce que le reçu ne touche pas ────────────────────────────────

    def test_aucun_numero_de_dossier_n_est_consomme(self):
        reference = self._creer_dossier()
        sequence = self.air.intake_sequence_id.sudo()
        avant = self._valeur_sequence(sequence)
        avant_dossiers = self.env["dally.shipment"].sudo().search_count([])

        self._recu(reference)
        self._pdf(reference)

        self.assertEqual(self._valeur_sequence(sequence), avant)
        self.assertEqual(
            self.env["dally.shipment"].sudo().search_count([]), avant_dossiers)

    def _valeur_sequence(self, sequence):
        self.env.cr.execute(
            "SELECT last_value FROM pg_sequences WHERE sequencename = %s",
            ["ir_sequence_%03d" % sequence.id])
        ligne = self.env.cr.fetchone()
        return ligne[0] if ligne else sequence.number_next_actual

    def test_aucun_colis_n_est_modifie(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        avant = [
            (c.id, c.description, c.quantity, c.total_weight_kg,
             c.customs_value_xof, c.write_date)
            for c in shipment.package_ids
        ]
        self._recu(reference)
        self._pdf(reference)
        shipment.package_ids.invalidate_recordset()
        self.assertEqual(
            [(c.id, c.description, c.quantity, c.total_weight_kg,
              c.customs_value_xof, c.write_date)
             for c in shipment.package_ids], avant)

    def test_le_recu_reste_disponible_quand_la_projection_sheet_echoue(self):
        """Google n'est jamais une condition du reçu.

        Le classeur est une projection administrative ; le client attend son
        justificatif au comptoir, pas la fin d'un transport tiers.
        """
        reference = self._creer_dossier()
        boite = self.env["dally.ops.sheet.outbox"].sudo().search([
            ("company_id", "=", self.societe.id),
            ("projection_type", "=", "freight_dossier"),
        ])
        self.assertTrue(boite)
        boite.write({"state": "retry", "last_error": "google indisponible"})

        recu = self._recu(reference)
        self.assertEqual(recu["reference"], reference)
        document = self._pdf(reference)
        self.assertTrue(document["content"])
        # Le reçu ne consulte même pas l'état de la projection.
        from odoo.addons.dally_ops_mobile.models import ops_receipt_service
        import inspect
        source = inspect.getsource(ops_receipt_service)
        self.assertNotIn("sheet.outbox", source)
        self.assertNotIn("sheet_outbox", source)

    # ─── Le contrat public ───────────────────────────────────────────

    def test_le_recu_ne_porte_aucun_identifiant_interne(self):
        reference = self._creer_dossier()
        self._encaisser(reference)
        rendu = json.dumps(self._recu(reference), ensure_ascii=False)
        for interdit in ("partner_id", "shipment_id", "invoice_id", "company_id",
                         "currency_id", "user_id", "account_move", "account_payment",
                         "request_uuid", "sync_source_key", "external_payment_key",
                         "external_line_key", "collection_id", "outbox"):
            self.assertNotIn(interdit, rendu)

    def test_le_recu_ne_porte_aucun_secret(self):
        reference = self._creer_dossier()
        rendu = json.dumps(self._recu(reference)).lower()
        for interdit in ("api_key", "password", "secret", "bearer", "token",
                         "private_key", "session_id", "cookie"):
            self.assertNotIn(interdit, rendu)

    # ─── Le PDF ──────────────────────────────────────────────────────

    def test_le_pdf_est_un_vrai_pdf_non_vide(self):
        reference = self._creer_dossier()
        document = self._pdf(reference)
        self.assertTrue(document["content"].startswith(b"%PDF"))
        self.assertGreater(len(document["content"]), 1000)

    def test_le_nom_de_fichier_est_sur_et_sans_nom_de_client(self):
        reference = self._creer_dossier()
        nom = self._pdf(reference)["filename"]
        self.assertTrue(nom.startswith("Recu_DallyTrading_"))
        self.assertTrue(nom.endswith(".pdf"))
        self.assertNotIn("Aissatou", nom)
        self.assertNotIn("/", nom)
        self.assertNotIn("..", nom)

    def test_une_reference_hostile_ne_fabrique_pas_un_chemin(self):
        """Le garde-fou du nom de fichier, éprouvé sur ce qu'il doit arrêter.

        Une référence propre traverse la neutralisation sans rien montrer :
        c'est sur une référence forgée qu'elle se voit. Le service ne sert que
        des références venues de la base, mais un nom de fichier construit sans
        filtre resterait une porte ouverte le jour où la source change.
        """
        service = self.env["dally.ops.receipt.service"]
        for reference, attendu in (
            ("../../etc/passwd", "Recu_DallyTrading_etc-passwd.pdf"),
            ('a"b', "Recu_DallyTrading_a-b.pdf"),
            ("..", "Recu_DallyTrading_recu.pdf"),
            ("", "Recu_DallyTrading_recu.pdf"),
            ("A" * 90, "Recu_DallyTrading_%s.pdf" % ("A" * 60)),
        ):
            self.assertEqual(
                service._nom_de_fichier({"reference": reference}), attendu)

    def test_le_pdf_supporte_les_accents_les_devises_et_le_multi_articles(self):
        reference = self._creer_dossier(
            description="Épices, céréales & thé — Ndèye")
        self._ajouter_article(reference, "Tissu wax — Médina", 3.55)
        self._ajouter_article(reference, "Habits & chaussures", 6.75)
        self._encaisser(reference, 100000.0, "TWACC001")
        document = self._pdf(reference)
        self.assertTrue(document["content"].startswith(b"%PDF"))
        self.assertGreater(len(document["content"]), 1000)

    def test_le_pdf_contient_reellement_le_texte_du_recu(self):
        """Un PDF valide peut être une page blanche.

        Les octets sont donc relus : le nom du client, la référence, les
        désignations accentuées et les montants doivent s'y trouver.
        """
        from pdfminer.high_level import extract_text

        reference = self._creer_dossier(description="Épices, céréales & thé")
        self._ajouter_article(reference, "Tissu wax — Médina", 3.55)
        self._encaisser(reference, 100000.0, "TWTXT001")
        document = self._pdf(reference)

        texte = re.sub(r"\s+", " ", extract_text(io.BytesIO(document["content"])))
        self.assertIn("REÇU DE PRISE EN CHARGE", texte)
        self.assertIn(reference, texte)
        self.assertIn("Aissatou Reçu", texte)
        self.assertIn("Épices, céréales & thé", texte)
        self.assertIn("Tissu wax — Médina", texte)
        self.assertIn("Aérien", texte)
        self.assertIn("100 000 FCFA", texte)
        # La ligne d'article **et** le total, qui ne portent pas le même
        # nombre : vérifier l'un des deux laisserait l'autre écrire ce qu'il
        # veut.
        self.assertIn("67,50 €", texte)   # l'article
        self.assertIn("85,25 €", texte)   # le total des deux articles
        self.assertIn("13,5 kg", texte)   # le poids d'un article
        self.assertIn("17,05 kg", texte)  # le poids total
        # Aucun point décimal dans un document français. Le papier et l'écran
        # écrivent les mêmes caractères, sans quoi le client lirait deux
        # versions du même montant.
        for brut in ("67.5", "85.25", "13.5", "17.05"):
            self.assertNotIn(brut, texte)
        self.assertIn("Gilles", texte)
        self.assertIn("Il ne constitue pas une facture", texte)
        # Un solde entre deux devises n'est pas calculé : il est renvoyé au
        # détail des paiements plutôt qu'inventé.
        self.assertIn("Voir détail", texte)

    def test_les_montants_du_recu_sont_ecrits_une_seule_fois(self):
        """Le papier et l'écran lisent la même chaîne, pas deux formateurs."""
        from odoo.addons.dally_ops_mobile.models.ops_receipt_service import montant

        self.assertEqual(montant(100000.0, "XOF"), "100 000 FCFA")
        self.assertEqual(montant(67.5, "EUR"), "67,50 €")
        self.assertEqual(montant(0.0, "EUR"), "0,00 €")
        self.assertEqual(montant(1234567.0, "XOF"), "1 234 567 FCFA")
        self.assertEqual(montant(-12.5, "EUR"), "-12,50 €")
        # Une devise inconnue reste juste : le nombre et son code.
        self.assertEqual(montant(9.5, "USD"), "9,50 USD")
        # Un montant absent ne devient jamais zéro.
        self.assertEqual(montant(None, "EUR"), "")

    def test_le_pdf_et_l_apercu_viennent_du_meme_contrat(self):
        """Une seule lecture, deux rendus.

        Deux constructions séparées finiraient par diverger, et c'est toujours
        le papier — celui que le client emporte — qui dirait faux.
        """
        from odoo.addons.dally_ops_mobile.models import ops_receipt_service
        import inspect
        source = inspect.getsource(ops_receipt_service.DallyOpsReceiptService)
        # `receipt_pdf` passe par `_construire`, comme `receipt_dto`.
        self.assertIn("recu = self._construire(shipment)", source)
        self.assertIn('_render(GABARIT, {"receipt": recu})', source)


@tagged("post_install", "-at_install", "dally")
class TestOpsReceiptsHttp(HttpCase):
    """Les deux routes, éprouvées par HTTP réel."""

    MOT_DE_PASSE = "OpsProbe!2026#recu"

    def setUp(self):
        super().setUp()
        self.societe = self.env.company
        self.gilles = self.env["res.users"].create({
            "name": "Gilles HTTP Reçu", "login": "http.recu.gilles",
            "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref(
                "dally_ops_mobile.group_dally_ops_logistician").id])],
            "company_id": self.societe.id,
            "company_ids": [(6, 0, [self.societe.id])],
        })
        self.etranger = self.env["res.users"].create({
            "name": "Sans rôle", "login": "http.recu.autre",
            "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            "company_id": self.societe.id,
            "company_ids": [(6, 0, [self.societe.id])],
        })

    def _dossier(self):
        """Un vrai dossier, pour interroger la route telle qu'elle sert.

        Les tests de refus se contentent d'une référence inconnue ; ceux-ci
        veulent la réponse complète — le type, les en-têtes, les octets — parce
        que c'est là que se décide si un reçu client peut finir dans le cache
        d'un proxy partagé.
        """
        Famille = self.env["dally.freight.tariff.family"]
        famille = Famille.search([("code", "=", "non_food")], limit=1)
        if not famille:
            famille = Famille.create({"name": "HTTP Non alim", "code": "non_food"})
        consolidation = self.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-HTTP-RECU-%s" % self.gilles.id,
            "state": "collecting", "active": True,
            "company_id": self.societe.id, "transport_mode": "air",
            "direction": "export",
            "origin_country_id": self.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": self.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })
        partner = self.env["res.partner"].create({
            "name": "Aïssatou HTTP", "company_id": self.societe.id,
        })
        handle = self.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": partner.id, "company_id": self.societe.id,
        })
        return (self.env["dally.ops.intake.service"]
                .with_user(self.gilles).with_company(self.societe)
                .create_intake({
                    "request_uuid": str(uuid.uuid4()),
                    "consolidation_reference": consolidation.name,
                    "customer_reference": handle.token,
                    "received_on": "2026-08-30",
                    "line": {
                        "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                        "goods_category": "Non alimentaire",
                        "description": "Savon", "quantity": 1,
                        "announced_weight_kg": None, "exact_weight_kg": 13.5,
                        "length_cm": None, "width_cm": None, "height_cm": None,
                        "billing_method": "real",
                        "tariff_family_code": famille.code,
                        "customs_value_xof": 25000,
                    },
                }))["intake"]["reference"]

    def test_le_contrat_est_servi_dans_son_enveloppe(self):
        reference = self._dossier()
        reponse = self._lire(
            "/api/v1/ops/intakes/%s/receipt" % reference, "http.recu.gilles")
        self.assertEqual(reponse.status_code, 200, reponse.content[:300])
        charge = json.loads(reponse.content)
        self.assertTrue(charge["success"])
        self.assertEqual(sorted(charge["data"]), ["receipt"])
        self.assertEqual(charge["data"]["receipt"]["reference"], reference)
        self.assertEqual(reponse.headers.get("Cache-Control"),
                         "private, no-store, max-age=0")

    def test_le_pdf_est_servi_sans_qu_aucun_intermediaire_le_garde(self):
        reference = self._dossier()
        reponse = self._lire(
            "/api/v1/ops/intakes/%s/receipt/pdf" % reference, "http.recu.gilles")
        self.assertEqual(reponse.status_code, 200, reponse.content[:300])
        self.assertEqual(reponse.headers.get("Content-Type"), "application/pdf")
        self.assertTrue(reponse.content.startswith(b"%PDF"))
        self.assertGreater(len(reponse.content), 1000)
        # Un proxy partagé qui garderait ce document le servirait au client
        # suivant.
        self.assertEqual(reponse.headers.get("Cache-Control"),
                         "private, no-store, max-age=0")
        self.assertEqual(reponse.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(reponse.headers.get("Referrer-Policy"), "no-referrer")
        self.assertEqual(
            reponse.headers.get("Content-Disposition"),
            'attachment; filename="Recu_DallyTrading_%s.pdf"' % reference)
        # Aucun nom de client dans la liste des téléchargements.
        self.assertNotIn("ssatou", reponse.headers.get("Content-Disposition", ""))

    def _lire(self, chemin, login):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(chemin, allow_redirects=False)

    def test_un_dossier_inconnu_rend_404(self):
        reponse = self._lire(
            "/api/v1/ops/intakes/AIR-INCONNU-A001/receipt", "http.recu.gilles")
        self.assertEqual(reponse.status_code, 404)
        self.assertEqual(
            json.loads(reponse.content)["error"]["code"], "intake_not_found")

    def test_le_pdf_d_un_dossier_inconnu_rend_404_et_non_500(self):
        reponse = self._lire(
            "/api/v1/ops/intakes/AIR-INCONNU-A001/receipt/pdf", "http.recu.gilles")
        self.assertEqual(reponse.status_code, 404, reponse.content[:300])

    def test_un_authentifie_sans_role_ops_est_refuse(self):
        for chemin in ("/api/v1/ops/intakes/AIR-X-A001/receipt",
                       "/api/v1/ops/intakes/AIR-X-A001/receipt/pdf"):
            self.assertEqual(self._lire(chemin, "http.recu.autre").status_code, 403)

    def test_un_anonyme_est_renvoye_vers_la_connexion(self):
        for chemin in ("/api/v1/ops/intakes/AIR-X-A001/receipt",
                       "/api/v1/ops/intakes/AIR-X-A001/receipt/pdf"):
            self.assertIn(self._lire(chemin, None).status_code, (302, 303))

    def test_le_controleur_ne_contient_ni_sudo_ni_cle_d_api(self):
        import ast
        import inspect
        from odoo.addons.dally_ops_mobile.controllers import ops_receipts
        arbre = ast.parse(inspect.getsource(ops_receipts))
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                continue
            premier = noeud.body[0] if noeud.body else None
            if (isinstance(premier, ast.Expr)
                    and isinstance(premier.value, ast.Constant)
                    and isinstance(premier.value.value, str)):
                noeud.body = noeud.body[1:] or [ast.Pass()]
        code = ast.unparse(arbre)
        for interdit in ("sudo", "SUPERUSER_ID", "API_KEY", "api_key", "with_user"):
            self.assertNotIn(interdit, code)
        self.assertIn("auth='user'", code)
