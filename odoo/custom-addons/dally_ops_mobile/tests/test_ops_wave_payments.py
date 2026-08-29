# -*- coding: utf-8 -*-
"""Encaisser par Wave, sur le dossier qui le justifie.

## Les deux propriétés que ces tests protègent

La première : le terrain **ne choisit ni le moyen ni le bénéficiaire**. Un
navigateur qui enverrait « espèces » ou « Dalanda » est refusé, et le serveur
n'écoute pas davantage un champ qui porterait par hasard les bonnes valeurs —
sans quoi un client finirait par croire qu'il les décide.

La seconde : le client n'est jamais saisi. Il vient du dossier par une
relation stockée en lecture seule, ce qui rend le paiement d'Aissatou
structurellement impossible à imputer à Fatou. Les tests le vérifient
malgré tout, parce qu'une relation peut être défaite par mégarde.

## Ce que ces tests figent aussi

Qu'enregistrer un encaissement ne crée pas de dossier, ne consomme pas de
numéro, ne touche pas aux colis, et ne poste aucune facture. Ce sont des
absences ; personne ne les remarquerait avant le rapprochement.
"""

import ast
import inspect
import json
import uuid

from odoo import SUPERUSER_ID
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.dally_ops_mobile.models.ops_errors import (
    DallyOpsConflict,
    DallyOpsError,
    DallyOpsNotFound,
)


