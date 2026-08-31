# -*- coding: utf-8 -*-
"""L'avancement d'état d'un dossier, depuis le terrain.

## Ce que ces tests protègent

**L'autorité de la machine à états.** Elle vit dans `dally_freight` —
`ALLOWED_STATE_TRANSITIONS`, les gates, les effets de bord. Ops n'en tient pas
une copie : il en propose un sous-ensemble et laisse `action_set_state` trancher.
Un test échoue si quelqu'un recopie la matrice ici.

**Ce que le terrain n'a pas le droit de faire.** Le départ appartient à la
consolidation : il est collectif, atomique, et sa gate financière ne se
satisfait pas depuis un téléphone. L'annulation n'est pas un geste de comptoir.
Ni l'un ni l'autre n'apparaît jamais dans `allowed_transitions`.

**Le rejeu.** Un entrepôt perd le réseau au mauvais moment. Le même geste
renvoyé ne doit produire qu'une transition, un audit, une projection — et le
même identifiant portant une **autre** intention doit être refusé plutôt que de
recevoir en silence le résultat du premier.

**Le privilège.** Un logisticien Ops n'a pas `group_dally_logistics` et ne doit
pas l'obtenir. Le privilège vit dans le service, après que le rôle Ops, la
société et le domaine Ops ont été vérifiés.
"""

import json
import uuid
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError


