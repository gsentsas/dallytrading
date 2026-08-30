# -*- coding: utf-8 -*-
"""Encaisser au comptoir, sans jamais perdre l'argent reçu.

La propriété centrale de cette étape n'est pas qu'un paiement se comptabilise :
c'est qu'il **survit** quand la comptabilité n'y arrive pas. Une facture pas
encore émise, un canal mal paramétré, une configuration incomplète — rien de
tout cela ne doit effacer l'argent que le client vient de donner.

Les tests ci-dessous vérifient donc autant les chemins qui réussissent que ceux
où la comptabilité échoue et où l'encaissement doit rester.
"""

import ast
import inspect
import json
import uuid

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.dally_ops_mobile.models.ops_errors import (
    DallyOpsConflict,
    DallyOpsError,
    DallyOpsNotFound,
)


def code_seul(module):
    arbre = ast.parse(inspect.getsource(module))
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, (ast.Module, ast.ClassDef,
                                  ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        premier = noeud.body[0] if noeud.body else None
        if (isinstance(premier, ast.Expr)
                and isinstance(premier.value, ast.Constant)
                and isinstance(premier.value.value, str)):
            noeud.body = noeud.body[1:] or [ast.Pass()]
    return ast.unparse(arbre)


@tagged("post_install", "-at_install", "dally")
class TestOpsPayments(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Le socle comptable d'Odoo tourne avec son propre utilisateur, qui n'a
        # aucun droit Freight. Ces ajouts vivent dans la transaction du test et
        # ne touchent ni les ACL du module, ni la production.
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.eur = cls.setup_other_currency("EUR")
        cls.xof = cls.setup_other_currency("XOF")
        cls.societe = cls.env.company
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Paiements Autre"})

        cls.logisticien = cls._compte(
            "paie.logi", "Gilles Paiements",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Gilles")
        cls.responsable = cls._compte(
            "paie.resp", "Dalanda Paiements",
            "dally_ops_mobile.group_dally_ops_supervisor", acteur="Dalanda")
        cls.sans_acteur = cls._compte(
            "paie.sansacteur", "Sans acteur",
            "dally_ops_mobile.group_dally_ops_logistician", acteur=False)
        cls.non_ops = cls._compte("paie.autre", "Sans rôle", "base.group_user")

        cls.canal_wave = cls._canal("wave", "Wave", cls.xof)
        cls.canal_especes = cls._canal("cash", "Espèces", cls.eur)

        cls.famille = cls.env["dally.freight.tariff.family"].create({
            "name": "Paiements Non alimentaire", "code": "paie_non_food",
        })
        cls.env["dally.freight.tariff.rule"].create({
            "name": "Paiements air 5 EUR", "transport_mode": "air",
            "family_id": cls.famille.id, "customer_segment": "individual",
            "price_per_kg_eur": 5.0,
        })
        cls.partner = cls.env["res.partner"].create({
            "name": "Aissatou Paiements", "company_id": cls.societe.id,
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.consolidation = cls._consolidation("AIR-DSS-CDG-PAIE-001")

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
    def _canal(cls, code, nom, devise, societe=None, actif=True):
        journal = cls.company_data["default_journal_bank"]
        methode = journal.inbound_payment_method_line_ids[:1]
        return cls.env["dally.freight.payment.channel"].create({
            "name": nom, "code": code,
            "company_id": (societe or cls.env.company).id,
            "currency_id": devise.id,
            "journal_id": journal.id,
            "payment_method_line_id": methode.id,
            "active": actif,
        })

    @classmethod
    def _consolidation(cls, reference):
        return cls.env["dally.freight.consolidation"].create({
            "name": reference, "state": "collecting", "active": True,
            "company_id": cls.env.company.id, "transport_mode": "air",
            "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })

    def _paiements(self, utilisateur=None):
        return (self.env["dally.ops.payment.service"]
                .with_user(utilisateur or self.logisticien)
                .with_company(self.societe))

    def _creer_dossier(self):
        resultat = (self.env["dally.ops.intake.service"]
                    .with_user(self.logisticien)
                    .with_company(self.societe)
                    .create_intake({
                        "request_uuid": str(uuid.uuid4()),
                        "consolidation_reference": self.consolidation.name,
                        "customer_reference": self.handle.token,
                        "received_on": "2026-08-28",
                        "line": {
                            "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                            "goods_category": "Non alimentaire", "description": "Savon",
                            "quantity": 1, "announced_weight_kg": None,
                            "exact_weight_kg": 13.5,
                            "length_cm": None, "width_cm": None, "height_cm": None,
                            "billing_method": "real",
                            "tariff_family_code": self.famille.code,
                            "customs_value_xof": 25000,
                        },
                    }))
        return resultat["intake"]["reference"]

    def _demande(self, **changements):
        demande = {
            "request_uuid": str(uuid.uuid4()),
            "amount": 44280.0,
            "payment_date": "2026-08-28",
            "payment_method": "wave",
            "currency_code": "XOF",
        }
        demande.update(changements)
        return demande

    def _shipment(self, reference):
        return self.env["dally.shipment"].sudo().search(
            [("external_reference", "=", reference)], limit=1)

    def _collections(self, reference):
        return self.env["dally.freight.collection"].sudo().search(
            [("shipment_id", "=", self._shipment(reference).id)])

    # ─── Canaux ──────────────────────────────────────────────────────

    def test_les_canaux_configures_sont_lisibles(self):
        canaux = self._paiements().list_payment_channels()
        codes = {(canal["code"], canal["currency_code"]) for canal in canaux}
        self.assertIn(("wave", "XOF"), codes)
        self.assertIn(("cash", "EUR"), codes)

    def test_le_dto_canal_ne_dit_rien_de_la_comptabilite(self):
        for canal in self._paiements().list_payment_channels():
            self.assertEqual(sorted(canal), ["code", "currency_code", "name"])
        contenu = json.dumps(self._paiements().list_payment_channels())
        for interdit in ("journal", "payment_method_line", "account", "bank",
                         "company_id", "currency_id"):
            self.assertNotIn(interdit, contenu)

    def test_un_canal_d_une_autre_societe_est_invisible(self):
        self._canal("orange", "Orange Money", self.xof, societe=self.autre_societe)
        codes = {canal["code"] for canal in self._paiements().list_payment_channels()}
        self.assertNotIn("orange", codes)

    def test_un_canal_inactif_est_invisible(self):
        self._canal("ancien", "Ancien canal", self.eur, actif=False)
        codes = {canal["code"] for canal in self._paiements().list_payment_channels()}
        self.assertNotIn("ancien", codes)

    # ─── Encaissement ────────────────────────────────────────────────

    def test_un_encaissement_est_enregistre(self):
        reference = self._creer_dossier()
        resultat = self._paiements().record_payment(reference, self._demande())

        self.assertEqual(resultat["status"], "created")
        paiement = resultat["payment"]
        self.assertEqual(paiement["amount"], 44280.0)
        self.assertEqual(paiement["currency_code"], "XOF")
        self.assertEqual(paiement["payment_method"], {"code": "wave", "name": "Wave"})
        self.assertEqual(paiement["collector"], "Gilles")
        self.assertEqual(len(self._collections(reference)), 1)

    def test_le_serveur_impose_la_source_et_la_cle_metier(self):
        reference = self._creer_dossier()
        demande = self._demande()
        self._paiements().record_payment(reference, demande)

        collection = self._collections(reference)
        self.assertEqual(collection.source, "backoffice")
        self.assertEqual(
            collection.external_payment_key, "ops:%s" % demande["request_uuid"])

    def test_le_collecteur_vient_de_la_configuration_et_non_du_nom(self):
        """Le rapprochement par nom d'affichage a été écarté dès l'étape 2."""
        reference = self._creer_dossier()
        self._paiements().record_payment(reference, self._demande())
        collection = self._collections(reference)

        self.assertEqual(collection.collected_by_name, "Gilles")
        self.assertNotEqual(collection.collected_by_name, self.logisticien.display_name)
        # Le compte Ops est non interne : il ne peut pas être « collecté par ».
        self.assertFalse(collection.collected_by_id)

    def test_renommer_le_compte_ne_change_pas_l_acteur(self):
        self.logisticien.name = "Gilles Renommé Autrement"
        reference = self._creer_dossier()
        self._paiements().record_payment(reference, self._demande())
        self.assertEqual(self._collections(reference).collected_by_name, "Gilles")

    def test_sans_acteur_configure_l_encaissement_est_refuse(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._paiements(self.sans_acteur).record_payment(reference, self._demande())
        self.assertEqual(erreur.exception.code, "cash_actor_not_configured")
        self.assertEqual(len(self._collections(reference)), 0)

    def test_le_navigateur_ne_choisit_ni_collecteur_ni_source(self):
        reference = self._creer_dossier()
        for cle, valeur in (("collected_by", "Quelqu'un"), ("source", "google_sheets"),
                            ("external_payment_key", "forge"), ("shipment_id", 1),
                            ("collected_by_name", "Autre")):
            with self.subTest(cle=cle):
                demande = self._demande()
                demande[cle] = valeur
                with self.assertRaises(DallyOpsError):
                    self._paiements().record_payment(reference, demande)

    # ─── Validation ──────────────────────────────────────────────────

    def test_un_montant_nul_ou_negatif_est_refuse(self):
        reference = self._creer_dossier()
        for montant in (0, -1, -44280.0):
            with self.subTest(montant=montant):
                with self.assertRaises(DallyOpsError):
                    self._paiements().record_payment(
                        reference, self._demande(amount=montant))

    def test_une_date_future_est_refusee(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as erreur:
            self._paiements().record_payment(
                reference, self._demande(payment_date="2099-01-01"))
        self.assertEqual(erreur.exception.code, "invalid_payment_date")

    def test_un_couple_methode_devise_non_configure_est_refuse(self):
        """Wave existe en francs, pas en euros : on refuse plutôt que d'inventer."""
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as erreur:
            self._paiements().record_payment(
                reference, self._demande(currency_code="EUR"))
        self.assertEqual(erreur.exception.code, "payment_channel_not_available")
        self.assertEqual(len(self._collections(reference)), 0)

    def test_une_faute_de_frappe_ne_devient_pas_une_ecriture(self):
        reference = self._creer_dossier()
        for methode in ("wvae", "wawe", "cashh"):
            with self.subTest(methode=methode):
                with self.assertRaises(DallyOpsError):
                    self._paiements().record_payment(
                        reference, self._demande(payment_method=methode))

    def test_un_dossier_inexistant_ou_d_une_autre_societe_est_introuvable(self):
        with self.assertRaises(DallyOpsNotFound):
            self._paiements().record_payment("AIR-INEXISTANT-A001", self._demande())

    def test_un_dossier_annule_refuse_l_encaissement(self):
        reference = self._creer_dossier()
        self._shipment(reference).sudo()._write_state_from_operational_source("cancelled")
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._paiements().record_payment(reference, self._demande())
        self.assertEqual(erreur.exception.code, "intake_cancelled")

    # ─── L'argent survit à la comptabilité ───────────────────────────

    def test_sans_facture_postee_l_encaissement_reste_en_attente(self):
        """Le cas le plus courant, et ce n'est pas une erreur."""
        reference = self._creer_dossier()
        resultat = self._paiements().record_payment(reference, self._demande())

        self.assertEqual(resultat["payment"]["accounting_status"], "pending")
        collection = self._collections(reference)
        self.assertEqual(collection.state, "pending")
        self.assertFalse(collection.payment_id)
        # L'argent est là, même si la facture ne l'est pas encore.
        self.assertEqual(collection.amount, 44280.0)

    def test_avec_une_facture_postee_l_encaissement_est_comptabilise(self):
        """Facture postée et canal valide : le moteur va jusqu'au bout."""
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        facture = shipment.sudo().action_prepare_native_freight_invoice()
        facture.action_post()

        avant = self.env["account.payment"].sudo().search_count([])
        resultat = self._paiements().record_payment(
            reference, self._demande(amount=10.0, payment_method="cash",
                                     currency_code="EUR"))

        collection = self._collections(reference)
        collection.invalidate_recordset()
        self.assertEqual(resultat["payment"]["accounting_status"], "registered")
        self.assertEqual(collection.state, "registered")
        self.assertTrue(collection.payment_id)
        # Exactement une écriture comptable, pas deux.
        self.assertEqual(
            self.env["account.payment"].sudo().search_count([]), avant + 1)

    def test_un_rejeu_apres_comptabilisation_ne_recomptabilise_pas(self):
        """Le scénario du §42 : la réponse se perd après comptabilisation."""
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        facture = shipment.sudo().action_prepare_native_freight_invoice()
        facture.action_post()

        demande = self._demande(amount=10.0, payment_method="cash",
                                currency_code="EUR")
        premier = self._paiements().record_payment(reference, demande)
        self.assertEqual(premier["payment"]["accounting_status"], "registered")

        avant = self.env["account.payment"].sudo().search_count([])
        rejeu = self._paiements().record_payment(reference, demande)

        self.assertEqual(rejeu["status"], "replayed")
        self.assertEqual(rejeu["payment"], premier["payment"])
        self.assertEqual(len(self._collections(reference)), 1)
        self.assertEqual(self.env["account.payment"].sudo().search_count([]), avant)

    def test_une_erreur_comptable_ne_fait_pas_disparaitre_l_encaissement(self):
        """La propriété fondamentale de cette étape."""
        reference = self._creer_dossier()
        collection = self.env["dally.freight.collection"].sudo().create({
            "external_payment_key": "ops:%s" % uuid.uuid4(),
            "shipment_id": self._shipment(reference).id,
            "amount": 1000.0, "currency_id": self.xof.id,
            "payment_date": "2026-08-28", "source_method": "wave",
            "source": "backoffice", "collected_by_name": "Gilles",
        })
        collection.write({"state": "error", "error_message": "journal introuvable"})

        paiements = self._paiements().payments_for(self._shipment(reference))
        correspondant = [p for p in paiements if p["amount"] == 1000.0]
        self.assertEqual(len(correspondant), 1)
        # L'encaissement existe et se signale comme à vérifier.
        self.assertEqual(correspondant[0]["accounting_status"], "needs_review")

    def test_le_dto_ne_recopie_pas_le_message_comptable(self):
        reference = self._creer_dossier()
        collection = self.env["dally.freight.collection"].sudo().create({
            "external_payment_key": "ops:%s" % uuid.uuid4(),
            "shipment_id": self._shipment(reference).id,
            "amount": 1000.0, "currency_id": self.xof.id,
            "payment_date": "2026-08-28", "source_method": "wave",
            "source": "backoffice", "collected_by_name": "Gilles",
        })
        collection.write({
            "state": "error",
            "error_message": "journal BNK1 introuvable pour la société 1",
        })
        contenu = json.dumps(
            self._paiements().payments_for(self._shipment(reference)), ensure_ascii=False)
        # Un journal et un numéro de société ne disent rien d'actionnable à un
        # logisticien, et décrivent la configuration interne.
        for interdit in ("BNK1", "journal", "error_message"):
            self.assertNotIn(interdit, contenu)

    # ─── Idempotence ─────────────────────────────────────────────────

    def test_un_rejeu_ne_cree_pas_un_second_encaissement(self):
        reference = self._creer_dossier()
        demande = self._demande()
        premier = self._paiements().record_payment(reference, demande)
        second = self._paiements().record_payment(reference, demande)

        self.assertEqual(second["status"], "replayed")
        self.assertEqual(second["payment"], premier["payment"])
        self.assertEqual(len(self._collections(reference)), 1)

    def test_un_rejeu_ne_produit_aucune_ecriture_comptable_de_plus(self):
        reference = self._creer_dossier()
        demande = self._demande()
        self._paiements().record_payment(reference, demande)
        avant = self.env["account.payment"].sudo().search_count([])
        self._paiements().record_payment(reference, demande)
        self.assertEqual(self.env["account.payment"].sudo().search_count([]), avant)

    def test_le_meme_identifiant_avec_une_autre_intention_est_un_conflit(self):
        reference = self._creer_dossier()
        demande = self._demande()
        self._paiements().record_payment(reference, demande)
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._paiements().record_payment(
                reference, dict(demande, amount=999.0))
        self.assertEqual(erreur.exception.code, "idempotency_conflict")

    def test_plusieurs_encaissements_coexistent(self):
        reference = self._creer_dossier()
        self._paiements().record_payment(reference, self._demande(amount=30000.0))
        self._paiements().record_payment(reference, self._demande(amount=14280.0))
        self.assertEqual(len(self._collections(reference)), 2)

    # ─── Le dossier ──────────────────────────────────────────────────

    def test_le_dossier_montre_ses_encaissements(self):
        reference = self._creer_dossier()
        self._paiements().record_payment(reference, self._demande())
        detail = (self.env["dally.ops.intake.line.service"]
                  .with_user(self.logisticien).with_company(self.societe)
                  .get_intake(reference))["intake"]

        self.assertEqual(len(detail["payments"]), 1)
        self.assertEqual(detail["payments"][0]["amount"], 44280.0)
        self.assertEqual(sorted(detail["payments"][0]), [
            "accounting_status", "amount", "collector", "currency_code",
            "payment_date", "payment_method", "reference"])

    def test_un_encaissement_annule_n_apparait_pas(self):
        reference = self._creer_dossier()
        self._paiements().record_payment(reference, self._demande())
        self._collections(reference).write({"state": "cancelled"})
        detail = (self.env["dally.ops.intake.line.service"]
                  .with_user(self.logisticien).with_company(self.societe)
                  .get_intake(reference))["intake"]
        self.assertEqual(detail["payments"], [])

    def test_le_total_est_donne_par_devise_sans_conversion(self):
        """Additionner des euros et des francs demanderait un taux."""
        reference = self._creer_dossier()
        self._paiements().record_payment(reference, self._demande(amount=44280.0))
        self._paiements().record_payment(reference, self._demande(
            amount=50.0, payment_method="cash", currency_code="EUR"))

        detail = (self.env["dally.ops.intake.line.service"]
                  .with_user(self.logisticien).with_company(self.societe)
                  .get_intake(reference))["intake"]
        resume = {ligne["currency_code"]: ligne["amount"]
                  for ligne in detail["payment_summary"]}
        self.assertEqual(resume, {"EUR": 50.0, "XOF": 44280.0})

    # ─── DTO ─────────────────────────────────────────────────────────

    def test_le_dto_ne_contient_aucun_identifiant_odoo(self):
        reference = self._creer_dossier()
        resultat = self._paiements().record_payment(reference, self._demande())
        contenu = json.dumps(resultat, ensure_ascii=False)
        for interdit in ("collection_id", "shipment_id", "partner_id", "invoice_id",
                         "account_payment_id", "journal_id", "payment_method_line_id",
                         "currency_id", "company_id", "external_payment_key"):
            self.assertNotIn(interdit, contenu)

    def test_la_reference_publique_ne_porte_pas_le_prefixe_interne(self):
        reference = self._creer_dossier()
        demande = self._demande()
        resultat = self._paiements().record_payment(reference, demande)
        self.assertEqual(resultat["payment"]["reference"], demande["request_uuid"])
        self.assertNotIn("ops:", resultat["payment"]["reference"])

    # ─── Rôles et audit ──────────────────────────────────────────────

    def test_les_deux_roles_ops_encaissent_et_les_autres_non(self):
        reference = self._creer_dossier()
        self.assertEqual(
            self._paiements(self.responsable).record_payment(
                reference, self._demande())["status"], "created")
        with self.assertRaises(AccessError):
            self._paiements(self.non_ops).list_payment_channels()

    def test_l_encaissement_est_attribue_a_son_operateur(self):
        reference = self._creer_dossier()
        demande = self._demande()
        self._paiements().record_payment(reference, demande)
        evenement = self.env["dally.ops.audit.event"].sudo().search(
            [("request_uuid", "=", demande["request_uuid"]),
             ("action", "=", "payment_recorded")], limit=1)

        self.assertTrue(evenement)
        self.assertEqual(evenement.operator_user_id, self.logisticien)
        self.assertEqual(evenement.entity_model, "dally.freight.collection")

    def test_le_rejeu_est_trace_comme_tel(self):
        reference = self._creer_dossier()
        demande = self._demande()
        self._paiements().record_payment(reference, demande)
        self._paiements().record_payment(reference, demande)
        self.assertEqual(self.env["dally.ops.audit.event"].sudo().search_count(
            [("request_uuid", "=", demande["request_uuid"]),
             ("action", "=", "payment_request_replayed")]), 1)

    def test_l_audit_ne_contient_aucune_donnee_personnelle(self):
        reference = self._creer_dossier()
        demande = self._demande()
        self._paiements().record_payment(reference, demande)
        evenement = self.env["dally.ops.audit.event"].sudo().search(
            [("request_uuid", "=", demande["request_uuid"])], limit=1)
        self.env.cr.execute(
            "SELECT * FROM dally_ops_audit_event WHERE id = %s", [evenement.id])
        stocke = " ".join(str(valeur) for valeur in self.env.cr.fetchone())
        for interdit in ("Aissatou", "Gilles", "44280"):
            self.assertNotIn(interdit, stocke)

    # ─── Frontière de privilège ──────────────────────────────────────

    def test_le_controleur_ne_contient_aucun_sudo(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_payments
        self.assertNotIn("sudo", code_seul(ops_payments))

    def test_ops_n_appelle_pas_la_route_freight_a_cle_d_api(self):
        from odoo.addons.dally_ops_mobile.models import ops_payment_service
        from odoo.addons.dally_ops_mobile.controllers import ops_payments
        for module in (ops_payment_service, ops_payments):
            code = code_seul(module)
            for interdit in ("api_key", "required_scope", "freight:payment",
                             "/api/v1/freight", "DallyApiController"):
                self.assertNotIn(interdit, code)

    def test_le_logisticien_ne_lit_aucun_modele_comptable(self):
        for nom in ("dally.freight.collection", "dally.freight.payment.channel",
                    "account.payment", "account.move", "account.journal"):
            with self.subTest(modele=nom):
                self.assertFalse(
                    self.env[nom].with_user(self.logisticien).has_access("read"),
                    "%s est devenu lisible" % nom)
