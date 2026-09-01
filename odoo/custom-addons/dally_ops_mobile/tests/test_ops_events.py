# -*- coding: utf-8 -*-
"""Les événements opérationnels consignés depuis le terrain.

## Ce que ces tests protègent

**La séparation des deux journaux.** Un geste produit exactement un
`dally.shipment.event` — le fait métier — et un `dally.ops.audit.event` — la
preuve d'action. Ni deux fois l'un, ni l'un sans l'autre.

**Le silence côté client.** `visible_to_customer=False` et `is_automatic=False`
ne sont pas des valeurs par défaut qu'on pourrait remplacer : ce sont les deux
verrous qui garantissent qu'aucun message ne part et que rien n'apparaît au
portail. Le test de notification est le plus important du fichier.

**Le texte de l'opérateur.** Il va dans `internal_note`, jamais dans
`description`. `description` est publiée verbatim le jour où quelqu'un décide
de publier ; ce jour-là, elle doit contenir un libellé choisi par le serveur.

**L'immobilité de l'état.** Un événement décrit, il ne fait pas avancer. La
machine à états de l'étape 2 reste le seul chemin de transition.
"""

import uuid
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError
from odoo.addons.dally_ops_mobile.models.ops_event import OPS_EVENT_KINDS
from odoo.addons.dally_ops_mobile.models.ops_event_service import (
    KINDS_NOTE_REQUISE,
    LIBELLES_KIND,
    LONGUEUR_NOTE,
)


