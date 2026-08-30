# -*- coding: utf-8 -*-
"""Contrat de création d'une réception Dally Ops."""

import ast
import inspect
import json
import uuid

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.dally_ops_mobile.controllers import ops_intakes
from odoo.addons.dally_ops_mobile.models.ops_errors import (
    DallyOpsConflict,
    DallyOpsError,
    DallyOpsInternal,
    DallyOpsNotFound,
)


def code_seul(module):
    arbre = ast.parse(inspect.getsource(module))
    for noeud in ast.walk(arbre):
        if not isinstance(
            noeud,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue
        premier = noeud.body[0] if noeud.body else None
        if (
            isinstance(premier, ast.Expr)
            and isinstance(premier.value, ast.Constant)
            and isinstance(premier.value.value, str)
        ):
            noeud.body = noeud.body[1:] or [ast.Pass()]
    return ast.unparse(arbre)


@tagged("post_install", "-at_install", "dally")
class TestOpsIntakes(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.societe = cls.env["res.company"].create({
            "name": "Ops Intakes SA",
        })
        cls.autre_societe = cls.env["res.company"].create({
            "name": "Ops Intakes Autre SA",
        })
        cls.logisticien = cls._compte(
            "intake.logi", "Gilles Intake",
            "dally_ops_mobile.group_dally_ops_logistician",
        )
        cls.responsable = cls._compte(
            "intake.resp", "Dalanda Intake",
            "dally_ops_mobile.group_dally_ops_supervisor",
        )
        cls.non_ops = cls._compte(
            "intake.autre", "Sans rôle Intake", "base.group_user",
        )
        cls.partner = cls.env["res.partner"].create({
            "name": "Aissatou Intake",
            "company_id": cls.societe.id,
            "phone": "+221 77 123 45 67",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id,
            "company_id": cls.societe.id,
        })
        cls.family = cls.env["dally.freight.tariff.family"].create({
            "name": "Ops Non alimentaire",
            "code": "ops_non_food",
            "sequence": 20,
        })
        cls.family_first = cls.env["dally.freight.tariff.family"].create({
            "name": "Ops Alimentaire",
            "code": "ops_food",
            "sequence": 10,
        })
        cls.env["dally.freight.tariff.rule"].create({
            "name": "Ops air 5 EUR",
            "transport_mode": "air",
            "family_id": cls.family.id,
            "customer_segment": "individual",
            "price_per_kg_eur": 5.0,
            "volumetric_ratio_kg_cbm": 167.0,
        })
        cls.c1 = cls._consolidation(
            "AIR-DSS-CDG-OPS-001",
        )
        cls.c2 = cls._consolidation(
            "AIR-DSS-CDG-OPS-002",
        )

    @classmethod
    def _compte(cls, login, nom, groupe):
        return cls.env["res.users"].create({
            "name": nom,
            "login": login,
            "group_ids": [(6, 0, [cls.env.ref(groupe).id])],
            "company_id": cls.societe.id,
            "company_ids": [(6, 0, [cls.societe.id])],
        })

    @classmethod
    def _consolidation(cls, reference, **valeurs):
        defauts = {
            "name": reference,
            "state": "collecting",
            "active": True,
            "company_id": cls.societe.id,
            "transport_mode": "air",
            "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris",
            "destination_location": "CDG",
        }
        defauts.update(valeurs)
        return cls.env[
            "dally.freight.consolidation"
        ].create(defauts)

    def _service(self, utilisateur=None):
        utilisateur = utilisateur or self.logisticien
        return (
            self.env["dally.ops.intake.service"]
            .with_user(utilisateur)
            .with_company(self.societe)
        )

    def _charge(self, consolidation=None, customer=None, **changements):
        ligne = {
            "line_uuid": str(uuid.uuid4()),
            "package_type": "parcel",
            "goods_category": "Non alimentaire",
            "description": "Savon",
            "quantity": 1,
            "announced_weight_kg": 13.0,
            "exact_weight_kg": 13.5,
            "length_cm": None,
            "width_cm": None,
            "height_cm": None,
            "billing_method": "real",
            "tariff_family_code": self.family.code,
            "customs_value_xof": 25000,
        }
        ligne.update(changements.pop("line", {}))
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "consolidation_reference": (
                consolidation or self.c1
            ).name,
            "customer_reference": (
                customer or self.handle
            ).token,
            "received_on": "2026-08-28",
            "line": ligne,
        }
        charge.update(changements)
        return charge

    def test_roles_et_zero_acl(self):
        for utilisateur in (self.logisticien, self.responsable):
            resultat = self._service(utilisateur).create_intake(
                self._charge(),
            )
            self.assertEqual(resultat["status"], "created")
        with self.assertRaises(AccessError):
            self._service(self.non_ops).create_intake(self._charge())
        for modele in ("dally.shipment", "dally.shipment.package"):
            self.assertFalse(
                self.env[modele]
                .with_user(self.logisticien)
                .has_access("read"),
            )

    def test_handle_invalide_archive_et_autre_societe_sont_introuvables(self):
        with self.assertRaises(DallyOpsNotFound) as erreur:
            self._service().create_intake(
                self._charge(
                    customer=type("Jeton", (), {"token": str(uuid.uuid4())})(),
                ),
            )
        self.assertEqual(erreur.exception.code, "customer_not_found")

        self.partner.active = False
        with self.assertRaises(DallyOpsNotFound):
            self._service().create_intake(self._charge())
        self.partner.active = True

        partenaire_autre = self.env["res.partner"].create({
            "name": "Autre société",
            "company_id": self.autre_societe.id,
        })
        handle_autre = self.env[
            "dally.ops.customer.handle"
        ].sudo().create({
            "partner_id": partenaire_autre.id,
            "company_id": self.autre_societe.id,
        })
        with self.assertRaises(DallyOpsNotFound):
            self._service().create_intake(
                self._charge(customer=handle_autre),
            )

    def test_consolidations_air_mer_road_et_fermee(self):
        mer = self._consolidation(
            "SEA-DKR-LEH-OPS-001",
            transport_mode="sea",
            origin_location="DKR",
            destination_location="LEH",
        )
        self.assertEqual(
            self._service().create_intake(
                self._charge(
                    consolidation=mer,
                    line={"billing_method": "quote"},
                ),
            )["intake"]["state"],
            "goods_received",
        )
        road = self._consolidation(
            "ROAD-DKR-BKO-OPS-001",
            transport_mode="road",
            origin_location="DKR",
            destination_location="BKO",
        )
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service().create_intake(
                self._charge(consolidation=road),
            )
        self.assertEqual(
            erreur.exception.code, "consolidation_not_open",
        )
        fermee = self._consolidation(
            "AIR-DSS-CDG-OPS-CLOSED",
        )
        fermee.action_close_collection()
        with self.assertRaises(DallyOpsConflict):
            self._service().create_intake(
                self._charge(consolidation=fermee),
            )

    def test_route_mode_direction_et_identites_viennent_du_serveur(self):
        charge = self._charge()
        resultat = self._service().create_intake(charge)
        shipment = self.env["dally.shipment"].sudo().search([
            (
                "external_reference", "=",
                resultat["intake"]["reference"],
            ),
        ])
        self.assertEqual(shipment.transport_mode, self.c1.transport_mode)
        self.assertEqual(shipment.direction, self.c1.direction)
        self.assertEqual(shipment.origin_location, self.c1.origin_location)
        self.assertEqual(
            shipment.destination_location,
            self.c1.destination_location,
        )
        self.assertEqual(
            shipment.sync_source_key,
            "ops:%s" % charge["request_uuid"],
        )
        self.assertEqual(
            shipment.package_ids.external_line_key,
            "ops:%s:line:%s"
            % (
                charge["request_uuid"],
                charge["line"]["line_uuid"],
            ),
        )

    def test_a001_a002_et_reset_par_consolidation(self):
        x = self._service().create_intake(
            self._charge(consolidation=self.c1),
        )
        y = self._service().create_intake(
            self._charge(consolidation=self.c1),
        )
        z = self._service().create_intake(
            self._charge(consolidation=self.c2),
        )
        self.assertEqual(
            [
                x["intake"]["local_reference"],
                y["intake"]["local_reference"],
                z["intake"]["local_reference"],
            ],
            ["A001", "A002", "A001"],
        )
        self.assertEqual(
            x["intake"]["reference"],
            "%s-A001" % self.c1.name,
        )
        self.assertEqual(
            z["intake"]["reference"],
            "%s-A001" % self.c2.name,
        )

    def test_goods_received_colis_et_rattachement(self):
        resultat = self._service().create_intake(self._charge())
        shipment = self.env["dally.shipment"].sudo().search([
            ("external_reference", "=", resultat["intake"]["reference"]),
        ])
        self.assertEqual(shipment.state, "goods_received")
        self.assertEqual(len(shipment.package_ids), 1)
        self.assertEqual(shipment.intake_consolidation_id, self.c1)
        self.assertEqual(shipment.planned_consolidation_id, self.c1)
        self.assertEqual(shipment.consolidation_id, self.c1)
        self.assertTrue(shipment.consolidation_line_ids)

    def test_poids_exact_est_total_et_quantite_positive(self):
        resultat = self._service().create_intake(
            self._charge(
                line={"quantity": 4, "exact_weight_kg": 79.9},
            ),
        )
        self.assertAlmostEqual(
            resultat["intake"]["line"]["exact_weight_kg"],
            79.9,
            places=3,
        )
        shipment = self.env["dally.shipment"].sudo().search([
            (
                "external_reference", "=",
                resultat["intake"]["reference"],
            ),
        ])
        self.assertAlmostEqual(
            shipment.package_ids.unit_weight_kg,
            79.9 / 4,
            places=3,
        )
        for valeur in (0, -1, 1.5, True):
            with self.assertRaises(DallyOpsError):
                self._service().create_intake(
                    self._charge(line={"quantity": valeur}),
                )

    def test_famille_customs_types_et_dimensions_sont_stricts(self):
        cas = [
            {"tariff_family_code": ""},
            {"tariff_family_code": "inconnue"},
            {"customs_value_xof": 0},
            {"customs_value_xof": None},
            {"package_type": "vehicle"},
            {"package_type": "container"},
            {"length_cm": 10},
            {
                "billing_method": "volumetric",
                "length_cm": None,
                "width_cm": None,
                "height_cm": None,
            },
        ]
        for ligne in cas:
            with self.subTest(ligne=ligne):
                with self.assertRaises(DallyOpsError):
                    self._service().create_intake(
                        self._charge(line=ligne),
                    )
        resultat = self._service().create_intake(
            self._charge(line={
                "billing_method": "volumetric",
                "length_cm": 100,
                "width_cm": 50,
                "height_cm": 40,
            }),
        )
        self.assertAlmostEqual(
            resultat["intake"]["line"]["volume_cbm"],
            0.2,
            places=4,
        )

    def test_automatic_manual_required_et_quote(self):
        automatique = self._service().create_intake(
            self._charge(),
        )
        ligne = automatique["intake"]["line"]
        self.assertEqual(ligne["pricing_status"], "automatic")
        self.assertEqual(ligne["applied_unit_price_eur"], 5.0)
        self.assertEqual(ligne["transport_amount_eur"], 67.5)

        mer = self._consolidation(
            "SEA-DKR-LEH-OPS-PRICE",
            transport_mode="sea",
            origin_location="DKR",
            destination_location="LEH",
        )
        manuel = self._service().create_intake(
            self._charge(consolidation=mer),
        )["intake"]["line"]
        self.assertEqual(
            manuel["pricing_status"], "manual_required",
        )
        self.assertIsNone(manuel["applied_unit_price_eur"])
        self.assertIsNone(manuel["transport_amount_eur"])

        devis = self._service().create_intake(
            self._charge(line={"billing_method": "quote"}),
        )["intake"]["line"]
        self.assertEqual(devis["pricing_status"], "quote")
        self.assertIsNone(devis["transport_amount_eur"])

    def test_etats_pricing_incoherents_font_rollback(self):
        charge = self._charge()
        service = self._service()
        original = type(service)._verifier_resultat
        try:
            type(service)._verifier_resultat = (
                lambda _self, resultat, shipment, consolidation:
                shipment.package_ids
            )
            freight = self.env[
                "dally.freight.sync.service"
            ].sudo().with_company(self.societe)
            methode = type(freight)._price_line_if_ready
            type(freight)._price_line_if_ready = (
                lambda _self, line: "pending_family"
            )
            with self.assertRaises(DallyOpsInternal):
                service.create_intake(charge)
        finally:
            type(service)._verifier_resultat = original
            type(freight)._price_line_if_ready = methode
        self.assertFalse(
            self.env["dally.shipment"].sudo().search([
                (
                    "sync_source_key", "=",
                    "ops:%s" % charge["request_uuid"],
                ),
            ]),
        )

    def test_partner_reste_strictement_inchange(self):
        self.partner.flush_recordset()
        avant = self.partner.write_date
        self._service().create_intake(self._charge())
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.write_date, avant)

    def test_replay_garde_a001_un_colis_et_le_tarif_historique(self):
        consolidation = self._consolidation(
            "AIR-DSS-CDG-OPS-REPLAY",
        )
        charge = self._charge(consolidation=consolidation)
        premier = self._service().create_intake(charge)
        shipment = self.env["dally.shipment"].sudo().search([
            (
                "external_reference", "=",
                premier["intake"]["reference"],
            ),
        ])
        package = shipment.package_ids
        snapshot = (
            package.tariff_applied_on,
            package.tariff_rule_id,
            package.applied_unit_price_eur,
        )
        second = self._service().create_intake(charge)
        package.invalidate_recordset()
        self.assertEqual(second["status"], "replayed")
        self.assertEqual(
            second["intake"]["local_reference"], "A001",
        )
        self.assertEqual(
            second["intake"]["reference"],
            premier["intake"]["reference"],
        )
        self.assertEqual(len(shipment.package_ids), 1)
        self.assertEqual(
            (
                package.tariff_applied_on,
                package.tariff_rule_id,
                package.applied_unit_price_eur,
            ),
            snapshot,
        )

    def test_meme_uuid_autre_payload_est_un_conflit(self):
        charge = self._charge()
        self._service().create_intake(charge)
        modifiee = dict(charge)
        modifiee["line"] = dict(
            charge["line"], description="Autre",
        )
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._service().create_intake(modifiee)
        self.assertEqual(
            erreur.exception.code, "idempotency_conflict",
        )

    def test_audit_operateur_reel_et_aucun_responsable_sudo(self):
        charge = self._charge()
        resultat = self._service().create_intake(charge)
        shipment = self.env["dally.shipment"].sudo().search([
            (
                "external_reference", "=",
                resultat["intake"]["reference"],
            ),
        ])
        self.assertFalse(shipment.user_id)
        evenement = self.env[
            "dally.ops.audit.event"
        ].sudo().search([
            ("action", "=", "intake_created"),
            ("request_uuid", "=", charge["request_uuid"]),
        ])
        self.assertEqual(evenement.operator_user_id, self.logisticien)
        self.assertEqual(evenement.entity_model, "dally.shipment")
        self.assertEqual(evenement.entity_res_id, shipment.id)
        self._service().create_intake(charge)
        rejeu = self.env[
            "dally.ops.audit.event"
        ].sudo().search([
            ("action", "=", "intake_request_replayed"),
            ("request_uuid", "=", charge["request_uuid"]),
        ])
        self.assertEqual(rejeu.operator_user_id, self.logisticien)

    def test_dto_ne_contient_aucun_identifiant_odoo(self):
        texte = str(
            self._service().create_intake(self._charge()),
        )
        for interdit in (
            "shipment_id", "package_id", "partner_id",
            "consolidation_id", "tariff_rule_id",
            "collection_sequence", "sync_source_key",
            "external_line_key", "sale_order_id", "invoice_id",
        ):
            self.assertNotIn(interdit, texte)

    def test_champs_serveur_et_inconnus_sont_refuses(self):
        for cle in (
            "partner_id", "shipment_id", "package_id",
            "consolidation_id", "external_reference",
            "sync_source_key", "collection_local_ref",
            "transport_mode", "direction", "origin",
            "destination", "state",
        ):
            charge = self._charge()
            charge[cle] = 1
            with self.subTest(cle=cle):
                with self.assertRaises(DallyOpsError):
                    self._service().create_intake(charge)
        for cle in (
            "external_line_key", "manual_unit_price_eur",
            "pricing_reason", "pricing_type",
            "collection_sequence",
        ):
            with self.subTest(cle=cle):
                with self.assertRaises(DallyOpsError):
                    self._service().create_intake(
                        self._charge(line={cle: 1}),
                    )

    def test_familles_actives_seulement_triees_sans_prix(self):
        inactive = self.env[
            "dally.freight.tariff.family"
        ].create({
            "name": "Ops Inactive",
            "code": "ops_inactive",
            "active": False,
        })
        familles = self._service().list_tariff_families()
        codes = [famille["code"] for famille in familles]
        self.assertNotIn(inactive.code, codes)
        self.assertLess(
            codes.index(self.family_first.code),
            codes.index(self.family.code),
        )
        for famille in familles:
            self.assertEqual(set(famille), {"code", "name"})

    def test_controller_ne_contient_ni_sudo_ni_cle_api(self):
        source = code_seul(ops_intakes)
        self.assertNotIn(".sudo(", source)
        self.assertNotIn("API_KEY", source)
        self.assertNotIn("freight:", source)
        self.assertIn('auth="user"', inspect.getsource(ops_intakes))


