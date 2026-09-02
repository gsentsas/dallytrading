# -*- coding: utf-8 -*-
"""Charger un départ depuis le quai, sans rien décider d'autre.

## Ce que ces tests protègent

**La frontière.** Un geste de chargement touche une seule table métier :
`dally.freight.consolidation.line`. Ni l'état du dossier, ni le colis, ni le
client, ni les paiements. Les tests d'immobilité sont les plus importants du
fichier : ils disent ce que Dally Ops **n'est pas** devenu.

**Le colis entier.** L'écran ne propose jamais une quantité au clavier. Une
ligne partielle héritée reste affichée et peut être complétée ; elle ne peut
pas être créée.

**L'identité opaque.** Un colis est désigné par `ops_loading_uuid`, jamais par
son identifiant de base. Connaître un identifiant ne doit pas suffire : le
colis doit aussi être attendu sur ce départ.

**Le rejeu.** Le même `request_uuid` rejoué ne charge pas deux fois ; le même
identifiant réutilisé pour une autre intention est refusé.
"""

import importlib.util
import inspect
import textwrap
import json
import uuid
from pathlib import Path

from unittest.mock import patch

from odoo.exceptions import ConcurrencyError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.dally_freight_consolidation.models.consolidation import (
    _CONSOLIDATION_BYPASS_TOKEN,
    _CONSOLIDATION_STATE_WRITE_TOKEN,
)
from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError
from odoo.addons.dally_ops_mobile.models.ops_activity_service import (
    EVENEMENTS_PUBLICS,
)
from odoo.addons.dally_ops_mobile.models.ops_loading_service import (
    ACTION_AUDIT_CHARGE,
    ACTION_AUDIT_RETIRE,
    ETATS_VISIBLES,
    STATUT_BLOQUE,
    STATUT_CHARGE,
    STATUT_NON_CHARGE,
    STATUT_PARTIEL,
)