@tagged("post_install", "-at_install", "dally")
class TestOpsEvents(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.societe = cls.env.company
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Event Autre"})

        cls.gilles = cls._compte(
            "event.gilles", "dally_ops_mobile.group_dally_ops_logistician")
        cls.responsable = cls._compte(
            "event.resp", "dally_ops_mobile.group_dally_ops_supervisor")
        cls.temoin = cls._compte("event.temoin", "base.group_user")

        Famille = cls.env["dally.freight.tariff.family"]
        Regle = cls.env["dally.freight.tariff.rule"]
        cls.famille = Famille.search([("code", "=", "non_food")], limit=1)
        if not cls.famille:
            cls.famille = Famille.create(
                {"name": "Event Non alimentaire", "code": "non_food"})
        if not Regle.search([("family_id", "=", cls.famille.id),
                             ("transport_mode", "=", "air")], limit=1):
            Regle.create({
                "name": "Event non_food air", "transport_mode": "air",
                "family_id": cls.famille.id, "customer_segment": "all",
                "price_per_kg_eur": 5.0,
            })

        cls.partner = cls.env["res.partner"].create({
            "name": "Aissatou Event", "company_id": cls.societe.id,
            "phone": "+221770000041", "email": "aissatou.event@example.test",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.depart = cls._consolidation("AIR-DSS-CDG-EVENT-001")

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
        return (self.env["dally.ops.event.service"]
                .with_user(utilisateur or self.gilles)
                .with_company(societe or self.societe))

    def _etat(self, reference, etat):
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

    def _consigner(self, reference, kind="anomaly", note="Carton enfoncé",
                   request_uuid=_ABSENT, utilisateur=None, **extra):
        charge = {
            "request_uuid": (str(uuid.uuid4())
                             if request_uuid is self._ABSENT else request_uuid),
            "kind": kind,
        }
        if note is not None:
            charge["note"] = note
        charge.update(extra)
        return self._service(utilisateur).create_event(reference, charge)

    def _lister(self, reference, utilisateur=None):
        return self._service(utilisateur).list_events(reference)

    def _evenements(self, shipment):
        return self.env["dally.shipment.event"].sudo().search(
            [("shipment_id", "=", shipment.id)], order="id")

    def _audits(self, action="event_recorded"):
        return self.env["dally.ops.audit.event"].sudo().search([
            ("company_id", "=", self.societe.id), ("action", "=", action)])

    def _notifications(self):
        return self.env["dally.shipment.notification"].sudo().search_count([])

    def _outbox(self, shipment):
        return self.env["dally.ops.sheet.outbox"].sudo().search([
            ("resource_id", "=", shipment.id)])

    # ─── E01 à E04 · rôles et portée ─────────────────────────────────

    def test_E01_un_logisticien_consigne_un_evenement(self):
        reference = self._creer_dossier()
        resultat = self._consigner(reference)
        self.assertFalse(resultat["replayed"])
        self.assertEqual(resultat["event"]["kind"], "anomaly")
        self.assertEqual(resultat["event"]["recorded_by"], self.gilles.name)

    def test_E02_un_responsable_consigne_aussi(self):
        reference = self._creer_dossier()
        resultat = self._consigner(reference, utilisateur=self.responsable)
        self.assertEqual(resultat["event"]["recorded_by"], self.responsable.name)

    def test_E03_un_compte_sans_role_ops_est_refuse(self):
        from odoo.exceptions import AccessError
        reference = self._creer_dossier()
        with self.assertRaises(AccessError):
            self._consigner(reference, utilisateur=self.temoin)

    def test_E04_un_dossier_d_une_autre_societe_est_invisible(self):
        """La clause de société, isolée.

        Un dossier Ops complet — clé `ops:`, origine back-office — déplacé dans
        une autre société. Seule la clause de société peut alors l'exclure.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        self.assertTrue(shipment.sync_source_key.startswith("ops:"))
        shipment.write({"company_id": self.autre_societe.id})
        with self.assertRaises(DallyOpsError) as leve:
            self._consigner(reference)
        self.assertEqual(leve.exception.code, "intake_not_found")

    def test_E05_un_dossier_historique_est_refuse(self):
        self._dossier_ancien("AIR-DSS-CDG-2019-077")
        with self.assertRaises(DallyOpsError) as leve:
            self._consigner("AIR-DSS-CDG-2019-077")
        self.assertEqual(leve.exception.code, "intake_not_found")

    def test_E06_un_dossier_repris_du_tableur_est_refuse(self):
        dossier = self._dossier_ancien("AIR-DSS-CDG-SHEET-077")
        dossier.sudo().write({"sync_source": "google_sheets",
                              "sync_source_key": "sheet:A077"})
        with self.assertRaises(DallyOpsError) as leve:
            self._consigner("AIR-DSS-CDG-SHEET-077")
        self.assertEqual(leve.exception.code, "intake_not_found")

    # ─── E07 à E10 · états ───────────────────────────────────────────

    def test_E07_goods_received_preparing_et_ready_acceptent(self):
        for etat in ("goods_received", "preparing", "ready"):
            reference = self._creer_dossier()
            if etat != "goods_received":
                self._etat(reference, etat)
            resultat = self._consigner(reference, kind="repacked", note=None)
            self.assertEqual(resultat["event"]["status"], etat, etat)

    def test_E08_un_dossier_annule_refuse(self):
        reference = self._creer_dossier()
        self._shipment(reference).sudo().write({"state": "cancelled"})
        with self.assertRaises(DallyOpsError) as leve:
            self._consigner(reference)
        self.assertEqual(leve.exception.code, "event_state_not_allowed")

    def test_E09_un_dossier_parti_refuse(self):
        reference = self._creer_dossier()
        self._etat(reference, "ready")
        self._shipment(reference).sudo(False)._write_historical_state("departed")
        with self.assertRaises(DallyOpsError) as leve:
            self._consigner(reference)
        self.assertEqual(leve.exception.code, "event_state_not_allowed")

    def test_E10_l_etat_photographie_est_celui_du_moment(self):
        reference = self._creer_dossier()
        self._etat(reference, "preparing")
        resultat = self._consigner(reference, kind="handover", note=None)
        self.assertEqual(resultat["event"]["status"], "preparing")
        # Le libellé vient de la sélection du modèle, pas d'une seconde table :
        # on vérifie qu'il en sort, sans figer la langue du serveur.
        attendu = dict(self.env["dally.shipment.event"]._fields["status"]
                       ._description_selection(self.env))["preparing"]
        self.assertEqual(resultat["event"]["status_label"], attendu)
        self.assertNotEqual(resultat["event"]["status_label"], "preparing")

    # ─── E11 à E15 · natures et note ─────────────────────────────────

    def test_E11_les_sept_natures_sont_acceptees(self):
        for code, libelle in OPS_EVENT_KINDS:
            reference = self._creer_dossier()
            note = "Motif détaillé" if code in KINDS_NOTE_REQUISE else None
            resultat = self._consigner(reference, kind=code, note=note)
            self.assertEqual(resultat["event"]["kind"], code, code)
            self.assertEqual(resultat["event"]["kind_label"], libelle, code)

    def test_E12_une_nature_inconnue_est_refusee(self):
        reference = self._creer_dossier()
        for inconnu in ("selfie", "", None, 42):
            with self.assertRaises(DallyOpsError) as leve:
                self._consigner(reference, kind=inconnu)
            self.assertEqual(leve.exception.code, "event_kind_invalid",
                             repr(inconnu))

    def test_E13_la_note_est_exigee_pour_trois_natures(self):
        for code in sorted(KINDS_NOTE_REQUISE):
            reference = self._creer_dossier()
            for absente in (None, "", "  ", "ab"):
                with self.assertRaises(DallyOpsError) as leve:
                    self._consigner(reference, kind=code, note=absente)
                self.assertEqual(leve.exception.code, "event_note_required",
                                 "%s / %r" % (code, absente))

    def test_E14_la_note_est_facultative_pour_les_autres(self):
        for code in sorted(set(dict(OPS_EVENT_KINDS)) - KINDS_NOTE_REQUISE):
            reference = self._creer_dossier()
            resultat = self._consigner(reference, kind=code, note=None)
            self.assertEqual(resultat["event"]["note"], "", code)

    def test_E15_une_note_trop_longue_est_refusee(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as leve:
            self._consigner(reference, note="x" * (LONGUEUR_NOTE + 1))
        self.assertEqual(leve.exception.code, "event_note_too_long")

    # ─── E16 à E19 · le contrat d'écriture ───────────────────────────

    def test_E16_la_description_vient_du_serveur_jamais_de_l_operateur(self):
        """`description` est publiée verbatim le jour où l'on publie.

        Le texte de l'opérateur n'a donc rien à y faire, même quand
        `visible_to_customer` vaut faux : un drapeau se retourne, un champ mal
        rempli reste.
        """
        reference = self._creer_dossier()
        secret = "NE DOIT PAS ETRE PUBLIE"
        self._consigner(reference, kind="anomaly", note=secret)
        evenement = self._evenements(self._shipment(reference)).filtered(
            "ops_event_kind")
        self.assertEqual(evenement.description, LIBELLES_KIND["anomaly"])
        self.assertNotIn(secret, evenement.description)
        self.assertEqual(evenement.internal_note, secret)

    def test_E17_l_evenement_reste_ferme_au_client(self):
        reference = self._creer_dossier()
        self._consigner(reference)
        evenement = self._evenements(self._shipment(reference)).filtered(
            "ops_event_kind")
        self.assertFalse(evenement.visible_to_customer)
        self.assertFalse(evenement.is_automatic)
        self.assertEqual(evenement.user_id.id, self.gilles.id)
        self.assertTrue(evenement.event_date)

    def test_E18_aucun_champ_de_l_api_n_ouvre_la_publication(self):
        """Les clés qui décideraient de la visibilité n'existent pas.

        Les proposer doit faire tomber la demande entière, et non être ignoré
        en silence : un appelant qui croit publier doit l'apprendre.
        """
        reference = self._creer_dossier()
        for interdit in ("visible_to_customer", "is_automatic", "status",
                         "description", "event_date", "user_id", "company_id",
                         "shipment_id", "location", "publish", "notify"):
            with self.assertRaises(DallyOpsError, msg=interdit):
                self._consigner(reference, **{interdit: True})

    def test_E19_la_nature_est_persistee_sur_l_evenement(self):
        reference = self._creer_dossier()
        self._consigner(reference, kind="damage_noted", note="Coin écrasé")
        evenement = self._evenements(self._shipment(reference)).filtered(
            "ops_event_kind")
        self.assertEqual(evenement.ops_event_kind, "damage_noted")

    # ─── E20 à E23 · ce qui ne doit pas bouger ───────────────────────

    def test_E20_l_etat_du_dossier_ne_bouge_pas(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        avant = shipment.state
        self._consigner(reference)
        shipment.invalidate_recordset(["state"])
        self.assertEqual(shipment.state, avant)

    def test_E21_aucune_notification_client_n_est_mise_en_file(self):
        """Le garde le plus important du fichier.

        `goods_received` a `notify_customer=True` dans la politique : une
        transition vers cet état écrit bien au client. Un événement de terrain
        au même état ne doit rien écrire — et ce n'est pas une vigilance, c'est
        `is_automatic=False` qui le rend impossible.
        """
        reference = self._creer_dossier()
        avant = self._notifications()
        self._consigner(reference, kind="customer_contacted", note=None)
        self.assertEqual(self._notifications(), avant)

    def test_E22_aucune_projection_tableur(self):
        """Compter les lignes ne suffit pas : `enqueue_dossier` est idempotente.

        La réception a déjà posé une ligne pour ce dossier ; un second appel
        n'en ajouterait aucune, et un test qui compte passerait au vert alors
        qu'une projection aurait bel et bien été réveillée.

        Ce qui se mesure, c'est donc l'état de la ligne : on la marque livrée,
        et elle doit le rester. Un `enqueue_dossier` la remettrait en attente —
        un transport de plus vers le tableur, pour un événement qui n'y change
        rien.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        lignes = self._outbox(shipment)
        self.assertTrue(lignes, "la réception doit avoir posé une projection")
        lignes.write({"state": "delivered",
                      "delivered_at": fields.Datetime.now()})
        nombre_avant = len(lignes)

        self._consigner(reference)

        apres = self._outbox(shipment)
        self.assertEqual(len(apres), nombre_avant)
        for ligne in apres:
            self.assertEqual(
                ligne.state, "delivered",
                "un événement ne doit pas réveiller la projection du dossier")

    def test_E23_aucun_evenement_automatique_n_est_engendre(self):
        """Un geste, un événement. Pas deux, et surtout pas un automatique."""
        reference = self._creer_dossier()
        avant = len(self._evenements(self._shipment(reference)))
        self._consigner(reference)
        apres = self._evenements(self._shipment(reference))
        self.assertEqual(len(apres), avant + 1)
        self.assertEqual(len(apres.filtered("ops_event_kind")), 1)

    # ─── E24 à E28 · rejeu et concurrence ────────────────────────────

    def test_E24_le_meme_geste_renvoye_rend_le_meme_evenement(self):
        reference = self._creer_dossier()
        geste = str(uuid.uuid4())
        premier = self._consigner(reference, request_uuid=geste)
        second = self._consigner(reference, request_uuid=geste)
        self.assertFalse(premier["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(second["event"]["event_date"],
                         premier["event"]["event_date"])

    def test_E25_un_rejeu_ne_cree_ni_second_evenement_ni_second_audit(self):
        reference = self._creer_dossier()
        geste = str(uuid.uuid4())
        avant = len(self._audits())
        self._consigner(reference, request_uuid=geste)
        self._consigner(reference, request_uuid=geste)
        self.assertEqual(
            len(self._evenements(self._shipment(reference)).filtered(
                "ops_event_kind")), 1)
        self.assertEqual(len(self._audits()), avant + 1)

    def test_E26_le_meme_identifiant_sur_une_autre_intention_est_un_conflit(self):
        reference = self._creer_dossier()
        geste = str(uuid.uuid4())
        self._consigner(reference, kind="anomaly", note="Premier motif",
                        request_uuid=geste)
        for autre in ({"kind": "repacked", "note": None},
                      {"kind": "anomaly", "note": "Second motif"}):
            with self.assertRaises(DallyOpsError) as leve:
                self._consigner(reference, request_uuid=geste, **autre)
            self.assertEqual(leve.exception.code, "idempotency_conflict",
                             repr(autre))

    def test_E27_un_identifiant_de_geste_invalide_est_refuse(self):
        reference = self._creer_dossier()
        for mauvais in (None, "", "pas-un-uuid", 7):
            with self.assertRaises(DallyOpsError):
                self._consigner(reference, request_uuid=mauvais)

    def test_E28_le_verrou_du_dossier_precede_la_lecture_de_l_etat(self):
        """L'ordre est la garantie, et il se mesure.

        Deux gestes concurrents photographieraient sinon deux états différents
        du même instant. La sentinelle prouve l'ordre ; le second contrôle
        épingle la primitive, qu'un corps vidé de sa clause bloquante rendrait
        inopérante sans que la sentinelle s'en aperçoive.
        """
        import inspect
        import re

        reference = self._creer_dossier()
        service = type(self.env["dally.ops.event.service"])

        sentinelle = RuntimeError("verrou de dossier atteint")
        with patch.object(service, "_verrouiller_dossier", side_effect=sentinelle):
            with self.assertRaises(RuntimeError) as leve:
                self._consigner(reference)
        self.assertIs(leve.exception, sentinelle)

        source = re.sub(
            r"\s+", " ", inspect.getsource(service._verrouiller_dossier)).upper()
        self.assertIn("FOR UPDATE", source)
        self.assertLess(source.index("FROM DALLY_SHIPMENT"),
                        source.index("FOR UPDATE"))

    # ─── E29 à E32 · audit et lecture ────────────────────────────────

    def test_E29_l_audit_designe_l_evenement_et_son_dossier(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        self._consigner(reference)
        evenement = self._evenements(shipment).filtered("ops_event_kind")

        audits = self._audits()
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits.entity_model, "dally.shipment.event")
        self.assertEqual(audits.entity_res_id, evenement.id)
        self.assertEqual(audits.shipment_id.id, shipment.id)
        self.assertNotEqual(audits.entity_res_id, shipment.id)

    def test_E30_l_audit_ne_recopie_pas_la_note(self):
        """La note vit dans `internal_note`. La dupliquer ferait deux endroits
        à purger le jour où quelqu'un demandera son effacement."""
        reference = self._creer_dossier()
        secret = "Numero de telephone du voisin"
        self._consigner(reference, note=secret)
        self.assertNotIn(secret, str(self._audits().changes_json))

    def test_E31_la_liste_montre_les_saisies_et_masque_les_automatiques(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        # Une transition engendre un événement automatique…
        self._etat(reference, "preparing")
        automatiques = self._evenements(shipment).filtered("is_automatic")
        self.assertTrue(automatiques)
        # …une saisie backoffice en engendre un manuel sans nature Ops…
        self.env["dally.shipment.event"].sudo().create({
            "shipment_id": shipment.id, "status": shipment.state,
            "description": "Note du backoffice", "is_automatic": False,
        })
        # …et le terrain en engendre un manuel avec nature.
        self._consigner(reference, kind="repacked", note=None)

        liste = self._lister(reference)
        sources = sorted(e["source"] for e in liste["events"])
        self.assertEqual(sources, ["backoffice", "ops"])
        self.assertTrue(liste["can_add"])
        self.assertEqual(len(liste["kinds"]), len(OPS_EVENT_KINDS))

    def test_E32_le_contrat_ne_publie_aucun_identifiant_technique(self):
        reference = self._creer_dossier()
        self._consigner(reference)
        liste = self._lister(reference)
        rendu = str(liste)
        for interdit in ("res_model", "res_id", "user_id", "company_id",
                         "shipment_id", "internal_note", "visible_to_customer",
                         "is_automatic", "attachment"):
            self.assertNotIn(interdit, rendu, interdit)
        self.assertEqual(set(liste["events"][0]), {
            "kind", "kind_label", "description", "note", "status",
            "status_label", "event_date", "recorded_by", "source"})

    def test_E33_can_add_suit_l_etat_du_dossier(self):
        reference = self._creer_dossier()
        self.assertTrue(self._lister(reference)["can_add"])
        self._shipment(reference).sudo().write({"state": "cancelled"})
        self.assertFalse(self._lister(reference)["can_add"])

    def test_E34_la_capacite_est_ouverte_aux_deux_roles(self):
        for compte in (self.gilles, self.responsable):
            capacites = (self.env["res.users"].with_user(compte)
                         ._dally_ops_capabilities())
            self.assertTrue(capacites["event_create"], compte.name)

    def test_E34b_la_capacite_est_fermee_a_qui_n_a_pas_de_role_ops(self):
        """Ouvrir une capacité, c'est aussi la fermer à tous les autres.

        Le service refuse déjà un compte sans rôle — E03 le mesure. Mais la
        capacité voyage jusqu'au navigateur : si elle passait à vrai pour un
        compte interne quelconque, l'écran proposerait un bouton que le serveur
        refuserait ensuite. Les deux moitiés doivent tomber ensemble.
        """
        capacites = (self.env["res.users"].with_user(self.temoin)
                     ._dally_ops_capabilities())
        self.assertIn("event_create", capacites)
        self.assertFalse(capacites["event_create"])
        # Et ce n'est pas propre aux événements : aucune capacité ne s'ouvre
        # sans rôle Ops.
        self.assertFalse(any(capacites.values()), sorted(
            nom for nom, ouverte in capacites.items() if ouverte))

    def test_E35_la_permission_de_synchro_sur_les_evenements_est_inchangee(self):
        """Non-régression volontaire.

        `group_dally_freight_sync_api` porte des droits de création sur
        `dally.shipment.event` depuis avant cette étape. Ce n'est pas notre
        dette, et la retirer pourrait casser un flux ancien : on l'épingle pour
        qu'un changement futur soit une décision, pas un effet de bord.
        """
        acces = self.env["ir.model.access"].sudo().search([
            ("model_id.model", "=", "dally.shipment.event"),
            ("group_id", "=", self.env.ref(
                "dally_freight_billing.group_dally_freight_sync_api").id),
        ])
        self.assertTrue(acces)
        self.assertTrue(acces.perm_create)
        self.assertFalse(acces.perm_write)
        self.assertFalse(acces.perm_unlink)