def code_seul(module):
    """Le code d'un module, ses textes d'explication retirés."""
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
class TestOpsWavePayments(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.xof = cls.setup_other_currency("XOF")
        cls.eur = cls.setup_other_currency("EUR")
        cls.societe = cls.env.company
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Wave Autre"})

        cls.gilles = cls._compte(
            "wave.gilles", "Gilles Caisse",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Gilles")
        cls.dalanda = cls._compte(
            "wave.dalanda", "Dalanda Terrain",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Dalanda")
        cls.non_ops = cls._compte("wave.autre", "Sans rôle", "base.group_user")

        # Le bénéficiaire est une **configuration**, jamais une constante de
        # code ni un identifiant numérique.
        cls.societe.sudo().write({"dally_ops_wave_beneficiary": "Gilles"})

        cls.canal_wave = cls._canal("wave", "Wave", cls.xof)
        cls.canal_especes = cls._canal("cash", "Espèces", cls.eur)

        cls.famille = cls.env["dally.freight.tariff.family"].create({
            "name": "Wave Non alimentaire", "code": "wave_non_food",
        })
        cls.env["dally.freight.tariff.rule"].create({
            "name": "Wave air 5 EUR", "transport_mode": "air",
            "family_id": cls.famille.id, "customer_segment": "all",
            "price_per_kg_eur": 5.0,
        })
        cls.partner = cls.env["res.partner"].create({
            "name": "Aissatou Wave", "company_id": cls.societe.id,
        })
        cls.autre_partner = cls.env["res.partner"].create({
            "name": "Fatou Wave", "company_id": cls.societe.id,
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.consolidation = cls._consolidation("AIR-DSS-CDG-WAVE-001")

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
    def _canal(cls, code, nom, devise, societe=None):
        journal = cls.company_data["default_journal_bank"]
        methode = journal.inbound_payment_method_line_ids[:1]
        return cls.env["dally.freight.payment.channel"].create({
            "name": nom, "code": code,
            "company_id": (societe or cls.env.company).id,
            "currency_id": devise.id,
            "journal_id": journal.id,
            "payment_method_line_id": methode.id,
            "active": True,
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

    def _service(self, utilisateur=None):
        return (self.env["dally.ops.wave.payment.service"]
                .with_user(utilisateur or self.gilles)
                .with_company(self.societe))

    def _creer_dossier(self):
        resultat = (self.env["dally.ops.intake.service"]
                    .with_user(self.gilles)
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

    def _valeur_sequence(self, sequence):
        """La valeur réelle de la séquence, lue dans PostgreSQL.

        `number_next_actual` ne bouge pas quand la séquence est servie par un
        objet `SEQUENCE` natif : mesuré sur le banc, le champ restait à 1
        pendant que la séquence en était à 120. Une assertion portée sur lui
        aurait laissé passer une consommation de numéro — précisément ce que ce
        test existe pour interdire.
        """
        self.env.cr.execute(
            "SELECT last_value FROM pg_sequences WHERE sequencename = %s",
            ["ir_sequence_%03d" % sequence.id])
        ligne = self.env.cr.fetchone()
        # Repli sur le champ Odoo si la séquence n'est pas servie par un objet
        # natif : l'assertion garde alors son sens, faute de mieux.
        return ligne[0] if ligne else ("odoo", sequence.number_next_actual)

    def _demande(self, **changements):
        demande = {
            "request_uuid": str(uuid.uuid4()),
            "amount": 100000.0,
            "currency": "XOF",
            "wave_reference": "TWXYZ12345",
            "paid_at": "2026-08-28",
            "note": "",
        }
        demande.update(changements)
        return demande

    def _shipment(self, reference):
        return self.env["dally.shipment"].sudo().search(
            [("external_reference", "=", reference)], limit=1)

    def _collections(self, reference):
        return self.env["dally.freight.collection"].sudo().search(
            [("shipment_id", "=", self._shipment(reference).id)])

    # ─── Le rôle ─────────────────────────────────────────────────────

    def test_un_compte_sans_role_ops_ne_peut_rien_faire(self):
        reference = self._creer_dossier()
        for appel in (
            lambda: self._service(self.non_ops).payment_context(reference),
            lambda: self._service(self.non_ops).list_payments(reference),
            lambda: self._service(self.non_ops).record_wave_payment(
                reference, self._demande()),
        ):
            with self.assertRaises(AccessError):
                appel()

    # ─── L'encaissement ──────────────────────────────────────────────

    def test_un_encaissement_wave_est_ecrit_tel_que_le_serveur_le_decide(self):
        reference = self._creer_dossier()
        demande = self._demande()
        resultat = self._service().record_wave_payment(reference, demande)
        self.assertEqual(resultat["status"], "created")

        collections = self._collections(reference)
        self.assertEqual(len(collections), 1)
        self.assertEqual(collections.source_method, "wave")
        self.assertEqual(collections.collected_by_name, "Gilles")
        self.assertEqual(collections.amount, 100000.0)
        self.assertEqual(collections.currency_id, self.xof)
        self.assertEqual(collections.wave_reference, "TWXYZ12345")
        self.assertEqual(collections.source, "backoffice")
        self.assertEqual(
            collections.external_payment_key, "ops:%s" % demande["request_uuid"])

    def test_le_moyen_est_wave_meme_si_le_navigateur_n_en_parle_pas(self):
        reference = self._creer_dossier()
        # Le contrat n'a aucun champ de moyen ; le serveur en impose un.
        self.assertNotIn("payment_method", self._demande())
        self._service().record_wave_payment(reference, self._demande())
        self.assertEqual(self._collections(reference).source_method, "wave")

    def test_le_beneficiaire_est_celui_de_la_societe_pas_l_operateur(self):
        """Un encaissement Wave n'entre pas dans la poche de qui le saisit."""
        reference = self._creer_dossier()
        # Dalanda saisit, mais l'argent arrive chez Gilles.
        self._service(self.dalanda).record_wave_payment(reference, self._demande())
        self.assertEqual(self._collections(reference).collected_by_name, "Gilles")

    def test_le_beneficiaire_resolu_n_est_pas_le_superutilisateur(self):
        _nom, compte = self._service()._beneficiaire()
        self.assertNotEqual(compte.id, SUPERUSER_ID)
        self.assertEqual(compte, self.gilles)
        self.assertTrue(compte.active)

    def test_sans_configuration_l_encaissement_est_refuse(self):
        self.societe.sudo().write({"dally_ops_wave_beneficiary": False})
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service().record_wave_payment(reference, self._demande())
        self.assertEqual(erreur.exception.code, "wave_beneficiary_not_configured")
        self.assertEqual(len(self._collections(reference)), 0)

    def test_un_beneficiaire_ambigu_bloque_l_encaissement(self):
        self._compte("wave.gilles2", "Gilles Bis",
                     "dally_ops_mobile.group_dally_ops_logistician", acteur="  GILLES ")
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service().record_wave_payment(reference, self._demande())
        self.assertEqual(erreur.exception.code, "cash_actor_configuration_conflict")

    def test_le_client_vient_du_dossier_et_de_nulle_part_ailleurs(self):
        reference = self._creer_dossier()
        self._service().record_wave_payment(reference, self._demande())
        collection = self._collections(reference)
        self.assertEqual(collection.partner_id, self.partner)
        self.assertEqual(collection.shipment_id, self._shipment(reference))
        self.assertEqual(collection.company_id, self.societe)
        # La relation est stockée et en lecture seule : le client n'est pas
        # une donnée du paiement, c'est une propriété du dossier.
        self.assertTrue(
            self.env["dally.freight.collection"]._fields["partner_id"].related)

    def test_impossible_de_rattacher_le_paiement_a_un_autre_client(self):
        reference = self._creer_dossier()
        for champ in ("partner_id", "customer_id", "user_id"):
            with self.assertRaises(DallyOpsError):
                self._service().record_wave_payment(
                    reference, self._demande(**{champ: self.autre_partner.id}))
        self.assertEqual(len(self._collections(reference)), 0)

    def test_un_champ_reserve_est_refuse_en_tant_que_tel(self):
        """Le motif du refus compte autant que le refus.

        Un contrat strict rejette déjà toute clé inconnue — une faute de frappe
        comme une tentative. Mais « champ réservé au serveur » et « champ non
        pris en charge » ne disent pas la même chose à qui lit les journaux, et
        le premier message est le seul qui signale qu'on a essayé de choisir ce
        que le serveur impose.

        Sans ce test, retirer un nom de la liste des champs réservés ne casse
        rien de visible : le refus demeure, sa raison disparaît.
        """
        reference = self._creer_dossier()
        for champ in ("partner_id", "customer_id", "beneficiary",
                      "beneficiary_user_id", "payment_method", "method",
                      "collected_by_name", "shipment_id", "user_id"):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_wave_payment(
                    reference, self._demande(**{champ: "x"}))
            self.assertIn("réservé au serveur", str(erreur.exception), champ)

    def test_un_champ_decide_par_le_serveur_est_refuse(self):
        reference = self._creer_dossier()
        for champ, valeur in (
            ("payment_method", "wave"),
            ("method", "cash"),
            ("beneficiary", "Gilles"),
            ("beneficiary_user_id", 1),
            ("collected_by_name", "Dalanda"),
            ("source", "google_sheets"),
            ("external_payment_key", "ops:x"),
            ("shipment_id", 1),
            ("invoice_id", 1),
            ("company_id", 1),
            ("state", "registered"),
        ):
            with self.assertRaises(DallyOpsError):
                self._service().record_wave_payment(
                    reference, self._demande(**{champ: valeur}))
        self.assertEqual(len(self._collections(reference)), 0)

    def test_un_champ_obligatoire_manquant_est_refuse(self):
        reference = self._creer_dossier()
        for champ in ("request_uuid", "amount", "currency", "paid_at",
                      "wave_reference", "note"):
            demande = self._demande()
            demande.pop(champ)
            with self.assertRaises(DallyOpsError):
                self._service().record_wave_payment(reference, demande)

    def test_un_montant_nul_ou_negatif_est_refuse(self):
        reference = self._creer_dossier()
        for montant in (0, -1, 0.0, -100000.0, True, "100000", None):
            with self.assertRaises(DallyOpsError):
                self._service().record_wave_payment(
                    reference, self._demande(amount=montant))

    def test_une_devise_sans_canal_wave_est_refusee(self):
        reference = self._creer_dossier()
        # Les espèces existent en euros ; Wave, non. Proposer une devise sans
        # canal ferait échouer la saisie au comptoir, devant le client.
        for code in ("EUR", "USD", "ZZZ", ""):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_wave_payment(
                    reference, self._demande(currency=code))
            self.assertIn(
                erreur.exception.code,
                ("payment_channel_not_available", "invalid_request"))
        self.assertEqual(len(self._collections(reference)), 0)

    def test_le_code_devise_est_normalise_en_majuscules(self):
        reference = self._creer_dossier()
        # « xof » et « XOF » désignent la même devise ; refuser la première
        # ferait échouer une saisie parfaitement correcte.
        resultat = self._service().record_wave_payment(
            reference, self._demande(currency="xof"))
        self.assertEqual(resultat["payment"]["currency_code"], "XOF")
        self.assertEqual(self._collections(reference).currency_id, self.xof)

    def test_une_date_illisible_ou_future_est_refusee(self):
        reference = self._creer_dossier()
        for valeur in ("", "28/08/2026", "2026-13-01", "hier", None, 20260828,
                       "2099-01-01"):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_wave_payment(
                    reference, self._demande(paid_at=valeur))
            self.assertEqual(erreur.exception.code, "invalid_paid_at")

    def test_un_dossier_inconnu_ou_d_une_autre_societe_est_introuvable(self):
        for valeur in ("AIR-FAUX-A001", "A001", "", "  "):
            with self.assertRaises(DallyOpsNotFound) as erreur:
                self._service().record_wave_payment(valeur, self._demande())
            self.assertEqual(erreur.exception.code, "intake_not_found")

    def test_un_dossier_d_une_autre_societe_reste_invisible(self):
        reference = self._creer_dossier()
        # Un compte de l'autre société : changer de société pour un compte qui
        # n'y a pas accès est refusé par Odoo avant même d'atteindre le service.
        etranger = self.env["res.users"].create({
            "name": "Ops Ailleurs", "login": "wave.ailleurs",
            "group_ids": [(6, 0, [self.env.ref(
                "dally_ops_mobile.group_dally_ops_logistician").id])],
            "company_id": self.autre_societe.id,
            "company_ids": [(6, 0, [self.autre_societe.id])],
            "dally_ops_cash_actor": "Gilles",
        })
        autre = (self.env["dally.ops.wave.payment.service"]
                 .with_user(etranger)
                 .with_company(self.autre_societe))
        with self.assertRaises(DallyOpsNotFound):
            autre.record_wave_payment(reference, self._demande())
        self.assertEqual(len(self._collections(reference)), 0)

    # ─── La référence Wave ───────────────────────────────────────────

    def test_la_reference_wave_est_facultative(self):
        reference = self._creer_dossier()
        for valeur in (None, "", "   "):
            resultat = self._service().record_wave_payment(
                reference, self._demande(wave_reference=valeur))
            self.assertEqual(resultat["payment"]["wave_reference"], "")
        # Trois encaissements sans référence coexistent : l'unicité ne gêne
        # jamais les lignes sans numéro.
        self.assertEqual(len(self._collections(reference)), 3)

    def test_la_reference_wave_est_normalisee(self):
        reference = self._creer_dossier()
        resultat = self._service().record_wave_payment(
            reference, self._demande(wave_reference="  tw abc-123  "))
        self.assertEqual(resultat["payment"]["wave_reference"], "TWABC-123")

    def test_une_reference_wave_mal_formee_est_refusee(self):
        reference = self._creer_dossier()
        for valeur in ("ab", "-abc123", "a" * 65, "tw/123", "tw 12$", 42):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_wave_payment(
                    reference, self._demande(wave_reference=valeur))
            self.assertEqual(erreur.exception.code, "invalid_wave_reference")

    def test_un_meme_transfert_wave_ne_paie_pas_deux_dossiers(self):
        """L'erreur de comptoir la plus facile à commettre."""
        premier = self._creer_dossier()
        second = self._creer_dossier()
        self._service().record_wave_payment(
            premier, self._demande(wave_reference="TWSAME999"))
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service().record_wave_payment(
                second, self._demande(wave_reference="twsame999"))
        self.assertEqual(erreur.exception.code, "wave_reference_already_used")
        self.assertEqual(len(self._collections(second)), 0)

    def test_la_base_refuse_aussi_le_doublon_de_reference(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        self.env["dally.freight.collection"].sudo().create({
            "external_payment_key": "test:un", "shipment_id": shipment.id,
            "amount": 1.0, "currency_id": self.xof.id, "payment_date": "2026-08-28",
            "source_method": "wave", "wave_reference": "TWDB0001",
        })
        with self.assertRaises(Exception):
            self.env["dally.freight.collection"].sudo().create({
                "external_payment_key": "test:deux", "shipment_id": shipment.id,
                "amount": 1.0, "currency_id": self.xof.id,
                "payment_date": "2026-08-28",
                "source_method": "wave", "wave_reference": "TWDB0001",
            })

    def test_une_reference_faite_d_espaces_est_refusee_par_le_modele(self):
        reference = self._creer_dossier()
        with self.assertRaises(ValidationError):
            self.env["dally.freight.collection"].sudo().create({
                "external_payment_key": "test:blanc",
                "shipment_id": self._shipment(reference).id,
                "amount": 1.0, "currency_id": self.xof.id,
                "payment_date": "2026-08-28",
                "source_method": "wave", "wave_reference": "   ",
            })

    # ─── L'idempotence et les paiements partiels ─────────────────────

    def test_une_demande_rejouee_ne_cree_qu_un_encaissement(self):
        reference = self._creer_dossier()
        demande = self._demande()
        premier = self._service().record_wave_payment(reference, demande)
        second = self._service().record_wave_payment(reference, dict(demande))
        self.assertEqual(premier["status"], "created")
        self.assertEqual(second["status"], "replayed")
        self.assertEqual(premier["payment"]["reference"],
                         second["payment"]["reference"])
        self.assertEqual(len(self._collections(reference)), 1)

    def test_le_meme_identifiant_avec_d_autres_informations_est_un_conflit(self):
        reference = self._creer_dossier()
        demande = self._demande()
        self._service().record_wave_payment(reference, demande)
        for changement in ({"amount": 50000.0}, {"paid_at": "2026-08-27"},
                           {"wave_reference": "TWAUTRE99"}, {"note": "autre"}):
            with self.assertRaises(DallyOpsConflict) as erreur:
                self._service().record_wave_payment(
                    reference, dict(demande, **changement))
            self.assertEqual(erreur.exception.code, "idempotency_conflict")
        self.assertEqual(len(self._collections(reference)), 1)

    def test_deux_encaissements_partiels_coexistent_sur_le_meme_dossier(self):
        reference = self._creer_dossier()
        self._service().record_wave_payment(
            reference, self._demande(amount=100000.0, wave_reference="TWPART001"))
        self._service().record_wave_payment(
            reference, self._demande(amount=50000.0, wave_reference="TWPART002"))

        collections = self._collections(reference)
        self.assertEqual(len(collections), 2)
        self.assertEqual(sorted(collections.mapped("amount")), [50000.0, 100000.0])
        self.assertEqual(set(collections.mapped("shipment_id.id")),
                         {self._shipment(reference).id})
        resume = self._service().list_payments(reference)["summary"]
        self.assertEqual(resume, [{"currency_code": "XOF", "amount": 150000.0}])

    def test_un_identifiant_de_demande_invalide_est_refuse(self):
        reference = self._creer_dossier()
        for valeur in ("", "pas-un-uuid", None, 42):
            with self.assertRaises(DallyOpsError):
                self._service().record_wave_payment(
                    reference, self._demande(request_uuid=valeur))

    def test_l_encaissement_prend_un_verrou_sur_la_demande(self):
        from odoo.addons.dally_ops_mobile.models import ops_wave_payment_service
        code = code_seul(ops_wave_payment_service)
        self.assertIn("ops-payment-request:%s", code)
        self.assertIn("pg_advisory_xact_lock", code)

    def test_deux_demandes_successives_ne_produisent_qu_un_audit(self):
        """La sérialisation, faute de vraie concurrence sur ce banc.

        Le serveur de test d'Odoo partage un curseur unique entre les
        requêtes : deux appels simultanés y sont exécutés l'un après l'autre.
        Ce test vérifie l'invariant que le verrou protège — une seule ligne,
        un seul audit — le verrou lui-même étant vérifié par lecture du code.
        """
        reference = self._creer_dossier()
        demande = self._demande()
        self._service().record_wave_payment(reference, demande)
        self._service().record_wave_payment(reference, dict(demande))
        self.assertEqual(len(self._collections(reference)), 1)
        self.assertEqual(self.env["dally.ops.audit.event"].sudo().search_count([
            ("action", "=", "wave_payment_recorded"),
            ("request_uuid", "=", demande["request_uuid"])]), 1)
        self.assertEqual(self.env["dally.ops.audit.event"].sudo().search_count([
            ("action", "=", "wave_payment_request_replayed"),
            ("request_uuid", "=", demande["request_uuid"])]), 1)

    def test_l_audit_nomme_l_operateur_reel_et_pas_le_beneficiaire(self):
        reference = self._creer_dossier()
        demande = self._demande()
        self._service(self.dalanda).record_wave_payment(reference, demande)
        evenement = self.env["dally.ops.audit.event"].sudo().search([
            ("action", "=", "wave_payment_recorded"),
            ("request_uuid", "=", demande["request_uuid"])])
        self.assertEqual(len(evenement), 1)
        # Qui a saisi, pas qui a reçu : ce sont deux questions différentes.
        self.assertEqual(evenement.operator_user_id, self.dalanda)
        self.assertEqual(evenement.entity_model, "dally.freight.collection")

    # ─── Ce que l'encaissement ne fait pas ───────────────────────────

    def test_aucun_dossier_ni_numero_ni_colis_n_est_touche(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        sequence = self.consolidation.intake_sequence_id.sudo()

        avant_dossiers = self.env["dally.shipment"].sudo().search_count([])
        avant_sequence = self._valeur_sequence(sequence)
        avant_colis = [
            (p.id, p.description, p.quantity, p.total_weight_kg, p.customs_value_xof)
            for p in shipment.package_ids
        ]
        avant_reference = shipment.external_reference

        self._service().record_wave_payment(reference, self._demande())

        self.assertEqual(
            self.env["dally.shipment"].sudo().search_count([]), avant_dossiers)
        self.assertEqual(self._valeur_sequence(sequence), avant_sequence)
        self.assertEqual(shipment.external_reference, avant_reference)
        self.assertEqual(
            [(p.id, p.description, p.quantity, p.total_weight_kg, p.customs_value_xof)
             for p in shipment.package_ids], avant_colis)

    def test_aucune_facture_n_est_creee_ni_postee(self):
        """Un encaissement n'émet pas de facture.

        L'inverse serait tentant — le client a payé, donc facturons — et
        produirait des pièces comptables au rythme des saisies de comptoir,
        sans qu'aucun responsable ne l'ait décidé.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        avant = self.env["account.move"].sudo().search_count([])
        facture_avant = shipment.invoice_id

        self._service().record_wave_payment(reference, self._demande())

        self.assertEqual(self.env["account.move"].sudo().search_count([]), avant)
        self.assertEqual(shipment.invoice_id, facture_avant)

    def test_une_facture_existante_n_est_ni_postee_ni_modifiee(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        facture = self.env["account.move"].sudo().create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "company_id": self.societe.id,
            "invoice_date": "2026-08-28",
            "currency_id": self.xof.id,
        })
        shipment.sudo().write({"invoice_id": facture.id})
        etat_avant = facture.state

        self._service().record_wave_payment(reference, self._demande())

        facture.invalidate_recordset(["state"])
        self.assertEqual(facture.state, etat_avant)
        self.assertEqual(facture.state, "draft")
        self.assertEqual(shipment.invoice_id, facture)

    def test_l_encaissement_n_est_pas_un_transfert_ni_une_depense(self):
        """Trois objets distincts, jamais confondus."""
        reference = self._creer_dossier()
        avant_transferts = self.env["dally.cash.transfer"].sudo().search_count([])
        avant_depenses = self.env["dally.cash.expense"].sudo().search_count([])

        self._service().record_wave_payment(reference, self._demande())

        self.assertEqual(
            self.env["dally.cash.transfer"].sudo().search_count([]), avant_transferts)
        self.assertEqual(
            self.env["dally.cash.expense"].sudo().search_count([]), avant_depenses)
        self.assertEqual(len(self._collections(reference)), 1)

    # ─── Lecture et DTO ──────────────────────────────────────────────

    def test_le_contexte_annonce_le_beneficiaire_sans_le_proposer(self):
        reference = self._creer_dossier()
        contexte = self._service().payment_context(reference)
        self.assertEqual(contexte["intake_reference"], reference)
        self.assertEqual(contexte["customer_name"], "Aissatou Wave")
        self.assertEqual(contexte["payment_method"], "wave")
        self.assertEqual(contexte["beneficiary"], "Gilles")
        self.assertEqual(contexte["currencies"], ["XOF"])

    def test_le_dto_ne_porte_aucun_identifiant_odoo(self):
        reference = self._creer_dossier()
        self._service().record_wave_payment(reference, self._demande())
        rendu = json.dumps({
            "contexte": self._service().payment_context(reference),
            "liste": self._service().list_payments(reference),
        })
        for interdit in ("partner_id", "shipment_id", "invoice_id", "company_id",
                         "currency_id", "collection_id", "payment_id",
                         "account_payment", "journal_id", "user_id",
                         "external_payment_key", "error_message", "ops:",
                         "collected_by"):
            self.assertNotIn(interdit, rendu)

    def test_le_dto_dit_le_verdict_comptable_sans_le_message(self):
        reference = self._creer_dossier()
        resultat = self._service().record_wave_payment(reference, self._demande())
        self.assertIn(
            resultat["payment"]["accounting_status"],
            ("registered", "pending", "needs_review"))
        self.assertEqual(resultat["payment"]["beneficiary"], "Gilles")
        self.assertEqual(resultat["payment"]["payment_method"], "wave")

    def test_la_liste_totalise_par_devise_sans_convertir(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        self._service().record_wave_payment(
            reference, self._demande(amount=100000.0, wave_reference="TWA001"))
        # Une collecte historique en euros, venue du tableur.
        self.env["dally.freight.collection"].sudo().create({
            "external_payment_key": "sheet:eur-1", "shipment_id": shipment.id,
            "amount": 40.0, "currency_id": self.eur.id,
            "payment_date": "2026-08-27", "source_method": "cash",
        })
        resume = self._service().list_payments(reference)["summary"]
        self.assertEqual(resume, [
            {"currency_code": "EUR", "amount": 40.0},
            {"currency_code": "XOF", "amount": 100000.0},
        ])

    # ─── Contrôles de source ─────────────────────────────────────────

    def test_le_controleur_ne_contient_ni_sudo_ni_cle_d_api(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_wave_payments
        code = code_seul(ops_wave_payments)
        for interdit in ("sudo", "SUPERUSER_ID", "API_KEY", "api_key",
                         "with_user", "search(", "browse("):
            self.assertNotIn(interdit, code)
        self.assertIn("auth='user'", code)

    def test_aucun_identifiant_numerique_n_est_ecrit_en_dur(self):
        """Le bénéficiaire se résout par configuration, jamais par son `id`.

        Un `id` PostgreSQL ne survit pas à une restauration et ne veut rien
        dire dans une autre base : le figer rendrait un test vert pour de
        mauvaises raisons.
        """
        from odoo.addons.dally_ops_mobile.models import ops_wave_payment_service
        code = code_seul(ops_wave_payment_service)
        self.assertNotIn("dally_ops_cash_actor\", \"=\"", code)
        self.assertNotIn("'Gilles'", code)
        self.assertNotIn('"Gilles"', code)
        # La seule comparaison numérique admise est celle qui **refuse** le
        # superutilisateur.
        self.assertIn("SUPERUSER_ID", code)

    def test_le_service_n_invente_aucune_integration_wave(self):
        from odoo.addons.dally_ops_mobile.models import ops_wave_payment_service
        code = code_seul(ops_wave_payment_service)
        for interdit in ("requests", "urlopen", "http://", "https://", "webhook",
                         "otp", "pin", "token", "credential", "password"):
            self.assertNotIn(interdit, code.lower())


@tagged("post_install", "-at_install", "dally")
class TestOpsControllerHelpers(TransactionCase):
    """Les aides privées des contrôleurs Ops ne se marchent pas dessus.

    ## Ce qui a rendu ce test nécessaire

    Odoo fusionne les contrôleurs qui partagent une classe de base : deux
    méthodes homonymes sur `DallyOpsController` n'en font qu'une, et c'est la
    dernière chargée qui l'emporte — pour **tous** les contrôleurs.

    Mesuré : une méthode `_servir` ajoutée aux encaissements Wave avec une
    convention d'appel différente a rendu les routes des dépenses et des
    transferts inutilisables, en HTTP 500, alors que tous leurs tests de
    service restaient verts. Seuls leurs tests HTTP l'ont vu.

    Ce test refuse désormais la situation en amont : un nom partagé doit
    porter exactement le même code partout, ou ne pas être partagé.
    """

    def test_deux_controleurs_ne_definissent_pas_la_meme_aide_autrement(self):
        import os
        from odoo.addons.dally_ops_mobile import controllers as paquet

        dossier = os.path.dirname(inspect.getfile(paquet))
        definitions = {}
        divergences = []
        for nom_fichier in sorted(os.listdir(dossier)):
            if not nom_fichier.endswith(".py") or nom_fichier == "__init__.py":
                continue
            if nom_fichier == "ops_base.py":
                # La base a le droit de définir ce que les autres réutilisent.
                continue
            chemin = os.path.join(dossier, nom_fichier)
            with open(chemin, encoding="utf-8") as fichier:
                arbre = ast.parse(fichier.read())
            for classe in [n for n in arbre.body if isinstance(n, ast.ClassDef)]:
                for methode in classe.body:
                    if not isinstance(methode, ast.FunctionDef):
                        continue
                    if not methode.name.startswith("_"):
                        continue
                    # Le **code**, texte d'explication retiré : deux aides
                    # identiques dont l'une seule est documentée fusionnent
                    # sans dommage, et signaler cela noierait le vrai défaut.
                    sans_docstring = ast.FunctionDef(
                        name=methode.name, args=methode.args,
                        body=methode.body[1:] if (
                            methode.body
                            and isinstance(methode.body[0], ast.Expr)
                            and isinstance(methode.body[0].value, ast.Constant)
                            and isinstance(methode.body[0].value.value, str)
                        ) else methode.body,
                        decorator_list=[], returns=None, type_params=[])
                    if not sans_docstring.body:
                        sans_docstring.body = [ast.Pass()]
                    corps = ast.unparse(ast.fix_missing_locations(sans_docstring))
                    if methode.name in definitions:
                        autre_fichier, autre_corps = definitions[methode.name]
                        if autre_corps != corps:
                            divergences.append(
                                "%s : %s et %s" % (
                                    methode.name, autre_fichier, nom_fichier))
                    else:
                        definitions[methode.name] = (nom_fichier, corps)

        self.assertEqual(divergences, [], "\n".join(divergences))

    def test_l_aide_wave_porte_un_nom_qui_lui_est_propre(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_wave_payments
        code = code_seul(ops_wave_payments)
        self.assertIn("_servir_wave", code)


@tagged("post_install", "-at_install", "dally")
class TestOpsWavePaymentsHttp(HttpCase):
    """Les routes elles-mêmes, éprouvées par HTTP réel.

    C'est le seul niveau où se voit une collision de contrôleurs : un service
    appelé directement ne passe jamais par la classe fusionnée qu'Odoo
    construit.
    """

    MOT_DE_PASSE = "OpsProbe!2026#wave"

    def setUp(self):
        super().setUp()
        self.societe = self.env["res.company"].create({"name": "Ops Wave HTTP SA"})
        self.xof = self.env.ref("base.XOF")
        self.xof.write({"active": True})
        self.societe.sudo().write({"dally_ops_wave_beneficiary": "Gilles"})

        self.gilles = self.env["res.users"].create({
            "name": "Gilles HTTP Wave", "login": "http.wave.gilles",
            "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref(
                "dally_ops_mobile.group_dally_ops_logistician").id])],
            "company_id": self.societe.id,
            "company_ids": [(6, 0, [self.societe.id])],
            "dally_ops_cash_actor": "Gilles",
        })
        self.etranger = self.env["res.users"].create({
            "name": "Sans rôle", "login": "http.wave.autre",
            "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            "company_id": self.societe.id,
            "company_ids": [(6, 0, [self.societe.id])],
        })

    def _lire(self, chemin, login):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(chemin, allow_redirects=False)

    def _poster(self, chemin, corps, login):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(
            chemin, data=json.dumps(corps),
            headers={"Content-Type": "application/json"}, allow_redirects=False)

    def test_un_dossier_inconnu_rend_404_et_non_500(self):
        """La route répond, et répond correctement.

        Un 500 ici signalerait que la classe de contrôleur fusionnée par Odoo
        appelle la mauvaise implémentation — exactement le défaut que ce
        fichier existe pour empêcher de revenir.
        """
        reponse = self._lire(
            "/api/v1/ops/shipments/AIR-INCONNU-A001/wave-context",
            "http.wave.gilles")
        self.assertEqual(reponse.status_code, 404, reponse.content[:400])
        self.assertEqual(
            json.loads(reponse.content)["error"]["code"], "intake_not_found")

    def test_les_trois_routes_wave_repondent(self):
        for chemin, methode in (
            ("/api/v1/ops/shipments/AIR-INCONNU-A001/wave-context", "GET"),
            ("/api/v1/ops/shipments/AIR-INCONNU-A001/payments", "GET"),
            ("/api/v1/ops/shipments/AIR-INCONNU-A001/payments", "POST"),
        ):
            reponse = (self._lire(chemin, "http.wave.gilles") if methode == "GET"
                       else self._poster(chemin, {}, "http.wave.gilles"))
            self.assertNotEqual(reponse.status_code, 500, chemin)
            self.assertIn(reponse.status_code, (400, 404))

    def test_les_routes_voisines_repondent_toujours(self):
        """Les dépenses et les transferts, contrôlés depuis ce fichier.

        Leur régression n'était visible qu'en HTTP, et elle venait d'ici.
        """
        for chemin in ("/api/v1/ops/expense-consolidations",
                       "/api/v1/ops/cash-transfer-options",
                       "/api/v1/ops/payment-channels"):
            reponse = self._lire(chemin, "http.wave.gilles")
            self.assertNotEqual(reponse.status_code, 500, chemin)

    def test_un_authentifie_sans_role_ops_est_refuse(self):
        self.assertEqual(
            self._lire("/api/v1/ops/shipments/AIR-X-A001/wave-context",
                       "http.wave.autre").status_code, 403)

    def test_un_anonyme_est_renvoye_vers_la_connexion(self):
        self.assertIn(
            self._lire("/api/v1/ops/shipments/AIR-X-A001/payments", None).status_code,
            (302, 303))
