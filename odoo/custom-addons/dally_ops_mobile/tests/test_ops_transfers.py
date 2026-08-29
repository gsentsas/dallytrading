# -*- coding: utf-8 -*-
"""Remettre de la caisse, et prouver qu'elle est arrivée.

## La propriété que ces tests protègent

Une remise n'est pas une réception. Celui qui donne ne peut pas attester que
l'argent est arrivé — seul celui qui reçoit le peut. Presque tous les tests
ci-dessous tournent autour de cette asymétrie : l'expéditeur est refusé, le
responsable qui n'est pas destinataire est refusé, et rien à la création ne
fait basculer un transfert en « reçu ».

## La seconde propriété

Un nom d'acteur de caisse est du texte libre dans le modèle partagé. Rien ne
garantit qu'il désigne une seule personne. Les tests d'acteurs vérifient donc
que le serveur refuse de deviner : un acteur porté par deux comptes actifs
disparaît de la liste, et bloque l'opération s'il s'agit du vôtre.
"""

import ast
import inspect
import json
import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.dally_ops_mobile.models.ops_errors import (
    DallyOpsConflict,
    DallyOpsError,
    DallyOpsNotFound,
)
from odoo.addons.dally_ops_mobile.tests.common import (
    MODELES_METIER_FERMES,
    MODELES_TECHNIQUES_LISIBLES,
    modeles_lisibles,
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


class SocleTransferts(TransactionCase):
    """Les comptes et la société que tous ces tests partagent."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Une société dédiée : la base du banc porte des acteurs venus des
        # étapes précédentes, et une énumération globale les ramasserait.
        cls.societe = cls.env["res.company"].create({"name": "Ops Transferts SA"})
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Transferts Autre"})

        cls.eur = cls.env.ref("base.EUR")
        cls.xof = cls.env.ref("base.XOF")
        cls.usd = cls.env.ref("base.USD")
        (cls.eur | cls.xof | cls.usd).write({"active": True})

        cls.gilles = cls._compte(
            "trf.gilles", "Gilles Terrain",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Gilles")
        cls.dalanda = cls._compte(
            "trf.dalanda", "Dalanda Terrain",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Dalanda")
        # Responsable : il implique le logisticien sans porter le groupe
        # directement. S'il n'apparaissait pas comme destinataire, la moitié de
        # l'équipe serait injoignable.
        cls.alain = cls._compte(
            "trf.alain", "Alain Responsable",
            "dally_ops_mobile.group_dally_ops_supervisor", acteur="Alain")
        cls.sans_acteur = cls._compte(
            "trf.sansacteur", "Sans acteur",
            "dally_ops_mobile.group_dally_ops_logistician", acteur=False)
        cls.non_ops = cls._compte("trf.autre", "Sans rôle", "base.group_user")

    @classmethod
    def _compte(cls, login, nom, groupe, acteur=None, actif=True, societe=None):
        valeurs = {
            "name": nom, "login": login, "active": actif,
            "group_ids": [(6, 0, [cls.env.ref(groupe).id])],
            "company_id": (societe or cls.societe).id,
            "company_ids": [(6, 0, [(societe or cls.societe).id])],
        }
        if acteur:
            valeurs["dally_ops_cash_actor"] = acteur
        return cls.env["res.users"].create(valeurs)

    def _acteurs(self, utilisateur=None):
        return (self.env["dally.ops.cash.actor.service"]
                .with_user(utilisateur or self.gilles)
                .with_company(self.societe))

    def _service(self, utilisateur=None):
        return (self.env["dally.ops.cash.transfer.service"]
                .with_user(utilisateur or self.gilles)
                .with_company(self.societe))

    def _charge(self, **changements):
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "to_actor": "Dalanda",
            "transfer_date": "2026-08-28",
            "amount": 100000.0,
            "currency_code": "XOF",
            "payment_method": "cash",
            "reason": "Remise caisse du soir",
            "comment": "",
        }
        charge.update(changements)
        return charge

    def _transfert(self, reference):
        return self.env["dally.cash.transfer"].sudo().search([
            ("external_transfer_key", "=", "ops:%s" % reference),
            ("company_id", "=", self.societe.id),
        ], limit=1)

    def _remettre(self, **changements):
        """Une remise de Gilles à Dalanda, et sa référence publique."""
        return self._service().record_transfer(
            self._charge(**changements))["transfer"]["reference"]

    def _audit(self, action):
        return self.env["dally.ops.audit.event"].sudo().search([
            ("company_id", "=", self.societe.id), ("action", "=", action),
        ])


# ══════════════════════════════════════════════════════════════════════
#  Les acteurs de caisse
# ══════════════════════════════════════════════════════════════════════

@tagged("post_install", "-at_install", "dally")
class TestOpsCashActors(SocleTransferts):

    def test_l_acteur_courant_vient_du_serveur(self):
        self.assertEqual(self._acteurs(self.gilles).current_actor(), "Gilles")
        self.assertEqual(self._acteurs(self.dalanda).current_actor(), "Dalanda")

    def test_sans_correspondance_l_operation_est_refusee(self):
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._acteurs(self.sans_acteur).current_actor()
        self.assertEqual(erreur.exception.code, "cash_actor_not_configured")

    def test_le_nom_odoo_ne_devient_jamais_l_acteur(self):
        # « Sans acteur » a un `display_name` parfaitement lisible ; il ne doit
        # pas servir de repli, sous peine d'imputations fausses et silencieuses.
        with self.assertRaises(DallyOpsConflict):
            self._acteurs(self.sans_acteur).current_actor()
        self.assertNotIn(
            self.sans_acteur.display_name,
            self._acteurs(self.gilles).available_recipients())

    def test_renommer_un_compte_ne_change_pas_son_acteur(self):
        self.dalanda.sudo().write({"name": "Dalanda Épouse Sow"})
        self.assertEqual(self._acteurs(self.dalanda).current_actor(), "Dalanda")
        self.assertIn("Dalanda", self._acteurs(self.gilles).available_recipients())

    def test_les_destinataires_sont_les_comptes_ops_actifs_configures(self):
        # Un responsable est destinataire : il implique le logisticien.
        self.assertEqual(
            self._acteurs(self.gilles).available_recipients(), ["Alain", "Dalanda"])

    def test_l_acteur_courant_est_exclu_de_ses_propres_destinataires(self):
        self.assertNotIn("Gilles", self._acteurs(self.gilles).available_recipients())
        self.assertNotIn("Dalanda", self._acteurs(self.dalanda).available_recipients())

    def test_un_compte_sans_role_ops_n_est_pas_destinataire(self):
        self._compte("trf.horsops", "Hors Ops", "base.group_user", acteur="Fatou")
        self.assertNotIn("Fatou", self._acteurs(self.gilles).available_recipients())

    def test_un_compte_desactive_n_est_pas_destinataire(self):
        self.dalanda.sudo().write({"active": False})
        self.assertNotIn("Dalanda", self._acteurs(self.gilles).available_recipients())

    def test_un_compte_sans_correspondance_n_est_pas_destinataire(self):
        self.assertNotIn("", self._acteurs(self.gilles).available_recipients())
        self.assertEqual(
            len(self._acteurs(self.gilles).available_recipients()), 2)

    def test_un_compte_d_une_autre_societe_n_est_pas_destinataire(self):
        self._compte("trf.ailleurs", "Ailleurs", 
                     "dally_ops_mobile.group_dally_ops_logistician",
                     acteur="Ailleurs", societe=self.autre_societe)
        self.assertNotIn("Ailleurs", self._acteurs(self.gilles).available_recipients())

    # ─── L'ambiguïté ─────────────────────────────────────────────────

    def test_un_acteur_porte_par_deux_comptes_disparait_de_la_liste(self):
        self._compte("trf.dalanda2", "Dalanda Bis",
                     "dally_ops_mobile.group_dally_ops_logistician", acteur="dalanda")
        # « Dalanda » et « dalanda » désignent la même personne : le serveur ne
        # choisit pas lequel des deux comptes la représente.
        self.assertNotIn("Dalanda", self._acteurs(self.gilles).available_recipients())
        self.assertEqual(self._acteurs(self.gilles).available_recipients(), ["Alain"])

    def test_un_acteur_courant_ambigu_bloque_l_operation(self):
        self._compte("trf.gilles2", "Gilles Bis",
                     "dally_ops_mobile.group_dally_ops_logistician", acteur="  GILLES  ")
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._acteurs(self.gilles).current_actor()
        self.assertEqual(erreur.exception.code, "cash_actor_configuration_conflict")

    def test_un_doublon_desactive_ne_rend_plus_ambigu(self):
        bis = self._compte("trf.dalanda3", "Dalanda Ter",
                           "dally_ops_mobile.group_dally_ops_logistician", acteur="Dalanda")
        self.assertNotIn("Dalanda", self._acteurs(self.gilles).available_recipients())
        bis.sudo().write({"active": False})
        self.assertIn("Dalanda", self._acteurs(self.gilles).available_recipients())

    def test_la_resolution_est_exacte_jamais_approchante(self):
        acteurs = self._acteurs(self.gilles)
        self.assertEqual(acteurs.resolve_recipient("Dalanda"), "Dalanda")
        # La casse et les espaces ne changent pas l'identité…
        self.assertEqual(acteurs.resolve_recipient("  dalanda "), "Dalanda")
        # …mais rien d'approchant n'est accepté.
        for valeur in ("Dal", "Dalandaa", "Dalanda Ba", "%", "_", "", None, 7):
            with self.assertRaises(DallyOpsError) as erreur:
                acteurs.resolve_recipient(valeur)
            self.assertEqual(erreur.exception.code, "cash_recipient_not_available")

    def test_le_dto_des_destinataires_ne_porte_que_le_nom(self):
        options = self._service(self.gilles).list_options()
        for destinataire in options["recipients"]:
            self.assertEqual(list(destinataire), ["actor"])
        rendu = json.dumps(options)
        for interdit in ("user_id", "login", "email", "phone", "group",
                         "company_id", "partner_id", "trf.dalanda"):
            self.assertNotIn(interdit, rendu)


# ══════════════════════════════════════════════════════════════════════
#  Les options
# ══════════════════════════════════════════════════════════════════════

@tagged("post_install", "-at_install", "dally")
class TestOpsCashTransferOptions(SocleTransferts):

    def test_un_compte_sans_role_ops_ne_voit_rien(self):
        with self.assertRaises(AccessError):
            self._service(self.non_ops).list_options()

    def test_les_options_annoncent_l_expediteur_et_ses_destinataires(self):
        options = self._service(self.gilles).list_options()
        self.assertEqual(options["from_actor"], "Gilles")
        self.assertEqual(
            [d["actor"] for d in options["recipients"]], ["Alain", "Dalanda"])

    def test_les_devises_offertes_sont_celles_de_la_caisse(self):
        codes = [d["code"] for d in self._service().list_options()["currencies"]]
        # Mesuré sur la base de production : les mouvements de caisse sont en
        # francs, l'euro sert déjà aux dépenses, le dollar n'a jamais rien porté.
        self.assertEqual(codes, ["XOF", "EUR"])
        self.assertNotIn("USD", codes)

    def test_une_devise_desactivee_n_est_pas_proposee(self):
        self.eur.sudo().write({"active": False})
        codes = [d["code"] for d in self._service().list_options()["currencies"]]
        self.assertEqual(codes, ["XOF"])

    def test_les_modes_sont_ceux_des_depenses(self):
        from odoo.addons.dally_ops_mobile.models import ops_cash_vocabulary
        codes = [m["code"] for m in self._service().list_options()["payment_methods"]]
        self.assertEqual(codes, list(ops_cash_vocabulary.MODES_PAIEMENT))
        self.assertEqual(codes, ["cash", "wave", "bank", "other"])

    def test_le_vocabulaire_est_partage_avec_les_depenses(self):
        # Deux listes finiraient par diverger : un écran offrirait un mode que
        # l'autre refuserait, et c'est l'opérateur qui le découvrirait.
        from odoo.addons.dally_ops_mobile.models import (
            ops_cash_vocabulary, ops_expense_service, ops_transfer_service)
        self.assertIs(ops_expense_service.MODES_PAIEMENT,
                      ops_cash_vocabulary.MODES_PAIEMENT)
        self.assertIs(ops_transfer_service.MODES_PAIEMENT,
                      ops_cash_vocabulary.MODES_PAIEMENT)


# ══════════════════════════════════════════════════════════════════════
#  La remise
# ══════════════════════════════════════════════════════════════════════

@tagged("post_install", "-at_install", "dally")
class TestOpsCashTransferCreate(SocleTransferts):

    def test_un_compte_sans_role_ops_ne_peut_rien_faire(self):
        for appel in (
            lambda: self._service(self.non_ops).record_transfer(self._charge()),
            lambda: self._service(self.non_ops).list_transfers(),
            lambda: self._service(self.non_ops).acknowledge(
                str(uuid.uuid4()), str(uuid.uuid4())),
        ):
            with self.assertRaises(AccessError):
                appel()

    def test_une_remise_est_ecrite_telle_que_le_serveur_la_decide(self):
        charge = self._charge()
        resultat = self._service().record_transfer(charge)
        self.assertEqual(resultat["status"], "created")

        transfert = self._transfert(charge["request_uuid"])
        self.assertTrue(transfert)
        self.assertEqual(transfert.from_actor, "Gilles")
        self.assertEqual(transfert.to_actor, "Dalanda")
        self.assertEqual(transfert.amount, 100000.0)
        self.assertEqual(transfert.currency_id, self.xof)
        self.assertEqual(transfert.payment_method, "cash")
        self.assertEqual(transfert.reason, "Remise caisse du soir")
        self.assertEqual(transfert.source, "backoffice")
        self.assertEqual(transfert.company_id, self.societe)

    def test_la_remise_naît_en_attente_de_reception(self):
        """Le cœur de l'étape : créer ne vaut jamais recevoir."""
        charge = self._charge()
        dto = self._service().record_transfer(charge)
        transfert = self._transfert(charge["request_uuid"])
        # Les deux acteurs sont configurés, et pourtant rien n'est validé.
        self.assertEqual(transfert.state, "review")
        self.assertFalse(transfert.acknowledged_at)
        self.assertFalse(transfert.acknowledged_by_user_id)
        self.assertEqual(dto["transfer"]["state"], "pending_receipt")
        self.assertIsNone(dto["transfer"]["acknowledged_at"])

    def test_le_dto_ne_parle_pas_le_vocabulaire_historique(self):
        dto = self._service().record_transfer(self._charge())
        rendu = json.dumps(dto)
        # L'interface n'a pas à savoir qu'une remise « à revoir » attend en
        # réalité son destinataire.
        self.assertNotIn("review", rendu)
        self.assertNotIn("validated", rendu)

    def test_l_expediteur_vient_du_compte_jamais_du_navigateur(self):
        for champ in ("from_actor", "sender", "actor", "actor_name"):
            with self.assertRaises(DallyOpsError):
                self._service().record_transfer(self._charge(**{champ: "Alain"}))

    def test_un_champ_decide_par_le_serveur_est_refuse(self):
        for champ, valeur in (
            ("state", "validated"),
            ("source", "google_sheets"),
            ("external_transfer_key", "TRF-1"),
            ("company_id", 1),
            ("total_eur_snapshot", 10),
            ("total_xof_snapshot", 10),
            ("acknowledged_at", "2026-08-28 10:00:00"),
            ("acknowledged_by_user_id", 1),
            ("user_id", 1),
            ("recipient_user_id", 1),
        ):
            with self.assertRaises(DallyOpsError):
                self._service().record_transfer(self._charge(**{champ: valeur}))

    def test_un_champ_obligatoire_manquant_est_refuse(self):
        for champ in ("to_actor", "transfer_date", "amount", "currency_code",
                      "payment_method", "reason", "comment"):
            charge = self._charge()
            charge.pop(champ)
            with self.assertRaises(DallyOpsError):
                self._service().record_transfer(charge)

    def test_le_destinataire_est_controle(self):
        for valeur in ("Fatou", "Dal", "Gilles Bis", "%", ""):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_transfer(self._charge(to_actor=valeur))
            self.assertEqual(erreur.exception.code, "cash_recipient_not_available")

    def test_on_ne_se_remet_pas_de_la_caisse_a_soi_meme(self):
        for valeur in ("Gilles", "gilles", "  Gilles  ", "GILLES"):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_transfer(self._charge(to_actor=valeur))
            self.assertEqual(erreur.exception.code, "same_actor")

    def test_un_montant_nul_ou_negatif_est_refuse(self):
        for montant in (0, -1, 0.0, -100000.0, True, "100000", None):
            with self.assertRaises(DallyOpsError):
                self._service().record_transfer(self._charge(amount=montant))

    def test_une_date_illisible_ou_future_est_refusee(self):
        for valeur in ("", "28/08/2026", "2026-13-01", "demain", None, 20260828,
                       "2099-01-01"):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_transfer(self._charge(transfer_date=valeur))
            self.assertEqual(erreur.exception.code, "invalid_transfer_date")

    def test_seules_les_devises_de_caisse_sont_acceptees(self):
        self.assertTrue(self._service().record_transfer(self._charge(currency_code="EUR")))
        for code in ("USD", "GBP", "ZZZ", "xof"):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_transfer(self._charge(currency_code=code))
            self.assertEqual(erreur.exception.code, "currency_not_available")

    def test_seuls_quatre_modes_sont_acceptes(self):
        for mode in ("cash", "wave", "bank", "other"):
            resultat = self._service().record_transfer(self._charge(payment_method=mode))
            self.assertEqual(resultat["transfer"]["payment_method"], mode)
        for mode in ("orange_money", "cheque", "", None, "CASH", 12):
            with self.assertRaises(DallyOpsError) as erreur:
                self._service().record_transfer(self._charge(payment_method=mode))
            self.assertEqual(erreur.exception.code, "payment_method_not_allowed")

    def test_les_instantanes_de_conversion_restent_vides(self):
        charge = self._charge()
        self._service().record_transfer(charge)
        transfert = self._transfert(charge["request_uuid"])
        self.assertEqual(transfert.total_eur_snapshot, 0.0)
        self.assertEqual(transfert.total_xof_snapshot, 0.0)

    def test_un_acteur_courant_ambigu_bloque_la_remise(self):
        self._compte("trf.gilles9", "Gilles Bis",
                     "dally_ops_mobile.group_dally_ops_logistician", acteur="gilles")
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service().record_transfer(self._charge())
        self.assertEqual(erreur.exception.code, "cash_actor_configuration_conflict")

    def test_sans_correspondance_de_caisse_la_remise_est_refusee(self):
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service(self.sans_acteur).record_transfer(
                self._charge(to_actor="Dalanda"))
        self.assertEqual(erreur.exception.code, "cash_actor_not_configured")

    # ─── L'idempotence ───────────────────────────────────────────────

    def test_une_demande_rejouee_ne_cree_qu_une_remise(self):
        charge = self._charge()
        premier = self._service().record_transfer(charge)
        second = self._service().record_transfer(dict(charge))
        self.assertEqual(premier["status"], "created")
        self.assertEqual(second["status"], "replayed")
        self.assertEqual(premier["transfer"]["reference"],
                         second["transfer"]["reference"])
        self.assertEqual(
            self.env["dally.cash.transfer"].sudo().search_count([
                ("external_transfer_key", "=", "ops:%s" % charge["request_uuid"]),
            ]), 1)

    def test_le_rejeu_ne_produit_pas_un_second_audit_de_remise(self):
        charge = self._charge()
        self._service().record_transfer(charge)
        self._service().record_transfer(dict(charge))
        self.assertEqual(len(self._audit("cash_transfer_recorded")), 1)
        self.assertEqual(len(self._audit("cash_transfer_create_replayed")), 1)

    def test_le_meme_identifiant_avec_un_autre_montant_est_un_conflit(self):
        charge = self._charge()
        self._service().record_transfer(charge)
        for changement in ({"amount": 50000.0}, {"to_actor": "Alain"},
                           {"reason": "Autre motif"}, {"payment_method": "wave"},
                           {"currency_code": "EUR"}, {"transfer_date": "2026-08-27"}):
            with self.assertRaises(DallyOpsConflict) as erreur:
                self._service().record_transfer(dict(charge, **changement))
            self.assertEqual(erreur.exception.code, "idempotency_conflict")

    def test_un_identifiant_de_demande_invalide_est_refuse(self):
        for valeur in ("", "pas-un-uuid", None, 42):
            with self.assertRaises(DallyOpsError):
                self._service().record_transfer(self._charge(request_uuid=valeur))

    def test_l_audit_nomme_l_operateur_reel(self):
        charge = self._charge()
        self._service().record_transfer(charge)
        evenement = self._audit("cash_transfer_recorded")
        self.assertEqual(len(evenement), 1)
        self.assertEqual(evenement.operator_user_id, self.gilles)
        self.assertEqual(evenement.entity_model, "dally.cash.transfer")
        self.assertEqual(evenement.request_uuid, charge["request_uuid"])

    def test_l_audit_ne_recopie_pas_le_montant(self):
        self._service().record_transfer(self._charge(amount=777777.0))
        evenement = self._audit("cash_transfer_recorded")
        rendu = json.dumps({
            champ: evenement.read([champ])[0][champ]
            for champ in ("action", "entity_model", "entity_res_id", "request_uuid")
        })
        self.assertNotIn("777777", rendu)
        self.assertNotIn("Dalanda", rendu)


# ══════════════════════════════════════════════════════════════════════
#  La liste
# ══════════════════════════════════════════════════════════════════════

@tagged("post_install", "-at_install", "dally")
class TestOpsCashTransferList(SocleTransferts):

    def test_chacun_ne_voit_que_ce_qui_le_concerne(self):
        self._remettre()                       # Gilles → Dalanda
        self._remettre(to_actor="Alain")       # Gilles → Alain
        self._service(self.dalanda).record_transfer(
            self._charge(to_actor="Alain"))    # Dalanda → Alain

        gilles = self._service(self.gilles).list_transfers()
        dalanda = self._service(self.dalanda).list_transfers()
        alain = self._service(self.alain).list_transfers()

        self.assertEqual(len(gilles["transfers"]), 2)
        self.assertEqual(len(dalanda["transfers"]), 2)
        self.assertEqual(len(alain["transfers"]), 2)
        self.assertEqual(gilles["actor"], "Gilles")

    def test_le_sens_est_donne_du_point_de_vue_de_celui_qui_regarde(self):
        self._remettre()
        gilles = self._service(self.gilles).list_transfers()["transfers"][0]
        dalanda = self._service(self.dalanda).list_transfers()["transfers"][0]
        self.assertEqual(gilles["direction"], "outgoing")
        self.assertEqual(dalanda["direction"], "incoming")
        self.assertEqual(gilles["reference"], dalanda["reference"])

    def test_le_totalise_par_devise_et_par_sens_sans_convertir(self):
        self._remettre(amount=100000.0, currency_code="XOF")
        self._remettre(amount=50000.0, currency_code="XOF")
        self._remettre(amount=40.0, currency_code="EUR")
        self._service(self.dalanda).record_transfer(
            self._charge(to_actor="Gilles", amount=25000.0, currency_code="XOF"))

        resume = self._service(self.gilles).list_transfers()["summary"]
        self.assertEqual(resume, [
            {"direction": "incoming", "currency_code": "XOF", "amount": 25000.0},
            {"direction": "outgoing", "currency_code": "EUR", "amount": 40.0},
            {"direction": "outgoing", "currency_code": "XOF", "amount": 150000.0},
        ])

    def test_un_tiers_ne_voit_pas_la_remise(self):
        self._remettre()  # Gilles → Dalanda
        self.assertEqual(
            len(self._service(self.alain).list_transfers()["transfers"]), 0)

    def test_la_liste_ne_porte_aucun_identifiant_odoo(self):
        self._remettre()
        rendu = json.dumps(self._service(self.gilles).list_transfers())
        for interdit in ("transfer_id", "company_id", "currency_id", "user_id",
                         "acknowledged_by", "external_transfer_key", "ops:",
                         "trf.gilles", "partner_id"):
            self.assertNotIn(interdit, rendu)

    def test_la_liste_ignore_les_remises_d_une_autre_societe(self):
        self._remettre()
        autre = self.env["dally.cash.transfer"].sudo().with_company(
            self.autre_societe).create({
                "company_id": self.autre_societe.id,
                "external_transfer_key": "ops:%s" % uuid.uuid4(),
                "transfer_date": "2026-08-28", "from_actor": "Gilles",
                "to_actor": "Dalanda", "amount": 1.0, "currency_id": self.xof.id,
            })
        self.assertTrue(autre)
        self.assertEqual(
            len(self._service(self.gilles).list_transfers()["transfers"]), 1)

    def test_la_liste_s_en_tient_aux_remises_nees_dans_dally_ops(self):
        """Une ligne du tableur n'a pas de référence sûre à exposer.

        `TRF-20260822-0001` est un numéro de document, pas une identité
        opaque : le servir laisserait deviner un volume et proposerait une
        référence que l'accusé de réception refuserait ensuite de résoudre.
        L'écran le dit plutôt que de laisser croire à un journal complet.
        """
        self._remettre()
        self.env["dally.cash.transfer"].sudo().with_company(self.societe).create({
            "company_id": self.societe.id,
            "external_transfer_key": "TRF-20260822-0001",
            "transfer_date": "2026-08-22", "from_actor": "Alain",
            "to_actor": "Gilles", "amount": 100000.0, "currency_id": self.xof.id,
            "source": "google_sheets",
        })
        liste = self._service(self.gilles).list_transfers()
        self.assertEqual(len(liste["transfers"]), 1)
        self.assertNotIn("TRF-", json.dumps(liste))


# ══════════════════════════════════════════════════════════════════════
#  L'accusé de réception
# ══════════════════════════════════════════════════════════════════════

@tagged("post_install", "-at_install", "dally")
class TestOpsCashTransferAcknowledge(SocleTransferts):

    def test_le_destinataire_confirme_et_lui_seul(self):
        reference = self._remettre()
        resultat = self._service(self.dalanda).acknowledge(reference, str(uuid.uuid4()))
        self.assertEqual(resultat["status"], "acknowledged")
        self.assertEqual(resultat["transfer"]["state"], "received")

        transfert = self._transfert(reference)
        self.assertEqual(transfert.state, "validated")
        self.assertTrue(transfert.acknowledged_at)
        self.assertEqual(transfert.acknowledged_by_user_id, self.dalanda)

    def test_l_expediteur_ne_peut_pas_confirmer_a_la_place_du_destinataire(self):
        """La règle qui donne son sens à toute l'étape."""
        reference = self._remettre()
        with self.assertRaises(DallyOpsError) as erreur:
            self._service(self.gilles).acknowledge(reference, str(uuid.uuid4()))
        self.assertEqual(erreur.exception.code, "not_transfer_recipient")
        self.assertEqual(erreur.exception.status, 403)
        self.assertEqual(self._transfert(reference).state, "review")

    def test_un_tiers_ne_peut_pas_confirmer(self):
        reference = self._remettre()
        with self.assertRaises(DallyOpsError) as erreur:
            self._service(self.alain).acknowledge(reference, str(uuid.uuid4()))
        self.assertEqual(erreur.exception.code, "not_transfer_recipient")

    def test_un_responsable_non_destinataire_ne_peut_pas_confirmer(self):
        """Le grade ne remplace pas la présence.

        Un responsable corrigera un jour une remise, par un écran assumé et
        tracé. Lui laisser confirmer une réception ici transformerait la preuve
        en formalité.
        """
        reference = self._service(self.dalanda).record_transfer(
            self._charge(to_actor="Gilles"))["transfer"]["reference"]
        with self.assertRaises(DallyOpsError) as erreur:
            self._service(self.alain).acknowledge(reference, str(uuid.uuid4()))
        self.assertEqual(erreur.exception.code, "not_transfer_recipient")
        self.assertEqual(self._transfert(reference).state, "review")

    def test_la_confirmation_ne_touche_a_rien_d_autre(self):
        reference = self._remettre()
        avant = self._transfert(reference)
        photo = (avant.amount, avant.currency_id, avant.from_actor,
                 avant.to_actor, avant.transfer_date, avant.reason,
                 avant.payment_method)
        self._service(self.dalanda).acknowledge(reference, str(uuid.uuid4()))
        apres = self._transfert(reference)
        self.assertEqual(
            (apres.amount, apres.currency_id, apres.from_actor, apres.to_actor,
             apres.transfer_date, apres.reason, apres.payment_method), photo)

    def test_une_remise_inconnue_est_introuvable(self):
        with self.assertRaises(DallyOpsNotFound) as erreur:
            self._service(self.dalanda).acknowledge(str(uuid.uuid4()), str(uuid.uuid4()))
        self.assertEqual(erreur.exception.code, "transfer_not_found")

    def test_une_reference_de_tableur_ne_se_resout_pas(self):
        self.env["dally.cash.transfer"].sudo().with_company(self.societe).create({
            "company_id": self.societe.id,
            "external_transfer_key": "TRF-20260822-0001",
            "transfer_date": "2026-08-22", "from_actor": "Gilles",
            "to_actor": "Dalanda", "amount": 1000.0, "currency_id": self.xof.id,
            "source": "google_sheets",
        })
        with self.assertRaises(DallyOpsNotFound):
            self._service(self.dalanda).acknowledge(
                "TRF-20260822-0001", str(uuid.uuid4()))

    def test_une_remise_annulee_ne_se_confirme_pas(self):
        reference = self._remettre()
        self._transfert(reference).sudo().write({"state": "cancelled"})
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service(self.dalanda).acknowledge(reference, str(uuid.uuid4()))
        self.assertEqual(erreur.exception.code, "transfer_cancelled")

    def test_une_seconde_confirmation_distincte_est_un_conflit(self):
        reference = self._remettre()
        self._service(self.dalanda).acknowledge(reference, str(uuid.uuid4()))
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service(self.dalanda).acknowledge(reference, str(uuid.uuid4()))
        self.assertEqual(erreur.exception.code, "transfer_already_received")

    # ─── Le rejeu ────────────────────────────────────────────────────

    def test_le_rejeu_est_examine_avant_l_etat(self):
        """Le scénario qui impose l'ordre.

        Dalanda confirme, le serveur écrit, la réponse se perd, le téléphone
        renvoie la même demande. Si l'état était vérifié d'abord, cette
        seconde tentative verrait « déjà reçu » et répondrait un conflit — pour
        une confirmation qui a parfaitement réussi.
        """
        reference = self._remettre()
        demande = str(uuid.uuid4())
        premier = self._service(self.dalanda).acknowledge(reference, demande)
        second = self._service(self.dalanda).acknowledge(reference, demande)
        self.assertEqual(premier["status"], "acknowledged")
        self.assertEqual(second["status"], "replayed")
        self.assertEqual(second["transfer"]["state"], "received")
        self.assertIsNotNone(second["transfer"]["acknowledged_at"])

    def test_le_rejeu_ne_produit_pas_un_second_audit_de_reception(self):
        reference = self._remettre()
        demande = str(uuid.uuid4())
        self._service(self.dalanda).acknowledge(reference, demande)
        self._service(self.dalanda).acknowledge(reference, demande)
        self.assertEqual(len(self._audit("cash_transfer_received")), 1)
        self.assertEqual(len(self._audit("cash_transfer_receive_replayed")), 1)

    def test_le_meme_identifiant_sur_une_autre_remise_est_un_conflit(self):
        premiere = self._remettre()
        seconde = self._remettre()
        demande = str(uuid.uuid4())
        self._service(self.dalanda).acknowledge(premiere, demande)
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service(self.dalanda).acknowledge(seconde, demande)
        self.assertEqual(erreur.exception.code, "idempotency_conflict")
        self.assertEqual(self._transfert(seconde).state, "review")

    def test_deux_confirmations_successives_ne_valident_qu_une_fois(self):
        """La sérialisation, faute de vraie concurrence sur ce banc.

        Le serveur de test d'Odoo partage un curseur unique entre les
        requêtes : deux appels HTTP simultanés y sont exécutés l'un après
        l'autre, et le verrou consultatif ne peut donc pas être mis à
        l'épreuve ici. Ce test vérifie ce qui reste vérifiable — l'invariant
        que le verrou protège : une seule transition, un seul audit. Le verrou
        lui-même est vérifié par lecture du code, ci-dessous.
        """
        reference = self._remettre()
        self._service(self.dalanda).acknowledge(reference, str(uuid.uuid4()))
        with self.assertRaises(DallyOpsConflict):
            self._service(self.dalanda).acknowledge(reference, str(uuid.uuid4()))
        self.assertEqual(len(self._audit("cash_transfer_received")), 1)
        self.assertEqual(self._transfert(reference).state, "validated")

    def test_la_confirmation_prend_un_verrou_sur_la_remise(self):
        from odoo.addons.dally_ops_mobile.models import ops_transfer_service
        code = code_seul(ops_transfer_service)
        # Deux verrous : celui de la demande, puis celui du transfert. Sans le
        # second, deux confirmations portant des identifiants différents se
        # croiseraient.
        self.assertIn("ops-cash-transfer-ack:%s", code)
        self.assertIn("ops-cash-transfer:%s:%s", code)

    def test_un_identifiant_de_confirmation_invalide_est_refuse(self):
        reference = self._remettre()
        for valeur in ("", "pas-un-uuid", None, 42):
            with self.assertRaises(DallyOpsError):
                self._service(self.dalanda).acknowledge(reference, valeur)


# ══════════════════════════════════════════════════════════════════════
#  Le flux historique, et l'invariant
# ══════════════════════════════════════════════════════════════════════

@tagged("post_install", "-at_install", "dally")
class TestOpsCashTransferHistorique(SocleTransferts):

    def test_un_transfert_de_tableur_continue_de_fonctionner(self):
        """Les champs d'accusé restent facultatifs.

        Le flux du tableur n'a jamais eu d'accusé et n'en aura pas
        rétroactivement. Les rendre obligatoires refuserait des lignes qui
        existent déjà et sont exactes.
        """
        transfert, cree = (self.env["dally.cash.transfer"].sudo()
                           .with_company(self.societe)
                           .upsert_from_sync({
                               "external_transfer_key": "TRF-20260822-0001",
                               "transfer_date": "2026-08-22",
                               "from_actor": "Alain", "to_actor": "Gilles",
                               "amount": 100000.0, "currency_id": self.xof.id,
                               "source": "google_sheets", "state": "validated",
                           }))
        self.assertTrue(cree)
        self.assertEqual(transfert.state, "validated")
        self.assertFalse(transfert.acknowledged_at)
        self.assertFalse(transfert.acknowledged_by_user_id)

        # Et il se met encore à jour, comme le connecteur le fait.
        encore, recree = (self.env["dally.cash.transfer"].sudo()
                          .with_company(self.societe)
                          .upsert_from_sync({
                              "external_transfer_key": "TRF-20260822-0001",
                              "transfer_date": "2026-08-22",
                              "from_actor": "Alain", "to_actor": "Gilles",
                              "amount": 120000.0, "currency_id": self.xof.id,
                              "source": "google_sheets", "state": "validated",
                          }))
        self.assertFalse(recree)
        self.assertEqual(encore, transfert)
        self.assertEqual(encore.amount, 120000.0)

    def test_la_contrainte_de_montant_du_modele_tient_toujours(self):
        with self.assertRaises(ValidationError):
            self.env["dally.cash.transfer"].sudo().with_company(self.societe).create({
                "company_id": self.societe.id,
                "external_transfer_key": "TRF-ZERO",
                "transfer_date": "2026-08-22", "from_actor": "A", "to_actor": "B",
                "amount": 0.0, "currency_id": self.xof.id,
            })

    # ─── L'invariant et les contrôles de source ──────────────────────

    def test_l_invariant_de_securite_n_a_pas_bouge(self):
        lisibles = modeles_lisibles(self.env, self.gilles)
        self.assertEqual(lisibles, set(MODELES_TECHNIQUES_LISIBLES))
        for modele in MODELES_METIER_FERMES:
            self.assertNotIn(modele, lisibles)

    def test_le_transfert_et_les_utilisateurs_restent_fermes(self):
        for modele in ("dally.cash.transfer", "res.users",
                       "dally.ops.cash.transfer.request",
                       "dally.ops.cash.transfer.ack.request",
                       "dally.ops.audit.event"):
            self.assertFalse(
                self.env[modele].with_user(self.gilles).has_access("read"), modele)

    def test_le_controleur_ne_contient_ni_sudo_ni_cle_d_api(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_transfers
        code = code_seul(ops_transfers)
        for interdit in ("sudo", "SUPERUSER_ID", "API_KEY", "api_key",
                         "with_user", "search(", "browse("):
            self.assertNotIn(interdit, code)
        self.assertIn("auth='user'", code)

    def test_le_service_n_eleve_pas_les_privileges_au_dela_du_sudo(self):
        from odoo.addons.dally_ops_mobile.models import (
            ops_cash_actor_service, ops_transfer_service)
        for module in (ops_cash_actor_service, ops_transfer_service):
            code = code_seul(module)
            self.assertNotIn("SUPERUSER_ID", code)
            self.assertNotIn("user=1", code)

    def test_le_service_ne_calcule_aucun_solde_et_ne_convertit_rien(self):
        from odoo.addons.dally_ops_mobile.models import ops_transfer_service
        code = code_seul(ops_transfer_service)
        # Un « solde Gilles » calculé ici serait un chiffre faux affiché avec
        # autorité : ni solde initial, ni périmètre, ni corrections ne sont
        # définis. Et convertir demanderait un taux que personne n'a choisi.
        for interdit in ("balance", "solde", "_convert", "compute_amount",
                         "currency_id.rate", "res.currency.rate"):
            self.assertNotIn(interdit, code)


# ══════════════════════════════════════════════════════════════════════
#  Par HTTP réel
# ══════════════════════════════════════════════════════════════════════

@tagged("post_install", "-at_install", "dally")
class TestOpsCashTransfersHttp(HttpCase):
    """Les routes elles-mêmes, éprouvées par HTTP réel.

    L'étape 7 a appris pourquoi : un défaut n'existant que dans le chemin HTTP
    était invisible aux tests de service. C'est aussi ici que se mesure le
    privilège réellement exigé par Odoo pour écrire un transfert sous une
    identité sans droits.
    """

    MOT_DE_PASSE = "OpsProbe!2026#trf"

    def setUp(self):
        super().setUp()
        self.societe = self.env["res.company"].create({"name": "Ops Transferts HTTP SA"})
        self.xof = self.env.ref("base.XOF")
        self.xof.write({"active": True})

        self.gilles = self._compte(
            "http.trf.gilles", "Gilles HTTP",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Gilles")
        self.dalanda = self._compte(
            "http.trf.dalanda", "Dalanda HTTP",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Dalanda")
        self.alain = self._compte(
            "http.trf.alain", "Alain HTTP",
            "dally_ops_mobile.group_dally_ops_supervisor", acteur="Alain")
        self.etranger = self._compte("http.trf.autre", "Sans rôle", "base.group_user")

    def _compte(self, login, nom, groupe, acteur=None):
        valeurs = {
            "name": nom, "login": login, "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref(groupe).id])],
            "company_id": self.societe.id,
            "company_ids": [(6, 0, [self.societe.id])],
        }
        if acteur:
            valeurs["dally_ops_cash_actor"] = acteur
        return self.env["res.users"].create(valeurs)

    def _charge(self, **changements):
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "to_actor": "Dalanda",
            "transfer_date": "2026-08-28",
            "amount": 100000.0,
            "currency_code": "XOF",
            "payment_method": "cash",
            "reason": "Remise caisse du soir",
            "comment": "",
        }
        charge.update(changements)
        return charge

    def _poster(self, chemin, corps, login):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(
            chemin, data=json.dumps(corps),
            headers={"Content-Type": "application/json"}, allow_redirects=False)

    def _lire(self, chemin, login):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(chemin, allow_redirects=False)

    def test_les_options_sont_servies_par_http(self):
        reponse = self._lire("/api/v1/ops/cash-transfer-options", "http.trf.gilles")
        self.assertEqual(reponse.status_code, 200, reponse.content[:600])
        donnees = json.loads(reponse.content)["data"]
        self.assertEqual(donnees["from_actor"], "Gilles")
        self.assertEqual(
            sorted(d["actor"] for d in donnees["recipients"]), ["Alain", "Dalanda"])
        self.assertEqual([d["code"] for d in donnees["currencies"]][0], "XOF")

    def test_le_logisticien_enregistre_une_remise_par_http(self):
        """Le test qui décide du niveau de privilège."""
        reponse = self._poster(
            "/api/v1/ops/cash-transfers", self._charge(), "http.trf.gilles")
        self.assertEqual(reponse.status_code, 200, reponse.content[:800])
        donnees = json.loads(reponse.content)["data"]
        self.assertEqual(donnees["status"], "created")
        self.assertEqual(donnees["transfer"]["from_actor"], "Gilles")
        self.assertEqual(donnees["transfer"]["to_actor"], "Dalanda")
        self.assertEqual(donnees["transfer"]["state"], "pending_receipt")
        self.assertIsNone(donnees["transfer"]["acknowledged_at"])

    def test_la_liste_est_servie_par_http_et_propre_a_l_acteur(self):
        self._poster("/api/v1/ops/cash-transfers", self._charge(), "http.trf.gilles")
        for login, attendu in (("http.trf.gilles", 1), ("http.trf.dalanda", 1),
                               ("http.trf.alain", 0)):
            reponse = self._lire("/api/v1/ops/cash-transfers", login)
            self.assertEqual(reponse.status_code, 200, reponse.content[:600])
            self.assertEqual(
                len(json.loads(reponse.content)["data"]["transfers"]), attendu, login)

    def test_le_destinataire_confirme_par_http(self):
        creation = self._poster(
            "/api/v1/ops/cash-transfers", self._charge(), "http.trf.gilles")
        reference = json.loads(creation.content)["data"]["transfer"]["reference"]

        reponse = self._poster(
            "/api/v1/ops/cash-transfers/%s/acknowledge" % reference,
            {"request_uuid": str(uuid.uuid4())}, "http.trf.dalanda")
        self.assertEqual(reponse.status_code, 200, reponse.content[:800])
        donnees = json.loads(reponse.content)["data"]
        self.assertEqual(donnees["status"], "acknowledged")
        self.assertEqual(donnees["transfer"]["state"], "received")

        transfert = self.env["dally.cash.transfer"].sudo().search(
            [("external_transfer_key", "=", "ops:%s" % reference)], limit=1)
        self.assertEqual(transfert.state, "validated")
        self.assertEqual(transfert.acknowledged_by_user_id, self.dalanda)
        self.assertTrue(transfert.acknowledged_at)

    def test_l_expediteur_qui_forge_l_appel_est_refuse_par_http(self):
        """Le bouton caché ne suffit pas : la route elle-même refuse."""
        creation = self._poster(
            "/api/v1/ops/cash-transfers", self._charge(), "http.trf.gilles")
        reference = json.loads(creation.content)["data"]["transfer"]["reference"]

        reponse = self._poster(
            "/api/v1/ops/cash-transfers/%s/acknowledge" % reference,
            {"request_uuid": str(uuid.uuid4())}, "http.trf.gilles")
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(
            json.loads(reponse.content)["error"]["code"], "not_transfer_recipient")

        transfert = self.env["dally.cash.transfer"].sudo().search(
            [("external_transfer_key", "=", "ops:%s" % reference)], limit=1)
        self.assertEqual(transfert.state, "review")

    def test_un_responsable_non_destinataire_est_refuse_par_http(self):
        creation = self._poster(
            "/api/v1/ops/cash-transfers", self._charge(), "http.trf.gilles")
        reference = json.loads(creation.content)["data"]["transfer"]["reference"]
        reponse = self._poster(
            "/api/v1/ops/cash-transfers/%s/acknowledge" % reference,
            {"request_uuid": str(uuid.uuid4())}, "http.trf.alain")
        self.assertEqual(reponse.status_code, 403)

    def test_le_corps_de_confirmation_n_accepte_rien_d_autre(self):
        creation = self._poster(
            "/api/v1/ops/cash-transfers", self._charge(), "http.trf.gilles")
        reference = json.loads(creation.content)["data"]["transfer"]["reference"]
        for corps in ({"request_uuid": str(uuid.uuid4()), "state": "validated"},
                      {"request_uuid": str(uuid.uuid4()), "amount": 1},
                      {}):
            reponse = self._poster(
                "/api/v1/ops/cash-transfers/%s/acknowledge" % reference,
                corps, "http.trf.dalanda")
            self.assertEqual(reponse.status_code, 400)

    def test_un_authentifie_sans_role_ops_est_refuse(self):
        self.assertEqual(
            self._lire("/api/v1/ops/cash-transfer-options", "http.trf.autre").status_code,
            403)
        self.assertEqual(
            self._poster("/api/v1/ops/cash-transfers", self._charge(),
                         "http.trf.autre").status_code, 403)

    def test_un_anonyme_est_renvoye_vers_la_connexion(self):
        self.assertIn(
            self._lire("/api/v1/ops/cash-transfers", None).status_code, (302, 303))
        self.assertIn(
            self._poster("/api/v1/ops/cash-transfers", self._charge(), None).status_code,
            (302, 303))

    def test_les_refus_metier_remontent_avec_leur_code(self):
        for changement, statut, code in (
            ({"to_actor": "Gilles"}, 422, "same_actor"),
            ({"to_actor": "Inconnue"}, 422, "cash_recipient_not_available"),
            ({"transfer_date": "2099-01-01"}, 422, "invalid_transfer_date"),
            ({"currency_code": "USD"}, 422, "currency_not_available"),
            ({"payment_method": "cheque"}, 422, "payment_method_not_allowed"),
        ):
            reponse = self._poster(
                "/api/v1/ops/cash-transfers", self._charge(**changement),
                "http.trf.gilles")
            self.assertEqual(reponse.status_code, statut, changement)
            self.assertEqual(json.loads(reponse.content)["error"]["code"], code)

    def test_le_dto_http_ne_contient_aucun_identifiant_odoo(self):
        contenu = self._poster(
            "/api/v1/ops/cash-transfers", self._charge(), "http.trf.gilles").content.decode()
        for interdit in ("transfer_id", "company_id", "currency_id", "user_id",
                         "external_transfer_key", "acknowledged_by", "ops:",
                         "http.trf."):
            self.assertNotIn(interdit, contenu)