@tagged("post_install", "-at_install", "dally")
class TestOpsIntakeState(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.societe = cls.env.company
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops State Autre"})

        cls.gilles = cls._compte(
            "state.gilles", "dally_ops_mobile.group_dally_ops_logistician")
        cls.responsable = cls._compte(
            "state.resp", "dally_ops_mobile.group_dally_ops_supervisor")
        cls.temoin = cls._compte("state.temoin", "base.group_user")

        Famille = cls.env["dally.freight.tariff.family"]
        Regle = cls.env["dally.freight.tariff.rule"]
        cls.famille = Famille.search([("code", "=", "non_food")], limit=1)
        if not cls.famille:
            cls.famille = Famille.create(
                {"name": "State Non alimentaire", "code": "non_food"})
        if not Regle.search([("family_id", "=", cls.famille.id),
                             ("transport_mode", "=", "air")], limit=1):
            Regle.create({
                "name": "State non_food air", "transport_mode": "air",
                "family_id": cls.famille.id, "customer_segment": "all",
                "price_per_kg_eur": 5.0,
            })

        cls.partner = cls.env["res.partner"].create({
            "name": "Aissatou State", "company_id": cls.societe.id,
            "phone": "+221770000021",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.depart = cls._consolidation("AIR-DSS-CDG-STATE-001")

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

    def _service(self, utilisateur=None):
        return (self.env["dally.ops.intake.state.service"]
                .with_user(utilisateur or self.gilles).with_company(self.societe))

    #: Sentinelle : « le test n'a rien dit », par opposition à « le test a dit
    #: None ». Sans elle, un `request_uuid=None` volontaire serait remplacé par
    #: un identifiant valide, et R37 ne testerait plus rien.
    _ABSENT = object()

    def _avancer(self, reference, attendu, cible, request_uuid=_ABSENT,
                 utilisateur=None, **extra):
        charge = {
            "request_uuid": (
                str(uuid.uuid4()) if request_uuid is self._ABSENT
                else request_uuid),
            "expected_state": attendu,
            "target_state": cible,
        }
        charge.update(extra)
        return self._service(utilisateur).advance_state(reference, charge)

    def _audits(self, action="intake_state_advanced"):
        return self.env["dally.ops.audit.event"].sudo().search([
            ("company_id", "=", self.societe.id), ("action", "=", action)])

    def _outbox(self, shipment):
        return self.env["dally.ops.sheet.outbox"].sudo().search([
            ("company_id", "=", self.societe.id),
            ("projection_type", "=", "freight_dossier"),
            ("resource_id", "=", shipment.id)])

    def _evenements_suivi(self, shipment, statut):
        return self.env["dally.shipment.event"].sudo().search([
            ("shipment_id", "=", shipment.id), ("status", "=", statut)])

    def _preparer(self, reference):
        """Amène un dossier à `preparing` par le chemin normal."""
        self._avancer(reference, "goods_received", "preparing")
        return self._shipment(reference)

    # ─── R1/R2 · les deux transitions autorisées ─────────────────────

    def test_R1_goods_received_vers_preparing(self):
        reference = self._creer_dossier()
        resultat = self._avancer(reference, "goods_received", "preparing")
        self.assertEqual(resultat["status"], "updated")
        self.assertEqual(resultat["state"], "preparing")
        self.assertEqual(resultat["reference"], reference)
        self.assertEqual(self._shipment(reference).state, "preparing")

    def test_R2_preparing_vers_ready_si_le_dossier_est_pret(self):
        reference = self._creer_dossier()
        self._preparer(reference)
        resultat = self._avancer(reference, "preparing", "ready")
        self.assertEqual(resultat["status"], "updated")
        self.assertEqual(resultat["state"], "ready")
        self.assertEqual(self._shipment(reference).state, "ready")

    # ─── R3/R4/R5 · ce que le terrain ne peut pas faire ──────────────

    def test_R3_goods_received_vers_ready_est_refuse(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "goods_received", "ready")
        self.assertEqual(erreur.exception.code, "state_transition_not_allowed")
        self.assertEqual(self._shipment(reference).state, "goods_received")

    def test_R4_departed_est_refuse_depuis_ops(self):
        """Le départ appartient à la consolidation, pas au comptoir."""
        reference = self._creer_dossier()
        self._preparer(reference)
        self._avancer(reference, "preparing", "ready")
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "ready", "departed")
        self.assertEqual(erreur.exception.code, "state_target_not_allowed")
        self.assertEqual(self._shipment(reference).state, "ready")

    def test_R5_cancelled_est_refuse_depuis_ops(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "goods_received", "cancelled")
        self.assertEqual(erreur.exception.code, "state_target_not_allowed")
        self.assertEqual(self._shipment(reference).state, "goods_received")

    # ─── R6 · état périmé ────────────────────────────────────────────

    def test_R6_un_expected_state_perime_est_refuse(self):
        reference = self._creer_dossier()
        self._preparer(reference)
        avant_audits = len(self._audits())
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "goods_received", "preparing")
        self.assertEqual(erreur.exception.code, "state_changed")
        self.assertEqual(erreur.exception.status, 409)
        self.assertEqual(len(self._audits()), avant_audits)

    # ─── R7 à R12 · rejeu et conflit d'intention ─────────────────────

    def test_R7_le_meme_geste_rejoue_est_un_replay(self):
        reference = self._creer_dossier()
        identifiant = str(uuid.uuid4())
        premier = self._avancer(reference, "goods_received", "preparing",
                                request_uuid=identifiant)
        second = self._avancer(reference, "goods_received", "preparing",
                               request_uuid=identifiant)
        self.assertEqual(premier["status"], "updated")
        self.assertEqual(second["status"], "replayed")
        self.assertEqual(second["state"], "preparing")

    def test_R8_un_rejeu_ne_produit_quun_seul_audit(self):
        reference = self._creer_dossier()
        identifiant = str(uuid.uuid4())
        self._avancer(reference, "goods_received", "preparing", request_uuid=identifiant)
        self._avancer(reference, "goods_received", "preparing", request_uuid=identifiant)
        self._avancer(reference, "goods_received", "preparing", request_uuid=identifiant)
        self.assertEqual(len(self._audits().filtered(
            lambda evenement: evenement.request_uuid == identifiant)), 1)

    def test_R9_un_rejeu_ne_produit_quune_seule_projection(self):
        """Un rejeu ne réveille pas une projection déjà transportée.

        Compter les lignes ne suffirait pas : `enqueue_dossier` est idempotente
        et n'en crée jamais deux. Ce qu'elle ferait, en revanche, c'est
        remettre une ligne `delivered` en `pending` — un transport de plus vers
        le classeur pour un geste qui n'a pas eu lieu. On livre donc la ligne
        avant de rejouer, et on vérifie qu'elle le reste.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        identifiant = str(uuid.uuid4())
        self._avancer(reference, "goods_received", "preparing", request_uuid=identifiant)

        lignes = self._outbox(shipment)
        self.assertEqual(len(lignes), 1)
        tentatives = lignes.attempt_count
        lignes.write({"state": "delivered", "delivered_at": fields.Datetime.now()})

        self._avancer(reference, "goods_received", "preparing", request_uuid=identifiant)

        apres = self._outbox(shipment)
        self.assertEqual(len(apres), 1)
        self.assertEqual(apres.attempt_count, tentatives)
        self.assertEqual(
            apres.state, "delivered",
            "un rejeu ne doit pas remettre la projection en attente")

    def test_R10_meme_identifiant_autre_cible_est_un_conflit(self):
        reference = self._creer_dossier()
        identifiant = str(uuid.uuid4())
        self._avancer(reference, "goods_received", "preparing", request_uuid=identifiant)
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "preparing", "ready", request_uuid=identifiant)
        self.assertEqual(erreur.exception.code, "idempotency_conflict")

    def test_R11_meme_identifiant_autre_etat_attendu_est_un_conflit(self):
        reference = self._creer_dossier()
        identifiant = str(uuid.uuid4())
        self._avancer(reference, "goods_received", "preparing", request_uuid=identifiant)
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "preparing", "preparing", request_uuid=identifiant)
        self.assertEqual(erreur.exception.code, "idempotency_conflict")

    def test_R12_meme_identifiant_autre_dossier_est_un_conflit(self):
        premier = self._creer_dossier()
        second = self._creer_dossier()
        identifiant = str(uuid.uuid4())
        self._avancer(premier, "goods_received", "preparing", request_uuid=identifiant)
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(second, "goods_received", "preparing", request_uuid=identifiant)
        self.assertEqual(erreur.exception.code, "idempotency_conflict")
        self.assertEqual(self._shipment(second).state, "goods_received")

    # ─── R13 à R17 · portée des dossiers ─────────────────────────────

    def test_R13_un_dossier_dune_autre_societe_est_introuvable(self):
        """La société isolée seule.

        Un dossier Ops complet — clé `ops:`, origine back-office, consolidation
        d'entrée — que l'on déplace dans une autre société. Seule la clause de
        société peut alors l'exclure : c'est ce qui rend ce test capable de
        détecter sa disparition.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        self.assertTrue(shipment.sync_source_key.startswith("ops:"))
        self.assertEqual(shipment.sync_source, "backoffice")
        self.assertTrue(shipment.intake_consolidation_id)
        shipment.write({"company_id": self.autre_societe.id})

        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "goods_received", "preparing")
        self.assertEqual(erreur.exception.code, "intake_not_found")
        self.assertEqual(self._shipment(reference).state, "goods_received")

    def test_R14_un_dossier_ancien_nest_pas_mutable(self):
        """Le cas réel : un dossier repris du classeur, exclu par tout."""
        ancien = self._dossier_ancien("A012")
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer("A012", "goods_received", "preparing")
        self.assertEqual(erreur.exception.code, "intake_not_found")
        self.assertEqual(ancien.state, "draft")

    def test_R14b_une_cle_de_source_non_ops_isole_la_clause(self):
        """La clé `ops:` isolée seule.

        Un dossier créé par le moteur Freight avec une clé de source qui n'est
        pas celle d'Ops : même société, même origine back-office, même
        consolidation d'entrée. Seule la clause `sync_source_key` l'exclut.
        """
        charge = (self.env["dally.ops.intake.service"]
                  .with_user(self.gilles).with_company(self.societe)
                  ._charge_freight(
                      {"request_uuid": str(uuid.uuid4()),
                       "received_on": "2026-08-29",
                       "line": {"line_uuid": str(uuid.uuid4()),
                                "package_type": "parcel",
                                "goods_category": "Non alimentaire",
                                "description": "Savon", "quantity": 1,
                                "announced_weight_kg": None,
                                "exact_weight_kg": 13.5, "length_cm": None,
                                "width_cm": None, "height_cm": None,
                                "billing_method": "real",
                                "customs_value_xof": 25000}},
                      self.partner, self.depart, self.famille))
        charge["sync_source_key"] = "sheet:%s" % uuid.uuid4()
        charge["lines"][0]["external_line_key"] = "%s:line:1" % charge["sync_source_key"]
        _resultat, shipment = (self.env["dally.freight.sync.service"].sudo()
                               .with_company(self.societe).upsert(charge))
        self.assertEqual(shipment.sync_source, "backoffice")
        self.assertTrue(shipment.intake_consolidation_id)
        self.assertFalse(shipment.sync_source_key.startswith("ops:"))

        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(shipment.external_reference, "goods_received", "preparing")
        self.assertEqual(erreur.exception.code, "intake_not_found")

    def test_R15_un_dossier_du_classeur_nest_pas_mutable(self):
        """L'origine isolée seule.

        Un dossier Ops complet dont on change la seule origine. Rien d'autre ne
        bouge : c'est la clause `sync_source` qui doit l'exclure, et elle seule.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        shipment.write({"sync_source": "google_sheets"})

        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "goods_received", "preparing")
        self.assertEqual(erreur.exception.code, "intake_not_found")
        self.assertEqual(self._shipment(reference).state, "goods_received")

    def test_R16_la_reference_locale_nest_jamais_une_cle(self):
        reference = self._creer_dossier()
        locale = self._shipment(reference).collection_local_ref
        self.assertTrue(locale)
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(locale, "goods_received", "preparing")
        self.assertEqual(erreur.exception.code, "intake_not_found")
        self.assertEqual(self._shipment(reference).state, "goods_received")

    def test_R17_la_reference_globale_est_acceptee(self):
        reference = self._creer_dossier()
        self.assertEqual(
            self._avancer(reference, "goods_received", "preparing")["state"],
            "preparing")

    # ─── R18 à R20 · rôles ───────────────────────────────────────────

    def test_R18_un_logisticien_ops_avance_sans_group_dally_logistics(self):
        """Le privilège vit dans le service, pas dans le groupe de l'opérateur."""
        self.assertFalse(
            self.gilles.has_group("dally_core.group_dally_logistics"),
            "le rôle Ops ne doit pas impliquer le rôle Logistics d'Odoo")
        reference = self._creer_dossier()
        self.assertEqual(
            self._avancer(reference, "goods_received", "preparing")["state"],
            "preparing")
        self.assertFalse(self.gilles.has_group("dally_core.group_dally_logistics"))

    def test_R19_un_responsable_avance_aussi(self):
        reference = self._creer_dossier()
        resultat = self._avancer(reference, "goods_received", "preparing",
                                 utilisateur=self.responsable)
        self.assertEqual(resultat["state"], "preparing")

    def test_R20_un_compte_sans_role_ops_est_refuse(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "goods_received", "preparing",
                          utilisateur=self.temoin)
        self.assertEqual(erreur.exception.code, "ops_forbidden")
        self.assertEqual(self._shipment(reference).state, "goods_received")

    # ─── R21 à R25 · ce que le serveur propose ───────────────────────

    def test_R21_depuis_goods_received_une_seule_cible(self):
        reference = self._creer_dossier()
        self.assertEqual(
            self._service().allowed_transitions(self._shipment(reference)),
            ["preparing"])

    def test_R22_depuis_preparing_une_seule_cible(self):
        reference = self._creer_dossier()
        self._preparer(reference)
        self.assertEqual(
            self._service().allowed_transitions(self._shipment(reference)),
            ["ready"])

    def test_R23_depuis_ready_aucune_cible(self):
        reference = self._creer_dossier()
        self._preparer(reference)
        self._avancer(reference, "preparing", "ready")
        self.assertEqual(
            self._service().allowed_transitions(self._shipment(reference)), [])

    def test_R24_departed_napparait_jamais(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        for etape in ("goods_received", "preparing", "ready"):
            self.assertNotIn("departed", self._service().allowed_transitions(shipment))
            suivant = self._service().allowed_transitions(shipment)
            if suivant:
                self._avancer(reference, shipment.state, suivant[0])
                shipment = self._shipment(reference)

    def test_R25_cancelled_napparait_jamais(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        self.assertNotIn("cancelled", self._service().allowed_transitions(shipment))
        self._preparer(reference)
        self.assertNotIn(
            "cancelled",
            self._service().allowed_transitions(self._shipment(reference)))

    # ─── R26 à R28 · la gate Freight reste l'autorité ────────────────

    def test_R26_un_dossier_incomplet_ne_passe_pas_a_ready(self):
        """La gate `_check_ready_requirements` n'est pas recopiée : elle agit."""
        reference = self._creer_dossier()
        shipment = self._preparer(reference)
        # Un poids réel absent est exactement ce que la gate refuse.
        shipment.package_ids.sudo().write({"unit_weight_kg": 0.0, "quantity": 1})
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "preparing", "ready")
        self.assertEqual(erreur.exception.code, "state_transition_blocked")
        self.assertEqual(erreur.exception.status, 409)
        self.assertEqual(self._shipment(reference).state, "preparing")

    def test_R27_une_gate_refusee_ne_journalise_rien(self):
        reference = self._creer_dossier()
        shipment = self._preparer(reference)
        shipment.package_ids.sudo().write({"unit_weight_kg": 0.0, "quantity": 1})
        avant = len(self._audits())
        with self.assertRaises(DallyOpsError):
            self._avancer(reference, "preparing", "ready")
        self.assertEqual(len(self._audits()), avant)

    def test_R28_une_gate_refusee_ne_projette_rien(self):
        reference = self._creer_dossier()
        shipment = self._preparer(reference)
        lignes_avant = self._outbox(shipment)
        tentatives = lignes_avant.attempt_count
        etat_avant = lignes_avant.state
        shipment.package_ids.sudo().write({"unit_weight_kg": 0.0, "quantity": 1})
        with self.assertRaises(DallyOpsError):
            self._avancer(reference, "preparing", "ready")
        lignes = self._outbox(shipment)
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes.attempt_count, tentatives)
        self.assertEqual(lignes.state, etat_avant)

    # ─── R29 à R31 · suivi client ────────────────────────────────────

    def test_R29_preparing_produit_un_evenement_de_suivi_unique(self):
        """Un seul événement — et il est publié au client.

        Mesuré, contre l'intuition : `dally_tracking` porte une table de
        formulations codée en dur où `preparing` est absent, mais
        `dally_freight_notifications` la **remplace** par la politique en
        données `dally.freight.state.policy`, où `preparing` a un libellé
        client, `visible_in_tracking` et `visible_in_portal`.

        Les deux transitions offertes au terrain sont donc visibles du client.
        Ce test fixe le fait ; c'est à la politique, pas au service Ops, de le
        changer si un jour on le décide.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        self._avancer(reference, "goods_received", "preparing")
        evenements = self._evenements_suivi(shipment, "preparing")
        self.assertEqual(len(evenements), 1)
        self.assertTrue(evenements.visible_to_customer)
        politique = self.env["dally.freight.state.policy"].sudo()._dally_policy_for(
            "preparing")
        self.assertTrue(politique.visible_in_tracking)

    def test_R30_ready_produit_un_evenement_visible_unique(self):
        reference = self._creer_dossier()
        shipment = self._preparer(reference)
        self._avancer(reference, "preparing", "ready")
        evenements = self._evenements_suivi(shipment, "ready")
        self.assertEqual(len(evenements), 1)
        self.assertTrue(evenements.visible_to_customer)

    def test_R31_le_service_ops_ne_cree_aucun_evenement_de_suivi(self):
        """Le crochet existant s'en charge ; en créer un second doublerait.

        On lit le code plutôt que de compter : un doublon ne se verrait qu'au
        moment où quelqu'un ajoute la ligne, et ce test-là doit tomber avant.
        """
        import ast
        import inspect
        from odoo.addons.dally_ops_mobile.models import ops_intake_state_service
        source = inspect.getsource(ops_intake_state_service)
        self.assertNotIn("dally.shipment.event", source)
        self.assertNotIn("visible_to_customer", source)
        ast.parse(source)

    # ─── R32 à R37 · contrat de sortie et validation ─────────────────

    def test_R32_laudit_conserve_lancien_et_le_nouvel_etat(self):
        reference = self._creer_dossier()
        identifiant = str(uuid.uuid4())
        self._avancer(reference, "goods_received", "preparing",
                      request_uuid=identifiant)
        evenement = self._audits().filtered(
            lambda enregistrement: enregistrement.request_uuid == identifiant)
        self.assertEqual(len(evenement), 1)
        self.assertEqual(evenement.changes_json, [{
            "field": "state",
            "old_value": "goods_received",
            "new_value": "preparing",
        }])
        self.assertEqual(evenement.shipment_id, self._shipment(reference))

    def test_R33_le_journal_restitue_le_geste_sans_identifiant_interne(self):
        reference = self._creer_dossier()
        self._avancer(reference, "goods_received", "preparing")
        journal = (self.env["dally.ops.activity.service"]
                   .with_user(self.gilles).with_company(self.societe)
                   .list_activity(limit=25))
        actions = [evenement["event"] for evenement in journal["events"]]
        self.assertIn("intake_state_advanced", actions)
        contenu = json.dumps(journal, ensure_ascii=False)
        for interdit in ("request_uuid", "shipment_id", "entity_res_id",
                         "partner_id", "sync_source_key"):
            self.assertNotIn(interdit, contenu)

    def test_R34_la_reponse_ne_contient_aucun_identifiant_sql(self):
        reference = self._creer_dossier()
        resultat = self._avancer(reference, "goods_received", "preparing")
        self.assertEqual(sorted(resultat), [
            "allowed_transitions", "reference", "state", "status"])
        contenu = json.dumps(resultat, ensure_ascii=False)
        for interdit in ("shipment_id", "partner_id", "sale_order_id",
                         "invoice_id", "sync_source_key", "external_line_key",
                         "request_uuid", "\"id\"", "ops:"):
            self.assertNotIn(interdit, contenu)

    def test_R35_un_champ_inconnu_est_refuse(self):
        reference = self._creer_dossier()
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "goods_received", "preparing", force=True)
        self.assertEqual(erreur.exception.code, "invalid_request")
        self.assertEqual(self._shipment(reference).state, "goods_received")

    def test_R36_une_cible_inconnue_est_refusee(self):
        reference = self._creer_dossier()
        for cible in ("delivered", "in_transit", "brouillon", "", None):
            with self.assertRaises(DallyOpsError) as erreur:
                self._avancer(reference, "goods_received", cible)
            self.assertIn(erreur.exception.code,
                          ("state_target_not_allowed", "invalid_request"))
        self.assertEqual(self._shipment(reference).state, "goods_received")

    def test_R37_un_identifiant_de_demande_invalide_est_refuse(self):
        reference = self._creer_dossier()
        for identifiant in ("", "   ", None, "pas-un-uuid", "x" * 200):
            with self.assertRaises(DallyOpsError) as erreur:
                self._avancer(reference, "goods_received", "preparing",
                              request_uuid=identifiant)
            self.assertEqual(erreur.exception.code, "invalid_request")
        self.assertEqual(self._shipment(reference).state, "goods_received")

    # ─── R38 · deux gestes concurrents ───────────────────────────────

    def test_R38_deux_identifiants_ne_gagnent_pas_tous_les_deux(self):
        """Deux opérateurs ayant lu le même état : un seul avance.

        Ce test épingle le contrat métier observable — le second reçoit
        `state_changed`, sans transition ni effet de bord. Il ne prouve pas le
        verrou de ligne lui-même : voir la limite documentée au rapport.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        premier = self._avancer(reference, "goods_received", "preparing",
                                request_uuid=str(uuid.uuid4()))
        self.assertEqual(premier["status"], "updated")

        audits_avant = len(self._audits())
        tentatives_avant = self._outbox(shipment).attempt_count
        with self.assertRaises(DallyOpsError) as erreur:
            self._avancer(reference, "goods_received", "preparing",
                          request_uuid=str(uuid.uuid4()))
        self.assertEqual(erreur.exception.code, "state_changed")
        self.assertEqual(len(self._audits()), audits_avant)
        self.assertEqual(self._outbox(shipment).attempt_count, tentatives_avant)
        self.assertEqual(self._shipment(reference).state, "preparing")

    def test_R39_le_verrou_precede_la_relecture_de_letat(self):
        """L'ordre est la garantie, et il se mesure.

        Le verrou par identifiant de demande ne protège que d'un rejeu ; deux
        opérateurs portent deux identifiants distincts. C'est la ligne du
        dossier qu'il faut prendre — et **avant** d'en relire l'état, sinon
        deux gestes concurrents passent tous deux le contrôle.

        On remplace la primitive de verrouillage par une sentinelle : si elle
        est atteinte, c'est qu'elle précède la comparaison. Retirer le verrou
        ferait remonter `state_changed` à la place, et ce test tomberait.
        """
        reference = self._creer_dossier()
        self._preparer(reference)  # l'état réel n'est plus `goods_received`

        sentinelle = RuntimeError("verrou de dossier atteint")
        Service = type(self.env["dally.ops.intake.state.service"])
        with patch.object(Service, "_verrouiller_dossier",
                          side_effect=sentinelle):
            with self.assertRaises(RuntimeError) as leve:
                self._avancer(reference, "goods_received", "preparing")
        self.assertIs(leve.exception, sentinelle)

    def test_R40_le_verrou_de_dossier_est_bien_un_select_for_update(self):
        """La sentinelle prouve l'ordre ; elle ne prouve pas la primitive.

        R38 mesure qu'un seul des deux gestes concurrents gagne, R39 que le
        verrou précède la relecture. Mais tous deux remplacent ou entourent la
        méthode : ni l'un ni l'autre ne verrait quelqu'un vider son corps de la
        clause qui la rend bloquante. Un `SELECT id` sans `FOR UPDATE`
        s'exécute, ne verrouille rien, et laisse passer les deux opérateurs.

        On épingle donc la primitive elle-même, à même le source, en tolérant
        les espaces et la casse — pas la mise en forme du jour.
        """
        import inspect
        import re

        service = type(self.env["dally.ops.intake.state.service"])
        source = inspect.getsource(service._verrouiller_dossier)
        normalise = re.sub(r"\s+", " ", source).upper()

        self.assertIn("FOR UPDATE", normalise,
                      "le verrou de dossier ne verrouille plus rien")
        self.assertIn("FROM DALLY_SHIPMENT", normalise)
        # La clause doit porter sur la ligne du dossier, pas traîner ailleurs.
        self.assertLess(normalise.index("FROM DALLY_SHIPMENT"),
                        normalise.index("FOR UPDATE"))

    # ─── Le détail du dossier publie ce que le serveur autorise ──────

    def test_le_detail_publie_les_transitions_autorisees(self):
        reference = self._creer_dossier()
        detail = (self.env["dally.ops.intake.line.service"]
                  .with_user(self.gilles).with_company(self.societe)
                  .get_intake(reference))["intake"]
        self.assertEqual(detail["allowed_transitions"], ["preparing"])
        self._preparer(reference)
        detail = (self.env["dally.ops.intake.line.service"]
                  .with_user(self.gilles).with_company(self.societe)
                  .get_intake(reference))["intake"]
        self.assertEqual(detail["allowed_transitions"], ["ready"])

    def test_la_matrice_freight_nest_pas_recopiee_dans_ops(self):
        """Ops propose un sous-ensemble ; il ne tient pas une seconde matrice."""
        import inspect
        from odoo.addons.dally_ops_mobile.models import ops_intake_state_service
        source = inspect.getsource(ops_intake_state_service)
        self.assertIn("ALLOWED_STATE_TRANSITIONS", source)
        for interdit in ("_STATE_BYPASS_TOKEN", "_OPERATIONAL_SYNC_TOKEN",
                         "_write_state_from_operational_source",
                         "_write_historical_state"):
            self.assertNotIn(interdit, source)
        # Aucune liste d'états recopiée : les cibles Ops sont deux, et deux
        # seulement.
        self.assertIn('OPS_STATE_TARGETS = ("preparing", "ready")', source)