@tagged("post_install", "-at_install", "dally")
class TestOpsLoading(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.societe = cls.env.company
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Load Autre"})

        cls.gilles = cls._compte(
            "load.gilles", "dally_ops_mobile.group_dally_ops_logistician")
        cls.responsable = cls._compte(
            "load.resp", "dally_ops_mobile.group_dally_ops_supervisor")
        cls.temoin = cls._compte("load.temoin", "base.group_user")

        Famille = cls.env["dally.freight.tariff.family"]
        Regle = cls.env["dally.freight.tariff.rule"]
        cls.famille = Famille.search([("code", "=", "non_food")], limit=1)
        if not cls.famille:
            cls.famille = Famille.create(
                {"name": "Load Non alimentaire", "code": "non_food"})
        if not Regle.search([("family_id", "=", cls.famille.id),
                             ("transport_mode", "=", "air")], limit=1):
            Regle.create({
                "name": "Load non_food air", "transport_mode": "air",
                "family_id": cls.famille.id, "customer_segment": "all",
                "price_per_kg_eur": 5.0,
            })

        cls.partner = cls.env["res.partner"].create({
            "name": "Fatou Chargement", "company_id": cls.societe.id,
            "phone": "+221770000071", "email": "fatou.load@example.test",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.depart = cls._consolidation("AIR-DSS-CDG-LOAD-001")

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
    def _consolidation(cls, reference, societe=None, etat="collecting"):
        depart = cls.env["dally.freight.consolidation"].create({
            "name": reference, "state": "collecting", "active": True,
            "company_id": (societe or cls.env.company).id,
            "transport_mode": "air", "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })
        if etat == "collection_closed":
            depart.sudo().action_close_collection()
        elif etat != "collecting":
            raise ValueError("État de fabrique non géré : %s" % etat)
        return depart

    def _creer_dossier(self, consolidation=None, poids=13.5):
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
                            "exact_weight_kg": poids, "length_cm": None,
                            "width_cm": None, "height_cm": None,
                            "billing_method": "real",
                            "tariff_family_code": self.famille.code,
                            "customs_value_xof": 25000,
                        },
                    }))
        return resultat["intake"]["reference"]

    def _shipment(self, reference):
        return self.env["dally.shipment"].sudo().search(
            [("external_reference", "=", reference)], limit=1)

    def _colis_de(self, reference):
        return self._shipment(reference).package_ids.sorted("sequence")

    def _service(self, utilisateur=None, societe=None):
        return (self.env["dally.ops.loading.service"]
                .with_user(utilisateur or self.gilles)
                .with_company(societe or self.societe))

    _ABSENT = object()

    def _appliquer(self, action, paquet, depart=None, request_uuid=_ABSENT,
                   utilisateur=None, **extra):
        charge = {
            "request_uuid": (str(uuid.uuid4())
                             if request_uuid is self._ABSENT else request_uuid),
            "action": action,
            # Un enregistrement donne son identité ; tout le reste — chaîne,
            # entier, liste — passe tel quel, pour pouvoir éprouver ce que le
            # service fait d'une référence qui n'est pas du texte.
            "package_reference": (paquet.ops_loading_uuid
                                  if hasattr(paquet, "ops_loading_uuid")
                                  else paquet),
        }
        charge.update(extra)
        return self._service(utilisateur).apply_loading(
            (depart or self.depart).name, charge)

    def _detail(self, depart=None, utilisateur=None):
        return self._service(utilisateur).get_loading(
            (depart or self.depart).name)["loading"]

    def _colis_dto(self, detail, paquet):
        for dossier in detail["shipments"]:
            for item in dossier["packages"]:
                if item["reference"] == paquet.ops_loading_uuid:
                    return item
        return None

    def _decharger(self, reference, depart=None):
        """Remet le colis dans l'état « pas encore chargé ».

        La réception native attache déjà le colis à son départ prévu — c'est
        `_add_available_packages_to_consolidation`, côté Freight. Pour
        éprouver le geste de chargement, il faut donc d'abord défaire ce que
        la réception a fait, et le faire **sans** passer par le service, pour
        que le test du chargement ne s'appuie pas sur celui du retrait.
        """
        paquet = self._colis_de(reference)
        self._lignes(depart).filtered(
            lambda ligne: ligne.package_id == paquet).unlink()
        return paquet

    def _lignes(self, depart=None):
        return self.env["dally.freight.consolidation.line"].sudo().search(
            [("consolidation_id", "=", (depart or self.depart).id)])

    def _audits(self, action):
        return self.env["dally.ops.audit.event"].sudo().search([
            ("company_id", "=", self.societe.id), ("action", "=", action)])

    # ─── Rôle et portée ──────────────────────────────────────────────

    def test_sans_role_ops_tout_est_refuse(self):
        for appel in (
            lambda: self._service(self.temoin).list_consolidations(),
            lambda: self._service(self.temoin).get_loading(self.depart.name),
            lambda: self._appliquer("load", "peu-importe", utilisateur=self.temoin),
        ):
            with self.assertRaises(DallyOpsError) as capture:
                appel()
            self.assertEqual(capture.exception.code, "ops_forbidden")
            self.assertEqual(capture.exception.status, 403)

    def test_les_deux_roles_ops_sont_admis(self):
        for utilisateur in (self.gilles, self.responsable):
            self.assertIn(
                "consolidations",
                self._service(utilisateur).list_consolidations())

    def test_un_depart_d_une_autre_societe_est_introuvable(self):
        etranger = self._consolidation("AIR-DSS-CDG-LOAD-ETR", self.autre_societe)
        with self.assertRaises(DallyOpsError) as capture:
            self._service().get_loading(etranger.name)
        self.assertEqual(capture.exception.code, "consolidation_not_found")
        self.assertEqual(capture.exception.status, 404)

    def test_un_colis_hors_du_depart_est_introuvable(self):
        autre = self._consolidation("AIR-DSS-CDG-LOAD-002")
        reference = self._creer_dossier(autre)
        paquet = self._colis_de(reference)
        with self.assertRaises(DallyOpsError) as capture:
            self._appliquer("load", paquet)
        self.assertEqual(capture.exception.code, "package_not_found")

    def test_une_identite_inconnue_est_introuvable(self):
        for identite in ("", "   ", str(uuid.uuid4())):
            with self.assertRaises(DallyOpsError) as capture:
                self._appliquer("load", identite)
            self.assertEqual(capture.exception.code, "package_not_found")

    # ─── Ce que le quai voit ─────────────────────────────────────────

    def test_la_liste_montre_les_trois_etats_regardables(self):
        ouvert = self._consolidation("AIR-DSS-CDG-LOAD-V-OUV")
        ferme = self._consolidation("AIR-DSS-CDG-LOAD-V-FER",
                                    etat="collection_closed")
        prete = self._consolidation("AIR-DSS-CDG-LOAD-V-PRT")
        self._creer_dossier(prete)
        prete.sudo().action_close_collection()
        prete.sudo().action_mark_ready()
        # Le départ réel passe par la porte de sortie de Freight, qui exige un
        # dossier soldé : hors sujet ici. On pose l'état par le jeton prévu,
        # comme le fait la suite de workflow du cœur.
        partie = self._consolidation("AIR-DSS-CDG-LOAD-V-PAR")
        self._creer_dossier(partie)
        partie.sudo().action_close_collection()
        partie.sudo().action_mark_ready()
        partie.sudo().with_context(
            _dally_consolidation_state_write=_CONSOLIDATION_STATE_WRITE_TOKEN,
            _dally_consolidation_bypass=_CONSOLIDATION_BYPASS_TOKEN,
        ).write({"state": "departed"})

        references = {item["reference"] for item
                      in self._service().list_consolidations()["consolidations"]}
        self.assertEqual({depart.state for depart in (ouvert, ferme, prete)},
                         set(ETATS_VISIBLES))
        for depart in (ouvert, ferme, prete):
            self.assertIn(depart.name, references)
        # Un départ parti ne se prépare plus, et ne se constate plus ici.
        self.assertNotIn(partie.name, references)

    def test_un_depart_archive_disparait(self):
        archive = self._consolidation("AIR-DSS-CDG-LOAD-ARCH")
        archive.sudo().write({"active": False})
        references = {item["reference"] for item
                      in self._service().list_consolidations()["consolidations"]}
        self.assertNotIn(archive.name, references)

    def test_can_load_ne_vaut_que_pour_la_collecte_ouverte(self):
        self.assertTrue(self._detail()["can_load"])
        ferme = self._consolidation("AIR-DSS-CDG-LOAD-FERME", etat="collection_closed")
        self.assertFalse(self._detail(ferme)["can_load"])

    def test_le_resume_compte_et_ne_calcule_aucun_pourcentage(self):
        self._decharger(self._creer_dossier())
        resume = self._detail()["summary"]
        self.assertEqual(resume["shipments_expected"], 1)
        self.assertEqual(resume["packages_expected"], 1)
        self.assertEqual(resume["packages_loaded"], 0)
        self.assertEqual(resume["packages_remaining"], 1)
        for cle in resume:
            self.assertNotIn("percent", cle)
            self.assertNotIn("ratio", cle)
            self.assertNotIn("rate", cle)

    def test_une_reception_native_arrive_deja_chargee(self):
        """Le fait le plus important du fichier.

        Recevoir un colis l'attache immédiatement à son départ prévu : c'est
        Freight qui le fait, à la réception, sans que Dally Ops le demande.
        L'écran de chargement ne sert donc pas à *charger* un dossier natif —
        il sert à **constater** ce qui est là, et à corriger les deux
        exceptions : un colis absent qu'il faut retirer, un colis replanifié
        qu'il faut rattacher.
        """
        reference = self._creer_dossier()
        paquet = self._colis_de(reference)
        detail = self._detail()

        self.assertEqual([d["reference"] for d in detail["shipments"]], [reference])
        self.assertTrue(detail["shipments"][0]["complete"])
        self.assertEqual(self._colis_dto(detail, paquet)["status"], STATUT_CHARGE)
        self.assertEqual(detail["summary"]["packages_loaded"], 1)
        self.assertEqual(detail["summary"]["packages_remaining"], 0)

    def test_charger_un_colis_deja_charge_ne_cree_pas_de_seconde_ligne(self):
        reference = self._creer_dossier()
        paquet = self._colis_de(reference)
        self._appliquer("load", paquet)
        lignes = self._lignes()
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes.quantity_loaded, paquet.quantity)

    def test_un_dossier_attendu_mais_non_charge_reste_liste(self):
        reference = self._creer_dossier()
        self._decharger(reference)
        detail = self._detail()
        self.assertEqual([d["reference"] for d in detail["shipments"]], [reference])
        self.assertFalse(detail["shipments"][0]["complete"])
        self.assertEqual(detail["summary"]["packages_remaining"], 1)

    def test_le_dto_du_colis_ne_porte_aucun_identifiant_technique(self):
        reference = self._creer_dossier()
        item = self._colis_dto(self._detail(), self._colis_de(reference))
        self.assertNotIn("id", item)
        self.assertNotIn("package_id", item)
        self.assertNotIn("shipment_id", item)
        self.assertEqual(item["reference"],
                         self._colis_de(reference).ops_loading_uuid)

    # ─── Charger et retirer ──────────────────────────────────────────

    def test_charger_cree_une_ligne_a_la_quantite_entiere(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        self._appliquer("load", paquet)

        ligne = self._lignes()
        self.assertEqual(len(ligne), 1)
        self.assertEqual(ligne.package_id, paquet)
        self.assertEqual(ligne.quantity_loaded, paquet.quantity)
        self.assertAlmostEqual(
            ligne.weight_loaded, paquet.unit_weight_kg * paquet.quantity, 3)

    def test_charger_fait_passer_le_colis_a_charge(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        self.assertEqual(self._colis_dto(self._detail(), paquet)["status"],
                         STATUT_NON_CHARGE)
        self._appliquer("load", paquet)

        item = self._colis_dto(self._detail(), paquet)
        self.assertEqual(item["status"], STATUT_CHARGE)
        self.assertEqual(item["loaded_quantity"], paquet.quantity)
        self.assertEqual(item["remaining_quantity"], 0)
        self.assertFalse(item["can_load"])
        self.assertTrue(item["can_unload"])
        self.assertIsNone(item["blocker"])

    def test_un_dossier_dont_tout_est_charge_devient_complet(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        self.assertFalse(self._detail()["shipments"][0]["complete"])
        self._appliquer("load", paquet)
        detail = self._detail()
        self.assertTrue(detail["shipments"][0]["complete"])
        self.assertEqual(detail["summary"]["shipments_complete"], 1)

    def test_retirer_supprime_la_ligne(self):
        reference = self._creer_dossier()
        paquet = self._colis_de(reference)
        self._appliquer("load", paquet)
        self._appliquer("unload", paquet)

        self.assertFalse(self._lignes())
        item = self._colis_dto(self._detail(), paquet)
        self.assertEqual(item["status"], STATUT_NON_CHARGE)
        self.assertTrue(item["can_load"])
        self.assertFalse(item["can_unload"])

    def test_retirer_un_colis_absent_est_sans_effet(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        resultat = self._appliquer("unload", paquet)
        self.assertFalse(resultat["replayed"])
        self.assertFalse(self._lignes())

    def test_une_ligne_partielle_heritee_se_complete_sans_en_creer_une_seconde(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        paquet.sudo().write({"quantity": 3})
        self.env["dally.freight.consolidation.line"].sudo().create({
            "consolidation_id": self.depart.id,
            "package_id": paquet.id,
            "quantity_loaded": 1,
        })
        self.assertEqual(
            self._colis_dto(self._detail(), paquet)["status"], STATUT_PARTIEL)

        self._appliquer("load", paquet)
        lignes = self._lignes()
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes.quantity_loaded, 3)
        self.assertEqual(
            self._colis_dto(self._detail(), paquet)["status"], STATUT_CHARGE)

    # ─── Les verrous ─────────────────────────────────────────────────

    def _requetes_de(self, appel):
        """Les ordres SQL émis par un appel, avec leurs paramètres.

        Les paramètres comptent autant que le texte : c'est là que vivent les
        clés de verrou, et donc ce qui distingue deux gestes de deux départs.
        """
        requetes = []
        original = type(self.env.cr).execute

        def espion(cr, requete, params=None, *args, **kwargs):
            requetes.append((requete, params))
            return original(cr, requete, params, *args, **kwargs)

        with patch.object(type(self.env.cr), "execute", espion):
            appel()
        return requetes

    def _cles_de_verrou(self, request_uuid, reference):
        """Les deux clés réellement passées à PostgreSQL."""
        requetes = self._requetes_de(
            lambda: self._service()._verrouiller_avant_instantane(
                request_uuid, reference))
        for texte, params in requetes:
            if "advisory" in texte:
                return list(params)
        self.fail("aucun ordre de verrou émis")

    def test_les_deux_verrous_tiennent_dans_un_seul_ordre_sql(self):
        """Un seul ordre, parce que le premier fige l'instantané.

        Sous `REPEATABLE READ`, deux `SELECT` successifs ne suffiraient pas :
        le premier figerait déjà l'instantané, et le second arriverait trop
        tard pour protéger quoi que ce soit.
        """
        requetes = self._requetes_de(
            lambda: self._service()._verrouiller_avant_instantane(
                str(uuid.uuid4()), self.depart.name))
        verrous = [t for t, _ in requetes if "advisory" in t]
        self.assertEqual(len(verrous), 1, requetes)
        self.assertEqual(verrous[0].count("pg_try_advisory_xact_lock"), 2)

    def test_le_verrou_n_attend_jamais(self):
        """Attendre rendrait la main sur un instantané périmé.

        C'est exactement le défaut qu'on vient de fermer : la transaction qui
        attend obtient son verrou après le commit de l'autre, mais lit encore
        l'état d'avant.
        """
        requetes = self._requetes_de(
            lambda: self._service()._verrouiller_avant_instantane(
                str(uuid.uuid4()), self.depart.name))
        for texte, _ in requetes:
            if "advisory" in texte:
                self.assertIn("pg_try_advisory_xact_lock", texte)

    def test_une_cle_tenue_leve_l_erreur_que_le_cadre_rejoue(self):
        """`ConcurrencyError`, que l'une ou l'autre clé manque.

        C'est l'erreur que `service.model.retrying` sait rejouer : il relance
        la requête entière sur une transaction neuve, dont l'instantané voit
        enfin l'état à jour.
        """
        # `create=True` : le curseur d'Odoo délègue `fetchone` par
        # `__getattr__`, il n'a donc pas l'attribut en propre.
        for reponse in ((False, True), (True, False), (False, False)):
            with patch.object(type(self.env.cr), "fetchone",
                              return_value=reponse, create=True):
                with self.assertRaises(ConcurrencyError, msg=reponse):
                    self._service()._verrouiller_avant_instantane(
                        str(uuid.uuid4()), self.depart.name)

    def test_deux_departs_partagent_la_cle_du_geste_mais_pas_celle_du_depart(self):
        """Cas B : même `request_uuid`, deux départs.

        Le geste reste sérialisé par son identifiant — c'est l'idempotence —
        mais deux départs distincts ne se bloquent pas l'un l'autre.
        """
        autre = self._consolidation("AIR-DSS-CDG-LOAD-CLE-B")
        identifiant = str(uuid.uuid4())
        ici = self._cles_de_verrou(identifiant, self.depart.name)
        ailleurs = self._cles_de_verrou(identifiant, autre.name)

        self.assertEqual(ici[0], ailleurs[0], "la clé du geste doit être la même")
        self.assertNotEqual(ici[1], ailleurs[1], "les départs ne doivent pas se bloquer")
        self.assertIn("ops-loading-request:", ici[0])
        self.assertIn("ops-loading-departure:", ici[1])
        self.assertIn(self.depart.name, ici[1])

    def test_deux_gestes_differents_partagent_la_cle_du_depart(self):
        """Cas C : deux `request_uuid`, un seul départ.

        C'est la clé qui manquait. Sans elle, un `unload` et un `load`
        concurrents ne se sérialisaient pas, et le second répondait sur un
        instantané périmé — reproduit avant correction.
        """
        premier = self._cles_de_verrou(str(uuid.uuid4()), self.depart.name)
        second = self._cles_de_verrou(str(uuid.uuid4()), self.depart.name)

        self.assertNotEqual(premier[0], second[0], "deux gestes, deux clés")
        self.assertEqual(premier[1], second[1], "un seul départ, une seule clé")

    def test_la_cle_du_depart_se_construit_sans_lecture_metier(self):
        """Elle ne doit dépendre que de la société et de la référence.

        Résoudre le départ pour bâtir la clé reviendrait à lire avant de
        verrouiller — donc à figer l'instantané trop tôt.
        """
        cles = self._cles_de_verrou(str(uuid.uuid4()), "  AIR-DSS-CDG-INEXISTANT  ")
        self.assertIn("AIR-DSS-CDG-INEXISTANT", cles[1])
        self.assertNotIn("  ", cles[1])
        # une référence non textuelle ne fait pas tomber la construction
        self.assertIn("invalid", self._cles_de_verrou(str(uuid.uuid4()), 42)[1])

    def test_aucune_lecture_orm_ne_precede_le_verrou(self):
        """L'invariant décisif, mesuré sur les deux contextes.

        Le verrou doit être le premier ordre SQL qui fige l'instantané. Un
        `SELECT` métier avant lui — `res_company` quand le contexte porte les
        sociétés, `res_users` quand il n'en porte pas — rouvrirait la fenêtre
        que ce verrou existe pour fermer. `SAVEPOINT` ne compte pas : c'est du
        contrôle de transaction, il n'acquiert aucun instantané.

        Le cas sans `allowed_company_ids` est le plus traître : il ne survient
        qu'en dehors de la passerelle HTTP, donc jamais dans les parcours
        courants, et passerait inaperçu sans ce test.
        """
        for contexte, libelle in (({"allowed_company_ids": [self.societe.id]}, "normal"),
                                  ({}, "sans allowed_company_ids")):
            service = (self.env["dally.ops.loading.service"]
                       .with_user(self.gilles).with_context(**contexte))
            requetes = []
            original = type(self.env.cr).execute

            def espion(cr, requete, params=None, *args, **kwargs):
                requetes.append(" ".join(str(requete).split()))
                return original(cr, requete, params, *args, **kwargs)

            with patch.object(type(self.env.cr), "execute", espion):
                service._verrouiller_avant_instantane(
                    str(uuid.uuid4()), self.depart.name)

            rang = next(i for i, r in enumerate(requetes)
                        if "pg_try_advisory_xact_lock" in r)
            avant = [r for r in requetes[:rang]
                     if not r.upper().startswith(("SAVEPOINT", "RELEASE", "ROLLBACK"))]
            self.assertEqual(avant, [], "%s : SQL avant le verrou" % libelle)

    def test_le_contexte_sans_societe_ne_leve_rien_et_ne_lit_rien(self):
        """Une sentinelle, pas une société.

        Deux appels sans contexte se gênent alors mutuellement — sans
        conséquence, ils sont exceptionnels — là où une fenêtre d'instantané
        périmé, elle, ne pardonnerait pas. Ce n'est **pas** une garantie
        d'isolation : celle-ci reste vérifiée après le verrou, par les
        recherches métier bornées sur `company_id`.
        """
        service = (self.env["dally.ops.loading.service"]
                   .with_user(self.gilles).with_context())
        sans = service.with_context(allowed_company_ids=None)
        self.assertEqual(sans._societe_pour_verrou(),
                         sans.SOCIETE_INCONNUE)
        avec = service.with_context(allowed_company_ids=[self.societe.id])
        self.assertEqual(avec._societe_pour_verrou(), self.societe.id)
        # et la clé se construit sans lever
        sans._verrouiller_avant_instantane(str(uuid.uuid4()), self.depart.name)

    def test_le_role_et_la_societe_sont_verifies_apres_le_verrou(self):
        """L'ordre, encore : verrou, puis rôle, puis résolution métier."""
        source = inspect.getsource(
            type(self.env["dally.ops.loading.service"]).apply_loading)
        corps = source[source.index("with self.env.cr.savepoint():"):]
        pose = corps.index("_verrouiller_avant_instantane")
        for suivant in ("_exiger_role_ops", "_valider", "_resoudre_depart"):
            self.assertLess(pose, corps.index(suivant), suivant)
        # La clé de verrou ne doit pas passer par l'ORM. On lit le code seul :
        # la docstring, elle, *nomme* `self.env.company` pour expliquer
        # précisément pourquoi elle ne l'appelle pas.
        import ast
        source = inspect.getsource(
            type(self.env["dally.ops.loading.service"])._societe_pour_verrou)
        arbre = ast.parse(textwrap.dedent(source))
        fonction = arbre.body[0]
        if (fonction.body and isinstance(fonction.body[0], ast.Expr)
                and isinstance(fonction.body[0].value, ast.Constant)):
            fonction.body = fonction.body[1:]          # on retire la docstring
        code = ast.unparse(fonction)
        for interdit in ("self.env.company", "search", "browse", "sudo"):
            self.assertNotIn(interdit, code, interdit)
        self.assertIn("allowed_company_ids", code)

    def test_le_verrou_de_ligne_du_depart_est_sans_attente(self):
        """Cas F : la contention du verrou de ligne ne doit pas attendre.

        `NOWAIT` refuse immédiatement plutôt que de rendre la main sur un
        instantané périmé.
        """
        requetes = self._requetes_de(
            lambda: self._service()._verrouiller_depart(self.depart))
        verrous = [t for t, _ in requetes if "FOR UPDATE" in t]
        self.assertEqual(len(verrous), 1)
        self.assertIn("FOR UPDATE NOWAIT", verrous[0])
        self.assertIn("dally_freight_consolidation", verrous[0])
        self.assertFalse([t for t, _ in requetes if "advisory" in t])

    def test_le_cadre_rejoue_deja_les_erreurs_de_contention(self):
        """Vérifié dans cet environnement, pas supposé.

        `LockNotAvailable` (55P03) et `SerializationFailure` (40001) figurent
        déjà dans la liste qu'Odoo rejoue : aucune conversion n'est donc
        nécessaire pour le verrou de ligne.
        """
        from psycopg2 import errors as erreurs_pg
        from odoo.service.model import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY
        self.assertIn(erreurs_pg.LockNotAvailable, PG_CONCURRENCY_EXCEPTIONS_TO_RETRY)
        self.assertIn(erreurs_pg.SerializationFailure, PG_CONCURRENCY_EXCEPTIONS_TO_RETRY)

    def test_les_verrous_precedent_toute_lecture_metier(self):
        """L'ordre est l'invariant : les verrous, puis le reste."""
        source = inspect.getsource(
            type(self.env["dally.ops.loading.service"]).apply_loading)
        corps = source[source.index("with self.env.cr.savepoint():"):]
        pose = corps.index("_verrouiller_avant_instantane")
        for suivant in ("_exiger_role_ops", "_valider", "_resoudre_depart"):
            self.assertLess(pose, corps.index(suivant), suivant)

    def test_la_cle_de_verrou_normalise_comme_la_validation(self):
        """Un identifiant entouré d'espaces reste le même geste.

        `_uuid` rogne avant d'analyser : « <uuid> » espacé valide donc vers sa
        forme canonique. Si la clé de verrou ne rognait pas, elle tomberait sur
        « invalid » pendant que le même identifiant sans espaces prendrait la
        sienne — les deux gestes échapperaient à la sérialisation, et le second
        heurterait la contrainte d'unicité du registre au lieu de se
        reconnaître comme un rejeu.
        """
        service = self._service()
        identifiant = str(uuid.uuid4())
        canonique = service._request_uuid_pour_verrou({"request_uuid": identifiant})
        self.assertEqual(canonique, identifiant)
        for espace in (" %s", "%s ", "  %s\n", "\t%s\t"):
            self.assertEqual(
                service._request_uuid_pour_verrou({"request_uuid": espace % identifiant}),
                canonique, espace)
        # Ce qui n'est pas un identifiant partage une clé unique et inoffensive.
        for mauvais in ({"request_uuid": "pas-un-uuid"}, {"request_uuid": 42}, {}):
            self.assertEqual(service._request_uuid_pour_verrou(mauvais), "invalid")

    def test_une_reference_de_colis_non_textuelle_est_refusee_proprement(self):
        """Un type inattendu doit refuser, pas planter.

        `(42 or "").strip()` lève une `AttributeError` : le contrôleur ne
        l'attrape pas, et la route rendrait 500 là où le contrat promet un
        refus. La valeur traverse donc `_valider` sans coercition, et
        `_resoudre_colis` — qui sait déjà refuser ce qui n'est pas du texte —
        rend « colis introuvable ».
        """
        reference = self._creer_dossier()
        self._decharger(reference)
        for valeur in (42, True, [], {}, None, 3.5):
            with self.assertRaises(DallyOpsError) as capture:
                self._appliquer("load", valeur)
            self.assertEqual(capture.exception.code, "package_not_found", valeur)
            self.assertEqual(capture.exception.status, 404, valeur)
        self.assertFalse(self._lignes())

    def test_le_verrou_du_depart_porte_sur_la_ligne_reelle(self):
        """Un verrou consultatif ne voyait pas la clôture back-office.

        Celle-ci prend `consolidation:<préfixe>`, pas nos clés : il n'y avait
        aucune contention. Et sous `REPEATABLE READ`, relire `state` après
        `invalidate_recordset` reste sur l'instantané. `FOR UPDATE` porte sur
        la ligne que la clôture modifie : si elle a changé depuis notre
        instantané, PostgreSQL lève une erreur de sérialisation, et
        `retrying` rejoue sur une transaction neuve.
        """
        requetes = []
        original = type(self.env.cr).execute

        def espion(cr, requete, params=None, *args, **kwargs):
            requetes.append(requete)
            return original(cr, requete, params, *args, **kwargs)

        with patch.object(type(self.env.cr), "execute", espion):
            self._service()._verrouiller_depart(self.depart)

        verrous = [r for r in requetes if "FOR UPDATE" in r]
        self.assertEqual(len(verrous), 1)
        self.assertIn("dally_freight_consolidation", verrous[0])
        self.assertFalse([r for r in requetes if "advisory" in r],
                         "le verrou du départ ne doit plus être consultatif")

    def test_la_creation_et_la_correction_calculent_les_memes_mesures(self):
        """Une seule formule, deux chemins.

        `create` l'appliquait dans le modèle, `write` la redisait dans le
        service : deux endroits pour une même règle. Les deux passent
        désormais par `_mesures_chargees`, et ce test compare leurs sorties à
        cette source unique.
        """
        Ligne = self.env["dally.freight.consolidation.line"].sudo()
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        paquet.sudo().write({"quantity": 4})
        attendu = Ligne._mesures_chargees(paquet, 4)

        # chemin `create`, par le service
        self._appliquer("load", paquet)
        ligne = self._lignes()
        self.assertEqual(len(ligne), 1)
        self.assertAlmostEqual(ligne.weight_loaded, attendu["weight_loaded"], 3)
        self.assertAlmostEqual(ligne.volume_loaded, attendu["volume_loaded"], 4)

        # chemin `write` : on redescend la ligne, puis on la complète
        ligne.write({"quantity_loaded": 1,
                     **Ligne._mesures_chargees(paquet, 1)})
        self._appliquer("load", paquet)
        ligne.invalidate_recordset()
        self.assertEqual(ligne.quantity_loaded, 4)
        self.assertAlmostEqual(ligne.weight_loaded, attendu["weight_loaded"], 3)
        self.assertAlmostEqual(ligne.volume_loaded, attendu["volume_loaded"], 4)

    # ─── Idempotence ─────────────────────────────────────────────────

    def test_le_meme_geste_rejoue_ne_charge_pas_deux_fois(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        identifiant = str(uuid.uuid4())

        premier = self._appliquer("load", paquet, request_uuid=identifiant)
        second = self._appliquer("load", paquet, request_uuid=identifiant)

        self.assertFalse(premier["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(len(self._lignes()), 1)
        self.assertEqual(self.env["dally.ops.loading.request"].sudo().search_count(
            [("request_uuid", "=", identifiant)]), 1)

    def test_le_meme_identifiant_pour_une_autre_intention_est_refuse(self):
        reference = self._creer_dossier()
        paquet = self._colis_de(reference)
        identifiant = str(uuid.uuid4())
        self._appliquer("load", paquet, request_uuid=identifiant)

        with self.assertRaises(DallyOpsError) as capture:
            self._appliquer("unload", paquet, request_uuid=identifiant)
        self.assertEqual(capture.exception.code, "loading_request_conflict")
        self.assertEqual(capture.exception.status, 409)
        self.assertEqual(len(self._lignes()), 1)

    def test_un_rejeu_n_ecrit_aucun_second_audit(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        identifiant = str(uuid.uuid4())
        self._appliquer("load", paquet, request_uuid=identifiant)
        avant = len(self._audits(ACTION_AUDIT_CHARGE))
        self._appliquer("load", paquet, request_uuid=identifiant)
        self.assertEqual(len(self._audits(ACTION_AUDIT_CHARGE)), avant)

    # ─── États du départ ─────────────────────────────────────────────

    def test_charger_hors_collecte_ouverte_est_refuse(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        self.depart.sudo().action_close_collection()

        with self.assertRaises(DallyOpsError) as capture:
            self._appliquer("load", paquet)
        self.assertEqual(capture.exception.code, "consolidation_not_collecting")
        self.assertEqual(capture.exception.status, 409)
        self.assertFalse(self._lignes())

    def test_la_lecture_reste_possible_apres_la_cloture(self):
        reference = self._creer_dossier()
        self.depart.sudo().action_close_collection()

        detail = self._detail()
        self.assertFalse(detail["can_load"])
        item = self._colis_dto(detail, self._colis_de(reference))
        self.assertEqual(item["status"], STATUT_CHARGE)
        self.assertFalse(item["can_load"])
        self.assertFalse(item["can_unload"])

    # ─── Conflits métier ─────────────────────────────────────────────

    def test_un_colis_charge_ailleurs_est_bloque(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        ailleurs = self._consolidation("AIR-DSS-CDG-LOAD-AILLEURS")
        self.env["dally.freight.consolidation.line"].sudo().create({
            "consolidation_id": ailleurs.id,
            "package_id": paquet.id,
            "quantity_loaded": paquet.quantity,
        })

        item = self._colis_dto(self._detail(), paquet)
        self.assertEqual(item["status"], STATUT_BLOQUE)
        self.assertTrue(item["blocker"])
        self.assertFalse(item["can_load"])

        with self.assertRaises(DallyOpsError) as capture:
            self._appliquer("load", paquet)
        self.assertEqual(capture.exception.code, "package_loaded_elsewhere")

    # ─── Validation de la demande ────────────────────────────────────

    def test_une_demande_mal_formee_est_refusee(self):
        reference = self._creer_dossier()
        paquet = self._colis_de(reference)
        base = {"request_uuid": str(uuid.uuid4()), "action": "load",
                "package_reference": paquet.ops_loading_uuid}

        charges = [
            None, [], "load",
            {**base, "quantity": 1},
            {cle: valeur for cle, valeur in base.items() if cle != "action"},
            {cle: valeur for cle, valeur in base.items() if cle != "request_uuid"},
        ]
        avant = len(self._lignes())
        for charge in charges:
            with self.assertRaises(DallyOpsError):
                self._service().apply_loading(self.depart.name, charge)
        self.assertEqual(len(self._lignes()), avant)

    def test_une_action_inconnue_est_refusee(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        for action in ("deliver", "close", "depart", "LOAD", ""):
            with self.assertRaises(DallyOpsError) as capture:
                self._appliquer(action, paquet)
            self.assertEqual(capture.exception.code, "loading_action_invalid")

    def test_un_identifiant_de_geste_non_uuid_est_refuse(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        for identifiant in ("", "pas-un-uuid", 42):
            with self.assertRaises(DallyOpsError):
                self._appliquer("load", paquet, request_uuid=identifiant)

    # ─── Audit ───────────────────────────────────────────────────────

    def test_chaque_geste_laisse_une_trace_ancree_sur_le_depart(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        self._appliquer("load", paquet)

        trace = self._audits(ACTION_AUDIT_CHARGE)
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace.entity_model, "dally.freight.consolidation")
        self.assertEqual(trace.entity_res_id, self.depart.id)
        self.assertEqual(trace.shipment_id, self._shipment(reference))
        self.assertEqual(trace.operator_user_id, self.gilles)
        champs = {change["field"]: change for change in trace.changes_json}
        self.assertEqual(champs["package_reference"]["new_value"],
                         paquet.ops_loading_uuid)
        self.assertEqual(champs["quantity_loaded"]["old_value"], "0")
        self.assertEqual(champs["quantity_loaded"]["new_value"],
                         str(paquet.quantity))

    def test_un_retrait_laisse_sa_propre_trace(self):
        reference = self._creer_dossier()
        paquet = self._colis_de(reference)
        self._appliquer("load", paquet)
        self._appliquer("unload", paquet)

        trace = self._audits(ACTION_AUDIT_RETIRE)
        self.assertEqual(len(trace), 1)
        champs = {change["field"]: change for change in trace.changes_json}
        self.assertEqual(champs["quantity_loaded"]["new_value"], "0")

    def test_les_deux_actions_sont_lisibles_dans_le_fil_d_activite(self):
        for action in (ACTION_AUDIT_CHARGE, ACTION_AUDIT_RETIRE):
            self.assertIn(action, EVENEMENTS_PUBLICS)
            libelle, categorie = EVENEMENTS_PUBLICS[action]
            self.assertTrue(libelle)
            self.assertEqual(categorie, "loading")

    # ─── Ce qu'un chargement ne touche pas ───────────────────────────

    def test_charger_ne_touche_ni_l_etat_ni_les_champs_metier_du_dossier(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        shipment = self._shipment(reference)
        surveilles = ["state", "partner_id", "external_reference",
                      "collection_local_ref", "intake_consolidation_id",
                      "transport_mode", "direction", "sync_source"]
        avant = {champ: shipment[champ] for champ in surveilles}
        avant_colis = {
            "quantity": paquet.quantity,
            "unit_weight_kg": paquet.unit_weight_kg,
            "description": paquet.description,
            "ops_loading_uuid": paquet.ops_loading_uuid,
            "write_date": paquet.write_date,
        }

        self._appliquer("load", paquet)
        shipment.invalidate_recordset()
        paquet.invalidate_recordset()

        for champ in surveilles:
            self.assertEqual(shipment[champ], avant[champ], champ)
        for champ, valeur in avant_colis.items():
            self.assertEqual(paquet[champ], valeur, champ)

    def test_charger_n_ecrit_aucun_paiement_ni_aucune_facture(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        paiements = self.env["account.payment"].sudo().search_count([])
        factures = self.env["account.move"].sudo().search_count([])

        self._appliquer("load", paquet)

        self.assertEqual(self.env["account.payment"].sudo().search_count([]), paiements)
        self.assertEqual(self.env["account.move"].sudo().search_count([]), factures)

    def test_charger_n_envoie_aucune_notification(self):
        reference = self._creer_dossier()
        paquet = self._decharger(reference)
        avant = self.env["dally.shipment.notification"].sudo().search_count([])
        self._appliquer("load", paquet)
        self.assertEqual(
            self.env["dally.shipment.notification"].sudo().search_count([]), avant)

    # ─── La migration qui pose les identités ─────────────────────────

    def test_la_migration_pose_une_identite_sans_toucher_write_date(self):
        """Le backfill est le seul endroit où une identité est posée sur un
        colis existant. S'il modifiait `write_date`, il ferait passer une
        opération technique pour une correction métier."""
        reference = self._creer_dossier()
        paquet = self._colis_de(reference)
        self.env.flush_all()

        # On remet le colis dans l'état d'avant la mise à jour : aucune
        # identité, et une date d'écriture ancienne et connue.
        self.env.cr.execute(
            "UPDATE dally_shipment_package "
            "   SET ops_loading_uuid = NULL, write_date = %s WHERE id = %s",
            ["2026-01-15 08:30:00", paquet.id])

        chemin = (Path(__file__).resolve().parent.parent / "migrations"
                  / "19.0.1.14.0" / "post-backfill-loading-uuid.py")
        specification = importlib.util.spec_from_file_location(
            "dally_ops_backfill_loading_uuid", chemin)
        migration = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(migration)
        migration.migrate(self.env.cr, "19.0.1.13.0")

        self.env.cr.execute(
            "SELECT ops_loading_uuid, write_date FROM dally_shipment_package "
            " WHERE id = %s", [paquet.id])
        identite, ecrit_le = self.env.cr.fetchone()
        self.assertTrue(identite)
        self.assertEqual(str(ecrit_le), "2026-01-15 08:30:00")

        self.env.cr.execute(
            "SELECT count(*), count(DISTINCT ops_loading_uuid) "
            "  FROM dally_shipment_package")
        total, distincts = self.env.cr.fetchone()
        self.assertEqual(total, distincts)

    def test_la_migration_ne_tourne_pas_sur_une_installation_neuve(self):
        """`version` vide signale une installation, pas une mise à jour :
        les colis n'existent pas encore, il n'y a rien à reprendre."""
        chemin = (Path(__file__).resolve().parent.parent / "migrations"
                  / "19.0.1.14.0" / "post-backfill-loading-uuid.py")
        specification = importlib.util.spec_from_file_location(
            "dally_ops_backfill_loading_uuid_neuf", chemin)
        migration = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(migration)

        reference = self._creer_dossier()
        paquet = self._colis_de(reference)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE dally_shipment_package SET ops_loading_uuid = NULL WHERE id = %s",
            [paquet.id])
        migration.migrate(self.env.cr, None)
        self.env.cr.execute(
            "SELECT ops_loading_uuid FROM dally_shipment_package WHERE id = %s",
            [paquet.id])
        self.assertIsNone(self.env.cr.fetchone()[0])


def _descendants(racine):
    """Toute la descendance d'une classe, pas seulement ses filles directes.

    `__subclasses__()` ne descend que d'un niveau. Un contrôleur qui hériterait
    d'une classe intermédiaire échapperait à l'inspection — alors qu'Odoo le
    fusionnerait comme les autres, et que le conflit de signature passerait
    inaperçu.

    Écrite au niveau du module pour être éprouvée seule, sur une hiérarchie
    jouet : construire un vrai contrôleur intermédiaire polluerait la carte de
    routage d'Odoo pour toute la suite.
    """
    for fille in racine.__subclasses__():
        yield fille
        yield from _descendants(fille)


@tagged("post_install", "-at_install", "dally")
class TestOpsControllersNeSeMarchentPasDessus(TransactionCase):
    """Deux contrôleurs Ops ne peuvent pas définir la même aide autrement.

    ## Le défaut que ce test aurait évité

    Odoo fusionne tous les contrôleurs qui partagent une base en une seule
    classe. Le contrôleur du chargement a défini un `_servir(self, operation)`
    là où celui des dépenses attendait `_servir(self, operation, route)` : la
    route des dépenses est tombée en 500, sans qu'aucun test du chargement ne
    s'en aperçoive. Seule la suite d'un *autre* module l'a vu.

    Le test ne réclame pas des noms uniques — la maison partage volontiers
    `_erreur` et `_servir`, à l'identique. Il réclame que deux définitions du
    même nom aient exactement la même signature.
    """

    def test_le_parcours_descend_au_dela_des_filles_directes(self):
        """La récursion, prouvée sur une hiérarchie à trois étages.

        `__subclasses__()` seul ne verrait que `Intermediaire`. C'est
        `Petite` — deux niveaux plus bas — qui porterait le conflit de
        signature, et qui échappait donc au garde.
        """
        class Racine:
            pass

        class Intermediaire(Racine):
            pass

        class Petite(Intermediaire):
            pass

        directes = set(Racine.__subclasses__())
        toutes = set(_descendants(Racine))
        self.assertEqual(directes, {Intermediaire})
        self.assertEqual(toutes, {Intermediaire, Petite})
        self.assertNotIn(Petite, directes)

    def test_deux_aides_de_meme_nom_ont_la_meme_signature(self):
        import importlib
        import inspect
        import pkgutil

        from odoo.addons.dally_ops_mobile import controllers
        from odoo.addons.dally_ops_mobile.controllers.ops_base import (
            DallyOpsController,
        )

        for module in pkgutil.iter_modules(controllers.__path__):
            importlib.import_module(
                "odoo.addons.dally_ops_mobile.controllers.%s" % module.name)

        signatures = {}
        conflits = []
        for classe in _descendants(DallyOpsController):
            for nom, membre in vars(classe).items():
                if not nom.startswith("_") or nom.startswith("__"):
                    continue
                fonction = getattr(membre, "__func__", membre)
                if not inspect.isfunction(fonction):
                    continue
                signature = str(inspect.signature(fonction))
                connu = signatures.setdefault(nom, (classe.__name__, signature))
                if connu[1] != signature:
                    conflits.append(
                        "%s : %s%s contredit %s%s"
                        % (nom, classe.__name__, signature, connu[0], connu[1]))

        self.assertEqual(conflits, [], "\n".join(conflits))


@tagged("post_install", "-at_install", "dally")
class TestOpsLoadingHttp(HttpCase):
    """Les routes elles-mêmes, éprouvées par HTTP réel.

    Un test de service ne traverse ni le routage, ni la session, ni la
    fusion des contrôleurs — et c'est précisément là qu'un défaut s'est
    logé. Ce qui est déclaré servi ne l'est que mesuré ainsi.
    """

    MOT_DE_PASSE = "OpsProbe!2026#load"

    def setUp(self):
        super().setUp()
        self.societe = self.env["res.company"].create({"name": "Ops Chargement HTTP SA"})
        self.logisticien = self._compte(
            "http.load.logi", "Gilles HTTP Chargement",
            "dally_ops_mobile.group_dally_ops_logistician")
        self.etranger = self._compte(
            "http.load.autre", "Sans rôle", "base.group_user")
        self.partner = self.env["res.partner"].create({
            "name": "Client Chargement HTTP", "company_id": self.societe.id,
        })
        self.depart = self.env["dally.freight.consolidation"].create({
            "name": "AIR-HTTP-LOAD-001", "company_id": self.societe.id,
            "transport_mode": "air", "direction": "export", "state": "collecting",
            "origin_country_id": self.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": self.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })
        self.dossier = self.env["dally.shipment"].create({
            "partner_id": self.partner.id, "company_id": self.societe.id,
            "external_reference": "AIR-HTTP-LOAD-001-A001",
            "transport_mode": "air", "direction": "export",
            # Le pays fait partie de la route : sans lui, le cœur refuse le
            # rattachement pour « divergence sur origin route ».
            "origin_country_id": self.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": self.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })
        self.colis = self.env["dally.shipment.package"].create({
            "shipment_id": self.dossier.id, "package_type": "parcel",
            "description": "Savon", "quantity": 2, "unit_weight_kg": 5.0,
        })
        self.dossier.planned_consolidation_id = self.depart

    def _compte(self, login, nom, groupe):
        return self.env["res.users"].create({
            "name": nom, "login": login, "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref(groupe).id])],
            "company_id": self.societe.id,
            "company_ids": [(6, 0, [self.societe.id])],
        })

    def _ouvrir(self, chemin, login="http.load.logi"):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(
            "/api/v1/ops/loading/%s" % chemin, allow_redirects=False)

    def _poster(self, chemin, charge, login="http.load.logi"):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(
            "/api/v1/ops/loading/%s" % chemin, data=json.dumps(charge),
            headers={"Content-Type": "application/json"}, allow_redirects=False)

    def _geste(self, action="load", **changements):
        charge = {
            "request_uuid": str(uuid.uuid4()), "action": action,
            "package_reference": self.colis.ops_loading_uuid,
        }
        charge.update(changements)
        return charge

    # ─── Lecture ─────────────────────────────────────────────────────

    def test_la_liste_est_servie_au_role_ops(self):
        reponse = self._ouvrir("consolidations")
        self.assertEqual(reponse.status_code, 200, reponse.content[:800])
        references = [item["reference"] for item
                      in json.loads(reponse.content)["data"]["consolidations"]]
        self.assertIn(self.depart.name, references)

    def test_le_detail_montre_le_dossier_attendu(self):
        reponse = self._ouvrir("consolidations/%s" % self.depart.name)
        self.assertEqual(reponse.status_code, 200, reponse.content[:800])
        detail = json.loads(reponse.content)["data"]["loading"]
        self.assertEqual([d["reference"] for d in detail["shipments"]],
                         [self.dossier.external_reference])
        self.assertEqual(detail["shipments"][0]["packages"][0]["status"],
                         STATUT_NON_CHARGE)

    def test_la_reponse_n_est_jamais_mise_en_cache(self):
        entetes = self._ouvrir("consolidations").headers
        self.assertEqual(entetes.get("Cache-Control"), "private, no-store, max-age=0")
        self.assertEqual(entetes.get("X-Content-Type-Options"), "nosniff")

    def test_un_depart_inconnu_repond_404(self):
        reponse = self._ouvrir("consolidations/AIR-HTTP-LOAD-INCONNU")
        self.assertEqual(reponse.status_code, 404)
        self.assertEqual(json.loads(reponse.content)["error"]["code"],
                         "consolidation_not_found")

    # ─── Mutation ────────────────────────────────────────────────────

    def test_le_logisticien_charge_un_colis_par_http(self):
        reponse = self._poster("consolidations/%s" % self.depart.name, self._geste())
        self.assertEqual(reponse.status_code, 200, reponse.content[:800])
        donnees = json.loads(reponse.content)["data"]
        self.assertFalse(donnees["replayed"])
        self.assertEqual(donnees["loading"]["shipments"][0]["packages"][0]["status"],
                         STATUT_CHARGE)
        self.assertEqual(self.env["dally.freight.consolidation.line"].search_count(
            [("consolidation_id", "=", self.depart.id)]), 1)

    def test_le_meme_geste_rejoue_par_http_ne_charge_pas_deux_fois(self):
        geste = self._geste()
        chemin = "consolidations/%s" % self.depart.name
        self.assertEqual(self._poster(chemin, geste).status_code, 200)
        second = self._poster(chemin, geste)
        self.assertEqual(second.status_code, 200, second.content[:800])
        self.assertTrue(json.loads(second.content)["data"]["replayed"])
        self.assertEqual(self.env["dally.freight.consolidation.line"].search_count(
            [("consolidation_id", "=", self.depart.id)]), 1)

    def test_un_corps_illisible_repond_400(self):
        self.authenticate("http.load.logi", self.MOT_DE_PASSE)
        reponse = self.url_open(
            "/api/v1/ops/loading/consolidations/%s" % self.depart.name,
            data="pas du json", headers={"Content-Type": "application/json"},
            allow_redirects=False)
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(json.loads(reponse.content)["error"]["code"],
                         "invalid_request")

    def test_une_reference_de_colis_non_textuelle_repond_404_et_non_500(self):
        """Le contrat, pas une trace de pile.

        C'est par HTTP que se mesure la différence : une `AttributeError`
        traverserait le contrôleur et rendrait 500.
        """
        chemin = "consolidations/%s" % self.depart.name
        for valeur in (42, True, [], {}, None):
            reponse = self._poster(chemin, self._geste(package_reference=valeur))
            self.assertEqual(reponse.status_code, 404, "%r -> %s" % (valeur, reponse.content[:200]))
            self.assertEqual(json.loads(reponse.content)["error"]["code"],
                             "package_not_found", valeur)

    def test_un_identifiant_de_geste_espace_reste_le_meme_geste(self):
        """Deux envois du même identifiant, l'un espacé, ne chargent qu'une fois."""
        identifiant = str(uuid.uuid4())
        chemin = "consolidations/%s" % self.depart.name
        premier = self._poster(chemin, self._geste(request_uuid=identifiant))
        self.assertEqual(premier.status_code, 200, premier.content[:400])
        second = self._poster(chemin, self._geste(request_uuid="  %s  " % identifiant))
        self.assertEqual(second.status_code, 200, second.content[:400])
        self.assertTrue(json.loads(second.content)["data"]["replayed"])
        self.assertEqual(self.env["dally.freight.consolidation.line"].search_count(
            [("consolidation_id", "=", self.depart.id)]), 1)

    def test_une_action_inconnue_repond_400(self):
        reponse = self._poster("consolidations/%s" % self.depart.name,
                               self._geste(action="depart"))
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(json.loads(reponse.content)["error"]["code"],
                         "loading_action_invalid")

    # ─── Refus ───────────────────────────────────────────────────────

    def test_un_authentifie_sans_role_ops_est_refuse_partout(self):
        chemin = "consolidations/%s" % self.depart.name
        self.assertEqual(self._ouvrir("consolidations", "http.load.autre").status_code, 403)
        self.assertEqual(self._ouvrir(chemin, "http.load.autre").status_code, 403)
        self.assertEqual(
            self._poster(chemin, self._geste(), "http.load.autre").status_code, 403)
        self.assertFalse(self.env["dally.freight.consolidation.line"].search(
            [("consolidation_id", "=", self.depart.id)]))

    def test_aucun_verbe_de_modification_n_est_route(self):
        self.authenticate("http.load.logi", self.MOT_DE_PASSE)
        for verbe in ("PUT", "PATCH", "DELETE"):
            reponse = self.opener.request(
                verbe,
                self.base_url() + "/api/v1/ops/loading/consolidations/%s" % self.depart.name,
                allow_redirects=False)
            self.assertEqual(reponse.status_code, 405, verbe)
