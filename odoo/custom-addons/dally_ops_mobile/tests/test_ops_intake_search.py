# -*- coding: utf-8 -*-
"""La recherche de dossier, telle que le comptoir en a besoin.

## Ce que ces tests protègent

**La clé de navigation.** `A001` est local à son départ : deux consolidations
en ont chacune un. Le résultat de recherche doit donc porter la référence
**globale**, et l'écran ne doit jamais composer une URL avec la référence
locale — il ouvrirait le dossier d'un autre client.

**La promesse d'ouverture.** La fiche Ops ne sait afficher que les dossiers nés
de Dally Ops. Un dossier repris du classeur historique existe, se cherche et
s'identifie, mais sa fiche détaillée n'est pas encore compatible. Le serveur le
dit — `detail_access` — plutôt que de laisser l'écran deviner une règle qu'il
appliquerait de travers.

**La surface d'énumération.** Une recherche ouvre une porte : rôle, société,
longueur minimale et plafond de résultats sont imposés par le serveur, jamais
par l'interface.
"""

import base64
import json
import uuid

from odoo.tests import HttpCase, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError


@tagged("post_install", "-at_install", "dally")
class TestOpsIntakeSearch(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.societe = cls.env.company
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Search Autre"})

        cls.gilles = cls._compte("search.gilles", "Gilles Search",
                                 "dally_ops_mobile.group_dally_ops_logistician")
        cls.temoin = cls._compte("search.temoin", "Temoin Search",
                                 "base.group_user")

        Famille = cls.env["dally.freight.tariff.family"]
        Regle = cls.env["dally.freight.tariff.rule"]
        cls.famille = Famille.search([("code", "=", "non_food")], limit=1)
        if not cls.famille:
            cls.famille = Famille.create(
                {"name": "Search Non alimentaire", "code": "non_food"})
        if not Regle.search([("family_id", "=", cls.famille.id),
                             ("transport_mode", "=", "air")], limit=1):
            Regle.create({
                "name": "Search non_food air", "transport_mode": "air",
                "family_id": cls.famille.id, "customer_segment": "all",
                "price_per_kg_eur": 5.0,
            })

        cls.partner = cls.env["res.partner"].create({
            "name": "Mayram Soumaré", "company_id": cls.societe.id,
            "phone": "+221 77 123 45 67",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })

        cls.depart_un = cls._consolidation("AIR-DSS-CDG-SEARCH-001")
        cls.depart_deux = cls._consolidation("AIR-DSS-CDG-SEARCH-002")

    # ─── Fabriques ───────────────────────────────────────────────────

    @classmethod
    def _compte(cls, prefixe, nom, groupe):
        return cls.env["res.users"].create({
            "name": nom, "login": "%s.%s" % (prefixe, uuid.uuid4().hex[:6]),
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

    def _depart_neuf(self):
        """Un départ à lui seul, pour que sa numérotation reparte de `A001`.

        Les séquences PostgreSQL ne se rembobinent pas entre deux tests : un
        départ partagé par la classe distribue `A001`, puis `A002`, puis
        `A017`. Un test qui parle de `A001` doit donc s'en donner un neuf.
        """
        return self._consolidation(
            "AIR-DSS-CDG-SEARCH-%s" % uuid.uuid4().hex[:8].upper())

    def _dossier_ops(self, consolidation=None):
        """Un dossier moderne, créé par le vrai service d'entrée."""
        resultat = (self.env["dally.ops.intake.service"]
                    .with_user(self.gilles).with_company(self.societe)
                    .create_intake({
                        "request_uuid": str(uuid.uuid4()),
                        "consolidation_reference": (
                            consolidation or self.depart_un).name,
                        "customer_reference": self.handle.token,
                        "received_on": "2026-08-29",
                        "line": {
                            "line_uuid": str(uuid.uuid4()),
                            "package_type": "parcel",
                            "goods_category": "Non alimentaire",
                            "description": "Savon", "quantity": 1,
                            "announced_weight_kg": None, "exact_weight_kg": 13.5,
                            "length_cm": None, "width_cm": None, "height_cm": None,
                            "billing_method": "real",
                            "tariff_family_code": self.famille.code,
                            "customs_value_xof": 25000,
                        },
                    }))
        return resultat["intake"]["reference"]

    def _dossier_ancien(self, reference, societe=None, partenaire=None):
        """Un dossier repris du classeur : aucune identité Ops."""
        return self.env["dally.shipment"].sudo().create({
            "partner_id": (partenaire or self.partner).id,
            "company_id": (societe or self.societe).id,
            "external_reference": reference,
            "transport_mode": "air", "direction": "export",
        })

    def _chercher(self, q, utilisateur=None, **options):
        service = (self.env["dally.ops.intake.search.service"]
                   .with_user(utilisateur or self.gilles)
                   .with_company(self.societe))
        return service.search_intakes(q, **options)

    @staticmethod
    def _references(resultat):
        return [item["reference"] for item in resultat["items"]]

    # ─── R1/R2 · retrouver par référence ─────────────────────────────

    def test_R1_reference_locale_exacte(self):
        reference = self._dossier_ops(self._depart_neuf())
        resultat = self._chercher("A001")
        self.assertIn(reference, self._references(resultat))

    def test_R2_reference_globale_exacte(self):
        reference = self._dossier_ops()
        self.assertEqual(self._references(self._chercher(reference)), [reference])

    def test_R2b_reference_globale_avec_annee_et_sequence(self):
        """Une vraie référence porte une année : elle passe les neuf chiffres.

        `AIR-DSS-CDG-2026-902-A001` ne contient que dix chiffres une fois les
        lettres et les tirets retirés — assez pour que la convention
        téléphonique la reconnaisse comme un numéro et cherche un partenaire
        au lieu d'un dossier.

        Les autres tests de référence globale ne l'attrapaient pas : leur
        consolidation s'appelle `AIR-DSS-CDG-SEARCH-001`, qui n'a que six
        chiffres. La fixture ne ressemblait pas à la production.
        """
        depart = self._consolidation("AIR-DSS-CDG-2026-902")
        reference = self._dossier_ops(depart)
        self.assertEqual(reference, "AIR-DSS-CDG-2026-902-A001")

        self.assertEqual(
            self._references(self._chercher(reference)), [reference])

    def test_R2c_une_reference_globale_n_est_jamais_lue_comme_un_numero(self):
        """La classification, prise au mot.

        Le test précédent vérifie le résultat ; celui-ci vérifie le chemin.
        Une chaîne qui contient des lettres n'entre pas dans la branche
        téléphone, quel que soit le nombre de chiffres qu'elle porte.
        """
        service = (self.env["dally.ops.intake.search.service"]
                   .with_user(self.gilles).with_company(self.societe))
        # La branche téléphone se reconnaît à sa forme exacte :
        # `("partner_id", "in", [...])`. La recherche par nom, elle, vise
        # `partner_id.name` — c'est un chemin, pas la même chose.
        BRANCHE_TELEPHONE = "('partner_id', 'in'"

        for reference in ("AIR-DSS-CDG-2026-902-A001",
                          "SEA-DKR-LEH-2026-014-A007",
                          "AIR-DSS-CDG-2026-002"):
            domaine = repr(service._domaine_de_recherche(reference))
            self.assertNotIn(
                BRANCHE_TELEPHONE, domaine,
                "%r ne doit pas être cherchée comme un numéro" % reference)
            self.assertIn("external_reference", domaine)

        # …et les cinq saisies téléphoniques y entrent toujours.
        for saisie in ("+221 77 123 45 67", "00221771234567",
                       "221771234567", "77 123 45 67", "771234567"):
            domaine = repr(service._domaine_de_recherche(saisie))
            self.assertIn(
                BRANCHE_TELEPHONE, domaine,
                "%r doit rester une recherche par numéro" % saisie)

    # ─── R3/R15/R16 · le dossier repris du classeur ──────────────────

    def test_R3_un_dossier_ancien_est_retrouve(self):
        self._dossier_ancien("A012")
        self.assertIn("A012", self._references(self._chercher("A012")))

    def test_R15_un_dossier_ancien_annonce_sa_fiche_indisponible(self):
        self._dossier_ancien("A012")
        item = self._chercher("A012")["items"][0]
        self.assertEqual(item["reference"], "A012")
        self.assertEqual(item["local_reference"], "")
        self.assertEqual(item["detail_access"], "unavailable")
        self.assertEqual(item["detail_access_reason"], "legacy_not_supported")

    def test_R16_aucune_url_de_fiche_n_est_publiee(self):
        self._dossier_ancien("A012")
        contenu = json.dumps(self._chercher("A012"), ensure_ascii=False)
        for interdit in ("/reception/", "http://", "https://", "url", "href"):
            self.assertNotIn(interdit, contenu)

    # ─── R17/R18 · le dossier Ops ────────────────────────────────────

    def test_R17_un_dossier_ops_est_ouvrable(self):
        reference = self._dossier_ops()
        item = self._chercher(reference)["items"][0]
        self.assertEqual(item["detail_access"], "full")
        self.assertIsNone(item["detail_access_reason"])

    def test_R18_la_cle_de_navigation_est_la_reference_globale(self):
        reference = self._dossier_ops(self._depart_neuf())
        item = self._chercher("A001")["items"][0]
        self.assertEqual(item["reference"], reference)
        self.assertEqual(item["local_reference"], "A001")
        self.assertNotEqual(item["reference"], item["local_reference"])

    # ─── R11/R19 · deux A001 ne se confondent pas ────────────────────

    def test_R11_deux_A001_de_departs_differents_restent_distincts(self):
        premier = self._dossier_ops(self._depart_neuf())
        second = self._dossier_ops(self._depart_neuf())
        resultat = self._chercher("A001")
        references = self._references(resultat)
        self.assertIn(premier, references)
        self.assertIn(second, references)
        self.assertNotEqual(premier, second)

    def test_R19_deux_A001_portent_deux_references_globales(self):
        self._dossier_ops(self._depart_neuf())
        self._dossier_ops(self._depart_neuf())
        items = self._chercher("A001")["items"]
        locales = {item["local_reference"] for item in items}
        globales = {item["reference"] for item in items}
        self.assertEqual(locales, {"A001"})
        self.assertEqual(len(globales), 2)

    # ─── R4/R5 · client et téléphone ─────────────────────────────────

    def test_R4_nom_client_partiel(self):
        reference = self._dossier_ops()
        self.assertIn(reference, self._references(self._chercher("Soumar")))

    def test_R5_le_telephone_suit_la_convention_existante(self):
        reference = self._dossier_ops()
        for saisie in ("+221 77 123 45 67", "00221771234567",
                       "221771234567", "77 123 45 67", "771234567"):
            self.assertIn(
                reference, self._references(self._chercher(saisie)),
                "la saisie %r doit retrouver le dossier" % saisie)

    def test_R5b_un_fragment_de_numero_ne_cherche_pas_un_telephone(self):
        """Moins de neuf chiffres : la convention CRM refuse déjà de comparer."""
        self._dossier_ops()
        self.assertEqual(self._chercher("7712345")["items"], [])

    # ─── R6/R7 · portée ──────────────────────────────────────────────

    def test_R6_un_dossier_d_une_autre_societe_est_invisible(self):
        autre_partenaire = self.env["res.partner"].create({
            "name": "Mayram Soumaré", "company_id": self.autre_societe.id,
            "phone": "+221 77 123 45 67",
        })
        self._dossier_ancien("A099", societe=self.autre_societe,
                             partenaire=autre_partenaire)
        for saisie in ("A099", "Soumar", "771234567"):
            self.assertNotIn("A099", self._references(self._chercher(saisie)))

    def test_R7_un_compte_sans_role_ops_est_refuse(self):
        self._dossier_ops()
        with self.assertRaises(DallyOpsError) as erreur:
            self._chercher("A001", utilisateur=self.temoin)
        self.assertEqual(erreur.exception.code, "ops_forbidden")

    # ─── R8/R9/R10 · bornes serveur ──────────────────────────────────

    def test_R8_une_recherche_vide_est_refusee(self):
        for vide in ("", "   ", None):
            with self.assertRaises(DallyOpsError) as erreur:
                self._chercher(vide)
            self.assertEqual(erreur.exception.code, "search_query_required")

    def test_R9_une_recherche_trop_courte_est_refusee(self):
        self._dossier_ops()
        for court in ("a", "7", "*", "é"):
            with self.assertRaises(DallyOpsError) as erreur:
                self._chercher(court)
            self.assertEqual(erreur.exception.code, "search_query_too_short")

    def test_R9b_une_recherche_demesuree_est_refusee(self):
        with self.assertRaises(DallyOpsError) as erreur:
            self._chercher("a" * 200)
        self.assertEqual(erreur.exception.code, "search_query_too_long")

    def test_R10_le_plafond_de_resultats_est_impose_par_le_serveur(self):
        depart = self._depart_neuf()
        for _index in range(6):
            self._dossier_ops(depart)
        self.assertEqual(len(self._chercher("A0", limit=2)["items"]), 2)
        # Un plafond réclamé au-delà du maximum serveur est refusé, jamais servi.
        for demesure in (0, -1, 500, 10_000):
            with self.assertRaises(DallyOpsError) as erreur:
                self._chercher("A0", limit=demesure)
            self.assertEqual(erreur.exception.code, "search_limit_invalid")

    # ─── R12 · rien d'interne ne sort ────────────────────────────────

    def test_R12_aucun_identifiant_interne_n_est_publie(self):
        reference = self._dossier_ops()
        self._dossier_ancien("A012")
        contenu = json.dumps(
            {"a": self._chercher("A001"), "b": self._chercher("A012"),
             "c": self._chercher(reference)},
            ensure_ascii=False)
        for interdit in ("shipment_id", "partner_id", "sale_order_id",
                         "invoice_id", "sync_source_key", "external_line_key",
                         "external_payment_key", "\"id\"", "ops:"):
            self.assertNotIn(interdit, contenu)

    # ─── R13/R14 · pagination et absence de résultat ─────────────────

    def test_R13_une_page_bornee_annonce_qu_il_en_reste(self):
        """Une recherche de comptoir se raffine ; elle ne se feuillette pas.

        Pas de curseur, donc pas de clé de parcours à publier — et donc rien
        à perdre ni à doubler entre deux pages, puisqu'il n'y en a qu'une.
        """
        depart = self._depart_neuf()
        for _index in range(5):
            self._dossier_ops(depart)

        borne = self._chercher("A0", limit=2)
        self.assertEqual(len(borne["items"]), 2)
        self.assertTrue(borne["has_more"])
        self.assertNotIn("next_cursor", borne)

        entier = self._chercher("A0", limit=50)
        self.assertGreaterEqual(len(entier["items"]), 5)
        self.assertFalse(entier["has_more"])

    def test_R13b_deux_recherches_identiques_rendent_le_meme_ordre(self):
        depart = self._depart_neuf()
        for _index in range(3):
            self._dossier_ops(depart)
        self.assertEqual(
            self._references(self._chercher("A0")),
            self._references(self._chercher("A0")),
            "le résultat doit être stable d'un appel à l'autre")

    def test_R13c_aucun_identifiant_de_base_ne_sort_meme_encode(self):
        """Le jeton de parcours d'hier encodait `shipment.id` en base64.

        Un encodage n'est pas une protection : ce test décode ce qui sort et
        vérifie qu'aucune valeur — brute, en texte, ou en base64 — ne
        correspond à un identifiant de la base.
        """
        depart = self._depart_neuf()
        references = [self._dossier_ops(depart) for _index in range(3)]
        identifiants = self.env["dally.shipment"].sudo().search(
            [("external_reference", "in", references)]).ids
        self.assertTrue(identifiants)

        resultat = self._chercher("A0", limit=2)
        self.assertTrue(resultat["has_more"])
        contenu = json.dumps(resultat, ensure_ascii=False)

        def valeurs(noeud):
            if isinstance(noeud, dict):
                for valeur in noeud.values():
                    yield from valeurs(valeur)
            elif isinstance(noeud, list):
                for valeur in noeud:
                    yield from valeurs(valeur)
            else:
                yield noeud

        publiees = list(valeurs(resultat))
        for identifiant in identifiants:
            self.assertNotIn(identifiant, publiees)
            self.assertNotIn(str(identifiant), publiees)
            encode = base64.urlsafe_b64encode(
                str(identifiant).encode("utf-8")).decode("ascii")
            self.assertNotIn(encode, contenu)
            self.assertNotIn(encode.rstrip("="), contenu)

    def test_R14_une_recherche_sans_resultat_reste_un_succes(self):
        resultat = self._chercher("ZZZ-INTROUVABLE-9999")
        self.assertEqual(resultat["items"], [])
        self.assertFalse(resultat["has_more"])

    # ─── La règle d'ouverture n'est pas dupliquée ────────────────────

    def test_la_regle_douverture_est_celle_de_la_fiche(self):
        """Une seconde formulation divergerait, et promettrait à tort.

        La recherche ne réécrit pas le domaine de la fiche : elle appelle la
        même méthode. Ce test échoue si quelqu'un en recopie une variante.
        """
        Ligne = self.env["dally.ops.intake.line.service"]
        domaine = Ligne.with_company(self.societe)._domaine_dossier_ops()
        self.assertIn(("company_id", "=", self.societe.id), domaine)
        self.assertIn(("sync_source", "=", "backoffice"), domaine)
        self.assertIn(("sync_source_key", "=like", "ops:%"), domaine)
        self.assertIn(("intake_consolidation_id", "!=", False), domaine)

    def test_un_dossier_declare_full_est_reellement_ouvrable(self):
        """Le contrat le plus important : `full` ne doit jamais mentir."""
        reference = self._dossier_ops()
        self._dossier_ancien("A012")
        Ligne = (self.env["dally.ops.intake.line.service"]
                 .with_user(self.gilles).with_company(self.societe))
        for saisie in ("A001", "A012", reference):
            for item in self._chercher(saisie)["items"]:
                if item["detail_access"] == "full":
                    self.assertTrue(Ligne.get_intake(item["reference"]))
                else:
                    with self.assertRaises(DallyOpsError):
                        Ligne.get_intake(item["reference"])


@tagged("post_install", "-at_install", "dally")
class TestOpsIntakeSearchRoute(HttpCase):
    """La route HTTP, y compris son cohabitation avec `/intakes/<reference>`."""

    def test_la_route_de_recherche_exige_une_session(self):
        """Sans session, Odoo renvoie vers la connexion — jamais un résultat."""
        reponse = self.url_open(
            "/api/v1/ops/intakes/search?q=A001", allow_redirects=False)
        self.assertIn(reponse.status_code,
                      (301, 302, 303, 307, 308, 401, 403))
        self.assertNotIn("\"items\"", reponse.content.decode("utf-8", "replace"))

    def test_la_route_de_recherche_n_est_pas_avalee_par_la_fiche(self):
        """`search` doit atteindre la recherche, pas un dossier nommé « search ».

        Werkzeug préfère un segment statique à une règle dynamique ; on le
        vérifie plutôt que de s'en remettre à cette préséance.
        """
        reponse = self.url_open(
            "/api/v1/ops/intakes/search?q=A001", allow_redirects=False)
        self.assertNotIn(
            "intake_not_found", reponse.content.decode("utf-8", "replace"))
