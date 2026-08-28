# -*- coding: utf-8 -*-
"""Les départs ouverts, vus par un compte qui ne peut rien lire.

Ce fichier éprouve la seule chose vraiment nouvelle de cette étape : un
logisticien à **zéro modèle métier accessible** obtient une liste de départs.
La contradiction n'est qu'apparente — il n'a pas accès au modèle, il a accès à
une réponse. Le test central est
``test_le_logisticien_ne_lit_pas_le_modele_mais_recoit_la_reponse``.
"""

import ast
import inspect
import json

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged

from odoo.addons.dally_freight_consolidation.models.consolidation import (
    _CONSOLIDATION_BYPASS_TOKEN,
)


def code_seul(module):
    """Le code exécutable d'un module, sans commentaires ni docstrings.

    Les canaris de ce fichier cherchent des interdits — ``sudo``, ``freight:``,
    une clé d'API. Or ces mots figurent légitimement dans la prose qui explique
    précisément pourquoi ils sont absents du code. Chercher dans le texte brut
    revenait à interdire d'expliquer l'interdit ; on analyse donc l'arbre
    syntaxique, où les commentaires n'existent pas et d'où les docstrings sont
    retirées.
    """
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
class TestOpsConsolidations(HttpCase):

    #: Un mot de passe de banc, jamais réutilisé ailleurs.
    MOT_DE_PASSE = "OpsProbe!2026#cons"

    ROUTE = "/api/v1/ops/consolidations"

    def setUp(self):
        super().setUp()
        # Une société dédiée, et non celle du banc.
        #
        # Le premier jet supposait une base sans départ ouvert. Elle l'était le
        # jour où il a été écrit, plus le lendemain : les consolidations créées
        # pour les essais de bout en bout faisaient échouer la moitié du
        # fichier, et le test de liste vide n'aurait plus jamais rien prouvé.
        # Une société propre rend chaque test indépendant de ce que la base
        # contient déjà — ce qui est aussi la situation réelle en production.
        self.societe = self.env["res.company"].create({"name": "Ops Banc SA"})
        self.logisticien = self._compte(
            "cons.logi", "Gilles Test",
            ["dally_ops_mobile.group_dally_ops_logistician"])
        self.responsable = self._compte(
            "cons.resp", "Dalanda Test",
            ["dally_ops_mobile.group_dally_ops_supervisor"])
        self.etranger = self._compte("cons.etranger", "Sans rôle", ["base.group_user"])
        self.senegal = self.env.ref("base.sn")
        self.france = self.env.ref("base.fr")

    def _compte(self, login, nom, groupes):
        """Un compte non interne dès que le rôle Ops suffit."""
        return self.env["res.users"].create({
            "name": nom,
            "login": login,
            "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref(g).id for g in groupes])],
            "company_id": self.societe.id,
            "company_ids": [(6, 0, [self.societe.id])],
        })

    def _consolidation(self, reference, **valeurs):
        """Un départ de banc.

        Créé à l'état ``collecting`` — le seul que ``create`` accepte avec
        ``draft`` — puis positionné si besoin par le jeton interne du modèle.
        Passer par les actions métier exigerait des lignes, des dossiers et des
        contrôles de départ : beaucoup de décor pour vérifier un filtre d'état.
        """
        etat = valeurs.pop("state", "collecting")
        defauts = {
            "name": reference,
            # Le défaut du modèle est « brouillon » : sans cette ligne, aucune
            # consolidation de banc ne serait visible et tous les tests de
            # visibilité passeraient pour la mauvaise raison.
            "state": "collecting",
            "company_id": self.societe.id,
            "transport_mode": "air",
            "direction": "export",
            "origin_country_id": self.senegal.id,
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_country_id": self.france.id,
            "destination_city": "Paris",
            "destination_location": "CDG",
        }
        defauts.update(valeurs)
        consolidation = self.env["dally.freight.consolidation"].create(defauts)
        if etat != "collecting":
            consolidation.with_context(
                _dally_consolidation_bypass=_CONSOLIDATION_BYPASS_TOKEN
            ).write({"state": etat})
        return consolidation

    def _appel(self, login=None, requete=""):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(self.ROUTE + requete, allow_redirects=False)

    def _references(self, login="cons.logi"):
        reponse = self._appel(login)
        self.assertEqual(reponse.status_code, 200)
        charge = json.loads(reponse.content)
        self.assertTrue(charge["success"])
        return [c["reference"] for c in charge["data"]["consolidations"]]

    # ─── La preuve centrale ──────────────────────────────────────────

    def test_le_logisticien_ne_lit_pas_le_modele_mais_recoit_la_reponse(self):
        """L'architecture Ops tient dans ce test.

        Aucun droit sur le modèle, et pourtant une réponse : le privilège vit
        dans le service, jamais dans le compte.
        """
        self._consolidation("AIR-DSS-CDG-TEST-001")

        Consolidation = self.env["dally.freight.consolidation"].with_user(self.logisticien)
        with self.assertRaises(AccessError):
            Consolidation.search([])

        self.assertIn("AIR-DSS-CDG-TEST-001", self._references())

    def test_le_logisticien_garde_zero_modele_metier_accessible(self):
        """Cette étape n'a ouvert aucune ACL."""
        self.assertFalse(
            self.env["dally.freight.consolidation"]
            .with_user(self.logisticien).has_access("read"))
        lisibles = []
        for nom in self.env.registry:
            modele = self.env[nom]
            if modele._abstract or modele._transient:
                continue
            try:
                if modele.with_user(self.logisticien).has_access("read"):
                    lisibles.append(nom)
            except Exception:  # pragma: no cover
                continue
        self.assertFalse(lisibles, "modèles lisibles : %s" % ", ".join(sorted(lisibles)))

    # ─── Qui a le droit d'appeler ────────────────────────────────────

    def test_le_logisticien_obtient_200(self):
        self.assertEqual(self._appel("cons.logi").status_code, 200)

    def test_le_responsable_obtient_200(self):
        self.assertEqual(self._appel("cons.resp").status_code, 200)

    def test_un_authentifie_sans_role_ops_obtient_403(self):
        reponse = self._appel("cons.etranger")
        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(json.loads(reponse.content)["success"])

    def test_le_refus_ne_renseigne_pas_sur_les_droits(self):
        contenu = self._appel("cons.etranger").content.decode()
        for indice in ("group_", "dally_ops_mobile.", "dally.freight.consolidation",
                       "AccessError", "Traceback"):
            self.assertNotIn(indice, contenu)

    def test_un_anonyme_est_renvoye_vers_la_connexion(self):
        reponse = self._appel(None)
        self.assertIn(reponse.status_code, (302, 303))
        self.assertIn("/web/login", reponse.headers.get("Location", ""))

    def test_le_service_refuse_lui_meme_un_appelant_sans_role(self):
        """La garde du service ne dépend pas du contrôleur."""
        service = self.env["dally.ops.consolidation.service"].with_user(self.etranger)
        with self.assertRaises(AccessError):
            service.list_open_for_intake()

    # ─── Ce qui est visible ──────────────────────────────────────────

    def test_un_depart_aerien_en_collecte_est_visible(self):
        self._consolidation("AIR-DSS-CDG-TEST-001", transport_mode="air")
        self.assertIn("AIR-DSS-CDG-TEST-001", self._references())

    def test_un_depart_maritime_en_collecte_est_visible(self):
        self._consolidation("SEA-DKR-LEH-TEST-001", transport_mode="sea")
        self.assertIn("SEA-DKR-LEH-TEST-001", self._references())

    # ─── Ce qui ne l'est pas ─────────────────────────────────────────

    def test_un_depart_routier_est_invisible(self):
        """Phase 1 : uniquement des colis. Un départ routier ne se réceptionne
        pas au comptoir ; l'afficher inviterait à y déposer un colis."""
        self._consolidation("ROAD-DKR-BKO-TEST-001", transport_mode="road")
        self.assertNotIn("ROAD-DKR-BKO-TEST-001", self._references())

    def test_les_etats_hors_collecte_sont_invisibles(self):
        for etat in ("draft", "collection_closed", "ready", "departed",
                     "arrived", "closed", "cancelled"):
            with self.subTest(etat=etat):
                reference = "AIR-DSS-CDG-ETAT-%s" % etat.upper()
                self._consolidation(reference, state=etat)
                self.assertNotIn(reference, self._references())

    def test_une_consolidation_archivee_est_invisible(self):
        self._consolidation("AIR-DSS-CDG-TEST-ARCH", active=False)
        self.assertNotIn("AIR-DSS-CDG-TEST-ARCH", self._references())

    def test_une_consolidation_d_une_autre_societe_est_invisible(self):
        self._consolidation("AIR-DSS-CDG-TEST-AUTRE", company_id=self.env.company.id)
        self.assertNotIn("AIR-DSS-CDG-TEST-AUTRE", self._references())

    def test_aucun_parametre_de_requete_n_elargit_la_recherche(self):
        """Le navigateur ne peut fournir ni société, ni état, ni domaine."""
        self._consolidation("ROAD-DKR-BKO-TEST-002", transport_mode="road")
        self._consolidation("AIR-DSS-CDG-ETAT-DRAFT2", state="draft")
        reponse = self._appel(
            "cons.logi",
            "?state=draft&transport_mode=road&company_id=0&domain=%5B%5D&limit=1000")
        references = [c["reference"] for c in json.loads(reponse.content)["data"]["consolidations"]]
        self.assertNotIn("ROAD-DKR-BKO-TEST-002", references)
        self.assertNotIn("AIR-DSS-CDG-ETAT-DRAFT2", references)

    # ─── Le contrat du DTO ───────────────────────────────────────────

    def test_le_dto_a_exactement_les_champs_prevus(self):
        self._consolidation("AIR-DSS-CDG-TEST-001")
        charge = json.loads(self._appel("cons.logi").content)
        entree = charge["data"]["consolidations"][0]
        self.assertEqual(sorted(entree), [
            "collection_close_on", "destination", "direction", "origin",
            "reference", "scheduled_departure", "transport_mode",
        ])
        self.assertEqual(sorted(entree["origin"]), ["city", "country_code", "location"])
        self.assertEqual(sorted(entree["destination"]), ["city", "country_code", "location"])

    def test_le_dto_ne_contient_aucun_identifiant_odoo(self):
        """Une API qui expose des ids devient un instrument d'énumération."""
        consolidation = self._consolidation("AIR-DSS-CDG-TEST-001")
        contenu = self._appel("cons.logi").content.decode()
        self.assertNotIn('"id"', contenu)
        self.assertNotIn('"%s"' % consolidation.id, contenu)
        self.assertNotIn("_id", contenu)

    def test_le_dto_ne_contient_aucun_champ_sensible(self):
        consolidation = self._consolidation(
            "AIR-DSS-CDG-TEST-001",
            mawb_number="074-12345678",
            hawb_reference="HAWB-SECRET",
            shipper_label="Expéditeur interne",
            consignee_label="Destinataire interne",
            goods_nature="Notes internes sur la marchandise",
            carrier_name="Air France",
            flight_number="AF718",
            master_gross_weight_kg=812.5,
        )
        self.assertTrue(consolidation.mawb_number)
        contenu = self._appel("cons.logi").content.decode()
        for interdit in ("074-12345678", "HAWB-SECRET", "Expéditeur interne",
                         "Destinataire interne", "Notes internes", "Air France",
                         "AF718", "812.5", "mawb", "hawb", "shipper", "consignee",
                         "intake_sequence", "line_ids", "shipment", "invoice",
                         "package_line_count", "create_uid", "write_uid",
                         "weight", "margin", "cost", "state", "active"):
            self.assertNotIn(interdit, contenu, "champ ou valeur sensible : %s" % interdit)

    def test_les_valeurs_presentes_sont_au_format_attendu(self):
        self._consolidation(
            "AIR-DSS-CDG-TEST-001",
            collection_close_on="2026-09-03",
            scheduled_departure="2026-09-05 10:00:00",
        )
        entree = json.loads(self._appel("cons.logi").content)["data"]["consolidations"][0]
        self.assertEqual(entree, {
            "reference": "AIR-DSS-CDG-TEST-001",
            "transport_mode": "air",
            "direction": "export",
            "origin": {"country_code": "SN", "city": "Dakar", "location": "DSS"},
            "destination": {"country_code": "FR", "city": "Paris", "location": "CDG"},
            "collection_close_on": "2026-09-03",
            "scheduled_departure": "2026-09-05T10:00:00Z",
        })

    def test_une_date_absente_vaut_null_et_un_texte_absent_vaut_vide(self):
        """Contrat figé : inventer une date de départ serait un mensonge, une
        ville absente ne s'affiche simplement pas."""
        self._consolidation(
            "AIR-XXX-YYY-TEST-001",
            origin_country_id=False, origin_city=False, origin_location=False,
            destination_country_id=False, destination_city=False,
            destination_location=False,
        )
        entree = json.loads(self._appel("cons.logi").content)["data"]["consolidations"][0]
        self.assertIsNone(entree["collection_close_on"])
        self.assertIsNone(entree["scheduled_departure"])
        self.assertEqual(entree["origin"], {"country_code": "", "city": "", "location": ""})
        self.assertEqual(entree["destination"], {"country_code": "", "city": "", "location": ""})

    def test_l_ordre_est_deterministe_et_place_les_sans_date_a_la_fin(self):
        self._consolidation("AIR-DSS-CDG-TEST-003")
        self._consolidation("AIR-DSS-CDG-TEST-002", collection_close_on="2026-09-10")
        self._consolidation("AIR-DSS-CDG-TEST-001", collection_close_on="2026-09-03")
        self._consolidation("AIR-DSS-CDG-TEST-004")
        self.assertEqual(self._references(), [
            "AIR-DSS-CDG-TEST-001",
            "AIR-DSS-CDG-TEST-002",
            "AIR-DSS-CDG-TEST-003",
            "AIR-DSS-CDG-TEST-004",
        ])

    def test_a_date_de_cloture_egale_le_depart_prevu_departage(self):
        self._consolidation("AIR-DSS-CDG-TEST-002", collection_close_on="2026-09-03",
                            scheduled_departure="2026-09-06 08:00:00")
        self._consolidation("AIR-DSS-CDG-TEST-001", collection_close_on="2026-09-03",
                            scheduled_departure="2026-09-05 08:00:00")
        self.assertEqual(self._references(),
                         ["AIR-DSS-CDG-TEST-001", "AIR-DSS-CDG-TEST-002"])

    def test_la_liste_vide_reste_un_succes(self):
        """Aucun départ ouvert n'est pas une erreur : c'est un jour sans."""
        charge = json.loads(self._appel("cons.logi").content)
        self.assertTrue(charge["success"])
        self.assertEqual(charge["data"]["consolidations"], [])

    def test_la_reponse_n_est_jamais_mise_en_cache(self):
        entetes = self._appel("cons.logi").headers
        self.assertEqual(entetes.get("Cache-Control"), "private, no-store, max-age=0")
        self.assertEqual(entetes.get("X-Content-Type-Options"), "nosniff")

    # ─── La frontière de privilège ───────────────────────────────────

    def test_le_controleur_ne_contient_aucun_sudo(self):
        from odoo.addons.dally_ops_mobile.controllers import (
            ops_base, ops_consolidations, ops_identity,
        )
        for module in (ops_base, ops_consolidations, ops_identity):
            with self.subTest(module=module.__name__):
                self.assertNotIn("sudo", code_seul(module))

    def test_le_sudo_est_unique_et_confine_a_une_seule_methode(self):
        from odoo.addons.dally_ops_mobile.models import ops_consolidation_service

        self.assertEqual(code_seul(ops_consolidation_service).count(".sudo()"), 1)
        self.assertIn(".sudo()", inspect.getsource(
            ops_consolidation_service.DallyOpsConsolidationService._rechercher_departs_ouverts))

    def test_le_service_n_expose_aucune_methode_generique(self):
        """Pas de `ops_sudo(modele, domaine)` : la décision de sécurité ne doit
        pas pouvoir migrer vers l'appelant."""
        from odoo.addons.dally_ops_mobile.models.ops_consolidation_service import (
            DallyOpsConsolidationService,
        )

        publiques = sorted(
            nom for nom, valeur in vars(DallyOpsConsolidationService).items()
            if not nom.startswith("_") and callable(valeur)
        )
        self.assertEqual(publiques, ["list_open_for_intake"])

    def test_le_domaine_du_service_est_ecrit_en_dur(self):
        from odoo.addons.dally_ops_mobile.models import ops_consolidation_service

        source = inspect.getsource(
            ops_consolidation_service.DallyOpsConsolidationService._rechercher_departs_ouverts)
        for contrainte in ('("company_id", "=", self.env.company.id)',
                           '("active", "=", True)',
                           '("state", "=", self.ETAT_OUVERT)',
                           '("transport_mode", "in", list(self.MODES_COLIS))'):
            self.assertIn(contrainte, source)

    def test_la_route_n_utilise_ni_cle_d_api_ni_portee_freight(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_consolidations

        code = code_seul(ops_consolidations)
        for interdit in ("api_key", "required_scope", "freight:", "DallyApiController",
                         "X-API-Key"):
            self.assertNotIn(interdit, code)
        # Les valeurs positives se lisent dans le fichier tel qu'il est écrit :
        # `ast.unparse` normalise les guillemets, et un test ne doit pas
        # dépendre de cette normalisation.
        declaration = inspect.getsource(ops_consolidations)
        self.assertIn('auth="user"', declaration)
        self.assertIn("readonly=True", declaration)
        self.assertNotIn('auth="none"', declaration)