@tagged("post_install", "-at_install", "dally")
class TestOpsIntakesHttp(HttpCase):
    """La route elle-même, éprouvée par HTTP réel.

    Les tests ci-dessus appellent le service directement, ce qui laissait la
    route hors couverture : un défaut n'existant que dans le chemin HTTP
    passait inaperçu. C'est arrivé, et ce fichier existe pour que cela ne se
    reproduise pas.
    """

    MOT_DE_PASSE = "OpsProbe!2026#http"
    ROUTE = "/api/v1/ops/intakes"

    def setUp(self):
        super().setUp()
        self.societe = self.env["res.company"].create({"name": "Ops Intake HTTP SA"})
        self.logisticien = self._compte(
            "http.logi", "Gilles HTTP",
            "dally_ops_mobile.group_dally_ops_logistician")
        self.etranger = self._compte("http.autre", "Sans rôle", "base.group_user")

        self.partner = self.env["res.partner"].create({
            "name": "Client HTTP", "company_id": self.societe.id,
        })
        self.handle = self.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": self.partner.id, "company_id": self.societe.id,
        })
        self.famille = self.env["dally.freight.tariff.family"].create({
            "name": "Non alimentaire HTTP", "code": "http_non_food",
        })
        self.env["dally.freight.tariff.rule"].create({
            "name": "Aérien HTTP", "transport_mode": "air",
            "family_id": self.famille.id, "customer_segment": "all",
            "price_per_kg_eur": 5.0,
        })
        self.consolidation = self.env["dally.freight.consolidation"].create({
            "name": "AIR-HTTP-TEST-001", "company_id": self.societe.id,
            "transport_mode": "air", "direction": "export", "state": "collecting",
            "origin_country_id": self.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": self.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })

    def _compte(self, login, nom, groupe):
        return self.env["res.users"].create({
            "name": nom, "login": login, "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref(groupe).id])],
            "company_id": self.societe.id,
            "company_ids": [(6, 0, [self.societe.id])],
        })

    def _charge(self, **changements):
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "consolidation_reference": self.consolidation.name,
            "customer_reference": self.handle.token,
            "received_on": "2026-08-28",
            "line": {
                "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                "goods_category": "Non alimentaire", "description": "Savon",
                "quantity": 1, "announced_weight_kg": None, "exact_weight_kg": 13.5,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "billing_method": "real", "tariff_family_code": self.famille.code,
                "customs_value_xof": 25000,
            },
        }
        charge.update(changements)
        return charge

    def _poster(self, charge, login="http.logi"):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(
            self.ROUTE, data=json.dumps(charge),
            headers={"Content-Type": "application/json"}, allow_redirects=False)

    def test_le_logisticien_enregistre_une_reception_par_http(self):
        reponse = self._poster(self._charge())
        self.assertEqual(reponse.status_code, 200, reponse.content[:500])
        charge = json.loads(reponse.content)["data"]
        self.assertEqual(charge["status"], "created")
        self.assertEqual(charge["intake"]["local_reference"], "A001")
        self.assertEqual(
            charge["intake"]["reference"], "%s-A001" % self.consolidation.name)
        self.assertEqual(charge["intake"]["state"], "goods_received")
        self.assertEqual(charge["intake"]["line"]["pricing_status"], "automatic")

    def test_un_authentifie_sans_role_ops_est_refuse(self):
        self.assertEqual(self._poster(self._charge(), "http.autre").status_code, 403)

    def test_un_anonyme_est_renvoye_vers_la_connexion(self):
        reponse = self._poster(self._charge(), None)
        self.assertIn(reponse.status_code, (302, 303))

    def test_les_familles_tarifaires_sont_lisibles_par_http(self):
        self.authenticate("http.logi", self.MOT_DE_PASSE)
        reponse = self.url_open("/api/v1/ops/tariff-families", allow_redirects=False)
        self.assertEqual(reponse.status_code, 200)
        familles = json.loads(reponse.content)["data"]["tariff_families"]
        self.assertTrue(familles)
        for famille in familles:
            self.assertEqual(sorted(famille), ["code", "name"])

    def test_le_dto_http_ne_contient_aucun_identifiant_odoo(self):
        contenu = self._poster(self._charge()).content.decode()
        for interdit in ("shipment_id", "package_id", "partner_id", "consolidation_id",
                         "tariff_rule_id", "collection_sequence", "sync_source_key",
                         "external_line_key", "sale_order_id", "invoice_id"):
            self.assertNotIn(interdit, contenu)
