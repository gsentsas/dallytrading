# -*- coding: utf-8 -*-
"""La projection du CRM vers le classeur Freight.

## Les deux propriétés que ces tests protègent

La première : **une panne Google n'annule rien**. La boîte d'envoi est écrite
dans la transaction métier, sans aucun accès réseau ; le colis reçu reste reçu
même si le classeur ne sera mis à jour que demain.

La seconde : **un rejeu ne double jamais une ligne**. La boîte porte une clé
métier unique par société, et la projection décrit un état plutôt qu'un delta.
Projeter deux fois le même état est sans effet ; c'est ce qui rend un accusé de
réception perdu inoffensif.

## Ce que ces tests refusent aussi

Qu'un `A001` serve d'identité globale. Deux départs différents ont chacun leur
`A001`, et les confondre mélangerait deux clients.
"""

import ast
import inspect
import json
import textwrap
import uuid
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


def code_seul(module):
    """Le code exécutable d'un module, sans commentaires ni docstrings."""
    arbre = ast.parse(textwrap.dedent(inspect.getsource(module)))
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
class TestOpsSheetOutbox(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.xof = cls.setup_other_currency("XOF")
        cls.eur = cls.setup_other_currency("EUR")
        cls.societe = cls.env.company
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Sheet Autre"})
        cls.societe.sudo().write({"dally_ops_wave_beneficiary": "Gilles"})

        cls.gilles = cls._compte(
            "sheet.gilles", "Gilles Sheet",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Gilles")
        cls.dalanda = cls._compte(
            "sheet.dalanda", "Dalanda Sheet",
            "dally_ops_mobile.group_dally_ops_logistician", acteur="Dalanda")

        cls.canal_wave = cls._canal("wave", "Wave", cls.xof)

        # Les codes de famille sont uniques dans toute la base : on réutilise
        # ceux qui existent plutôt que d'en créer des jumeaux, et on n'ajoute
        # une règle que si le couple famille/mode n'en a pas déjà une.
        cls.familles = {}
        Famille = cls.env["dally.freight.tariff.family"]
        Regle = cls.env["dally.freight.tariff.rule"]
        for code, nom in (("food", "Alimentaire standard"), ("seafood", "Halieutiques"),
                          ("honey", "Miel"), ("clothing", "Habits"),
                          ("non_food", "Non alimentaire")):
            famille = Famille.search([("code", "=", code)], limit=1)
            if not famille:
                famille = Famille.create({"name": "Sheet %s" % nom, "code": code})
            cls.familles[code] = famille
            for mode, prix in (("air", 5.0), ("sea", 3.0)):
                existante = Regle.search([
                    ("family_id", "=", famille.id), ("transport_mode", "=", mode),
                ], limit=1)
                if not existante:
                    Regle.create({
                        "name": "Sheet %s %s" % (code, mode), "transport_mode": mode,
                        "family_id": famille.id, "customer_segment": "all",
                        "price_per_kg_eur": prix,
                    })

        cls.partner = cls.env["res.partner"].create({
            "name": "Aissatou Sheet", "company_id": cls.societe.id,
            "phone": "+221770000001",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.air = cls._consolidation("AIR-DSS-CDG-SHEET-001", "air")
        cls.air2 = cls._consolidation("AIR-DSS-CDG-SHEET-002", "air")
        cls.sea = cls._consolidation("SEA-DKR-LEH-SHEET-001", "sea")

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

    def _boite(self):
        return self.env["dally.ops.sheet.outbox"].sudo()

    def _lignes(self, type_projection=None, societe=None):
        domaine = [("company_id", "=", (societe or self.societe).id)]
        if type_projection:
            domaine.append(("projection_type", "=", type_projection))
        return self._boite().search(domaine)

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
        resultat = (self.env["dally.ops.intake.service"]
                    .with_user(self.gilles).with_company(self.societe)
                    .create_intake({
                        "request_uuid": str(uuid.uuid4()),
                        "consolidation_reference": (consolidation or self.air).name,
                        "customer_reference": self.handle.token,
                        "received_on": "2026-08-29",
                        "line": saisie,
                    }))
        return resultat["intake"]["reference"]

    def _shipment(self, reference):
        return self.env["dally.shipment"].sudo().search(
            [("external_reference", "=", reference)], limit=1)

    def _recovery_expected(self, shipment):
        return {shipment.id: {
            "company_id": self.societe.id,
            "intake_consolidation_id": shipment.intake_consolidation_id.id,
            "external_reference": shipment.external_reference,
            "collection_local_ref": shipment.collection_local_ref,
            "collection_sequence": shipment.collection_sequence,
            "sync_source_key": shipment.sync_source_key,
        }}

    def _projeter(self, societe=None):
        """Un passage complet du transport, sans réseau."""
        return self._boite().claim_batch(societe or self.societe)

    def _accuser(self, projections, ok=True, permanent=False, erreur=""):
        return self._boite().acknowledge(self.societe, [
            {"outbox_id": p["outbox_id"], "ok": ok,
             "permanent": permanent, "error": erreur}
            for p in projections
        ])

    # ─── L'intention naît avec l'objet ───────────────────────────────

    def test_une_reception_inscrit_une_projection(self):
        reference = self._creer_dossier()
        lignes = self._lignes("freight_dossier")
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes.state, "pending")
        self.assertEqual(lignes.resource_model, "dally.shipment")
        self.assertEqual(lignes.resource_reference, reference)
        # La clé métier est la clé de source, pas le numéro visible.
        self.assertEqual(lignes.business_key, self._shipment(reference).sync_source_key)

    def test_un_rejeu_ne_cree_pas_une_seconde_intention(self):
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "consolidation_reference": self.air.name,
            "customer_reference": self.handle.token,
            "received_on": "2026-08-29",
            "line": {
                "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                "goods_category": "Non alimentaire", "description": "Savon",
                "quantity": 1, "announced_weight_kg": None, "exact_weight_kg": 13.5,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "billing_method": "real",
                "tariff_family_code": self.familles["non_food"].code,
                "customs_value_xof": 25000,
            },
        }
        service = (self.env["dally.ops.intake.service"]
                   .with_user(self.gilles).with_company(self.societe))
        service.create_intake(charge)
        service.create_intake(dict(charge))
        self.assertEqual(len(self._lignes("freight_dossier")), 1)
        # Compté sur le départ de ce test : la base du banc porte les
        # dossiers de toutes les étapes précédentes.
        self.assertEqual(
            self.env["dally.shipment"].sudo().search_count([
                ("intake_consolidation_id", "=", self.air.id),
                ("sync_source_key", "=like", "ops:%"),
            ]), 1)

    def test_une_projection_livree_est_reveillee_par_un_nouvel_etat(self):
        reference = self._creer_dossier()
        projections = self._projeter()
        self._accuser(projections)
        self.assertEqual(self._lignes("freight_dossier").state, "delivered")

        # Un encaissement change l'état du dossier : il doit repartir.
        self._encaisser(reference)
        ligne = self._lignes("freight_dossier")
        self.assertEqual(len(ligne), 1)
        self.assertEqual(ligne.state, "pending")

    # ─── L'onglet ────────────────────────────────────────────────────

    def test_un_dossier_aerien_vise_la_saisie_aerienne(self):
        self._creer_dossier(self.air)
        projection = self._projeter()[0]
        self.assertEqual(projection["sheet"], "Saisie aérien")

    def test_un_dossier_maritime_vise_la_saisie_maritime(self):
        self._creer_dossier(self.sea)
        projection = self._projeter()[0]
        self.assertEqual(projection["sheet"], "Saisie maritime")
        self.assertNotEqual(projection["sheet"], "Saisie aérien")

    # ─── Identités ───────────────────────────────────────────────────

    def test_la_projection_porte_les_identites_techniques_existantes(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        identite = self._projeter()[0]["identity"]
        self.assertEqual(identite["sync_source_key"], shipment.sync_source_key)
        self.assertEqual(identite["global_external_reference"], reference)
        self.assertEqual(identite["intake_consolidation_ref"], self.air.name)
        self.assertEqual(identite["collection_local_ref"], shipment.collection_local_ref)
        self.assertEqual(identite["shipment_id"], shipment.id)
        self.assertEqual(identite["partner_id"], self.partner.id)

    def test_deux_A001_de_departs_differents_ne_se_confondent_pas(self):
        """L'invariant le plus coûteux à rater.

        `A001` est local à son départ. Deux consolidations en ont chacune un, et
        les confondre mélangerait les colis de deux clients.
        """
        # Deux départs **neufs** : chacun attribue son propre A001. Les
        # séquences PostgreSQL ne se rembobinent pas entre deux tests, d'où
        # des consolidations créées ici plutôt que dans la classe.
        c1 = self._consolidation("AIR-DSS-CDG-SHEET-C1-%s" % uuid.uuid4().hex[:6], "air")
        c2 = self._consolidation("AIR-DSS-CDG-SHEET-C2-%s" % uuid.uuid4().hex[:6], "air")
        premier = self._creer_dossier(c1)
        second = self._creer_dossier(c2)
        projections = self._projeter()
        self.assertEqual(len(projections), 2)

        locales = {p["identity"]["collection_local_ref"] for p in projections}
        globales = {p["identity"]["global_external_reference"] for p in projections}
        cles = {p["business_key"] for p in projections}
        # Même référence locale, identités globales et clés distinctes.
        self.assertEqual(locales, {"A001"})
        self.assertEqual(len(globales), 2)
        self.assertEqual(len(cles), 2)
        self.assertIn(premier, globales)
        self.assertIn(second, globales)

    def test_aucune_projection_n_utilise_A001_comme_cle(self):
        self._creer_dossier(self.air)
        for ligne in self._lignes("freight_dossier"):
            self.assertNotEqual(ligne.business_key, "A001")
            self.assertNotIn(ligne.business_key, ("A001", "A002"))

    # ─── La référence visible du dossier ─────────────────────────────

    def _dossier_ancien(self, reference):
        """Un dossier antérieur aux conventions d'identité d'Ops.

        Ni `sync_source_key`, ni `collection_local_ref`, ni consolidation
        d'entrée : exactement la forme des dossiers repris du classeur
        historique, que la projection doit continuer de nommer.
        """
        return self.env["dally.shipment"].sudo().create({
            "partner_id": self.partner.id,
            "company_id": self.societe.id,
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
        })

    def _projection_de(self, shipment):
        """La projection réelle de ce dossier, transport compris."""
        self._boite().enqueue_dossier(shipment)
        for projection in self._projeter():
            if projection["identity"]["shipment_id"] == shipment.id:
                return projection
        self.fail("aucune projection produite pour ce dossier")

    def test_un_dossier_ancien_projette_sa_reference_globale(self):
        """La régression : un dossier sans référence locale perdait son nom.

        La projection écrit la colonne dossier du classeur sans condition.
        Y envoyer une chaîne vide efface la référence visible d'une ligne
        reprise du classeur historique — et avec elle ce que les formules du
        classeur lisent dans cette colonne.
        """
        ancien = self._dossier_ancien("A012")
        self.assertFalse(ancien.collection_local_ref)
        self.assertFalse(ancien.sync_source_key)

        projection = self._projection_de(ancien)

        self.assertEqual(projection["dossier"]["reference"], "A012")

    def test_un_dossier_moderne_garde_sa_reference_locale(self):
        """La référence locale reste prioritaire, et ne devient pas globale.

        Le repli ne doit jamais promouvoir la référence globale : le classeur
        affiche `A001` dans sa colonne dossier, pas
        `AIR-DSS-CDG-SHEET-001-A001`.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        self.assertTrue(shipment.collection_local_ref)

        projection = self._projeter()[0]

        self.assertEqual(
            projection["dossier"]["reference"], shipment.collection_local_ref)
        self.assertNotEqual(
            projection["dossier"]["reference"], shipment.external_reference)
        # Et l'identité technique reste ce qu'elle était : le repli d'affichage
        # ne déteint pas sur la clé globale.
        self.assertEqual(
            projection["identity"]["global_external_reference"],
            shipment.external_reference)
        self.assertEqual(
            projection["identity"]["collection_local_ref"],
            shipment.collection_local_ref)

    def test_un_dossier_sans_identite_visible_ne_fabrique_aucune_reference(self):
        """Aucune référence n'est inventée : mieux vaut vide que faux.

        Fabriquer un nom — un identifiant interne, un horodatage — ferait
        entrer dans le classeur une valeur qu'aucun humain ne reconnaîtrait,
        et qu'aucun rapprochement ne retrouverait.
        """
        ancien = self._dossier_ancien("A013-SANS-IDENTITE")
        self._boite().enqueue_dossier(ancien)
        # L'intention est inscrite ; le dossier perd ensuite sa seule
        # référence visible. Rien ne doit la remplacer.
        ancien.write({"external_reference": False})

        projection = [p for p in self._projeter()
                      if p["identity"]["shipment_id"] == ancien.id][0]

        self.assertEqual(projection["dossier"]["reference"], "")
        self.assertEqual(projection["identity"]["global_external_reference"], "")

    def test_la_reference_affichee_suit_la_cle_metier_dun_dossier_ancien(self):
        """Transport et affichage disent la même chose du même dossier.

        La boîte d'envoi retient `A012` comme clé métier ; il serait
        incompréhensible que la ligne projetée, elle, s'affiche sans nom.
        """
        ancien = self._dossier_ancien("A014")
        ligne = self._boite().enqueue_dossier(ancien)
        self.assertEqual(ligne.business_key, "A014")

        projection = [p for p in self._projeter()
                      if p["identity"]["shipment_id"] == ancien.id][0]

        self.assertEqual(projection["business_key"], "A014")
        self.assertEqual(projection["dossier"]["reference"], "A014")

    # ─── Articles ────────────────────────────────────────────────────

    def test_un_dossier_multi_articles_projette_une_ligne_par_article(self):
        reference = self._creer_dossier()
        service = (self.env["dally.ops.intake.line.service"]
                   .with_user(self.gilles).with_company(self.societe))
        for description in ("Riz", "Huile"):
            service.add_line(reference, {
                "request_uuid": str(uuid.uuid4()),
                "line": {
                    "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                    "goods_category": "Non alimentaire", "description": description,
                    "quantity": 2, "announced_weight_kg": None,
                    "exact_weight_kg": 10.0, "length_cm": None, "width_cm": None,
                    "height_cm": None, "billing_method": "real",
                    "tariff_family_code": self.familles["non_food"].code,
                    "customs_value_xof": 10000,
                },
            })
        projection = self._projeter()[0]
        self.assertEqual(len(projection["articles"]), 3)
        cles = [a["article_key"] for a in projection["articles"]]
        # Chaque article a sa propre clé, et aucune n'est vide.
        self.assertEqual(len(set(cles)), 3)
        self.assertTrue(all(cles))

    def test_un_rejeu_ne_multiplie_pas_les_articles(self):
        reference = self._creer_dossier()
        service = (self.env["dally.ops.intake.line.service"]
                   .with_user(self.gilles).with_company(self.societe))
        demande = {
            "request_uuid": str(uuid.uuid4()),
            "line": {
                "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                "goods_category": "Non alimentaire", "description": "Riz",
                "quantity": 2, "announced_weight_kg": None, "exact_weight_kg": 10.0,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "billing_method": "real",
                "tariff_family_code": self.familles["non_food"].code,
                "customs_value_xof": 10000,
            },
        }
        service.add_line(reference, demande)
        service.add_line(reference, dict(demande))
        projection = self._projeter()[0]
        self.assertEqual(len(projection["articles"]), 2)

    # ─── Familles tarifaires ─────────────────────────────────────────

    def test_les_cinq_familles_traversent_sans_perte(self):
        attendues = {}
        for code in ("food", "seafood", "honey", "clothing", "non_food"):
            reference = self._creer_dossier(famille=code)
            attendues[reference] = code
        projections = self._projeter()
        obtenues = {
            p["identity"]["global_external_reference"]:
                p["articles"][0]["tariff_family_code"]
            for p in projections
        }
        self.assertEqual(obtenues, attendues)

    def test_la_famille_est_un_code_jamais_un_libelle(self):
        self._creer_dossier(famille="seafood")
        article = self._projeter()[0]["articles"][0]
        self.assertEqual(article["tariff_family_code"], "seafood")
        self.assertNotIn(article["tariff_family_code"], ("Halieutiques", ""))

    # ─── Valeurs métier ──────────────────────────────────────────────

    def test_la_projection_porte_le_prix_odoo_et_la_valeur_douaniere(self):
        self._creer_dossier()
        article = self._projeter()[0]["articles"][0]
        self.assertEqual(article["customs_value_xof"], 25000)
        self.assertEqual(article["exact_weight_kg"], 13.5)
        self.assertEqual(article["applied_unit_price_eur"], 5.0)
        self.assertEqual(article["transport_amount_eur"], 67.5)

    # ─── Encaissements ───────────────────────────────────────────────

    def _encaisser(self, reference, montant=100000.0, wave="TWSHEET001"):
        return (self.env["dally.ops.wave.payment.service"]
                .with_user(self.gilles).with_company(self.societe)
                .record_wave_payment(reference, {
                    "request_uuid": str(uuid.uuid4()),
                    "amount": montant, "currency": "XOF",
                    "wave_reference": wave, "paid_at": "2026-08-29", "note": "",
                }))

    def test_un_encaissement_wave_est_projete_sur_la_ligne_du_dossier(self):
        reference = self._creer_dossier()
        self._encaisser(reference)
        projection = self._projeter()[0]
        self.assertEqual(len(projection["payments"]), 1)
        paiement = projection["payments"][0]
        self.assertEqual(paiement["amount_xof"], 100000.0)
        self.assertEqual(paiement["amount_eur"], 0)
        self.assertEqual(paiement["payment_method"], "wave")
        self.assertEqual(paiement["collected_by"], "Gilles")
        self.assertEqual(paiement["wave_reference"], "TWSHEET001")
        collection = self.env["dally.freight.collection"].sudo().search([
            ("shipment_id", "=", self._shipment(reference).id),
            ("state", "!=", "cancelled"),
        ], limit=1)
        self.assertTrue(collection)
        self.assertEqual(
            paiement["payment_key"],
            collection.external_payment_key,
        )

    def test_deux_paiements_partiels_restent_deux_lignes(self):
        reference = self._creer_dossier()
        self._encaisser(reference, 100000.0, "TWPART001")
        self._encaisser(reference, 50000.0, "TWPART002")
        paiements = self._projeter()[0]["payments"]
        self.assertEqual(len(paiements), 2)
        self.assertEqual(sorted(p["amount_xof"] for p in paiements), [50000.0, 100000.0])
        # Deux clés distinctes : aucune ne remplacera l'autre dans le classeur.
        self.assertEqual(len({p["payment_key"] for p in paiements}), 2)

    def test_un_encaissement_rejoue_ne_produit_pas_deux_paiements(self):
        reference = self._creer_dossier()
        demande = {
            "request_uuid": str(uuid.uuid4()), "amount": 100000.0,
            "currency": "XOF", "wave_reference": "TWREPLAY1",
            "paid_at": "2026-08-29", "note": "",
        }
        service = (self.env["dally.ops.wave.payment.service"]
                   .with_user(self.gilles).with_company(self.societe))
        service.record_wave_payment(reference, demande)
        service.record_wave_payment(reference, dict(demande))
        self.assertEqual(len(self._projeter()[0]["payments"]), 1)

    # ─── Annulation d'un encaissement ────────────────────────────────

    def _collections(self, reference):
        return self.env["dally.freight.collection"].sudo().search(
            [("shipment_id", "=", self._shipment(reference).id)],
            order="id asc")

    def test_un_encaissement_actif_annonce_son_etat(self):
        """Sans état déclaré, le classeur ne peut pas distinguer les deux cas."""
        reference = self._creer_dossier()
        self._encaisser(reference)
        paiement = self._projeter()[0]["payments"][0]
        self.assertIn("state", paiement)
        self.assertNotEqual(paiement["state"], "cancelled")

    def test_un_encaissement_annule_reste_projete_avec_son_identite(self):
        """Le cœur du sujet : disparaître n'est pas dire « annulé ».

        Tant que la projection se contente d'omettre la collecte annulée, le
        classeur garde une clé qu'Odoo ne revendique plus — et la garde
        d'identité y voit à juste titre une contradiction permanente.
        """
        reference = self._creer_dossier()
        self._encaisser(reference)
        collection = self._collections(reference)
        cle = collection.external_payment_key
        collection.write({"state": "cancelled"})

        paiements = self._projeter()[0]["payments"]
        self.assertEqual(len(paiements), 1)
        self.assertEqual(paiements[0]["payment_key"], cle)
        self.assertEqual(paiements[0]["state"], "cancelled")

    def test_la_projection_dun_paiement_annule_garde_son_montant_historique(self):
        """La projection décrit Odoo ; c'est le classeur qui neutralise.

        Effacer le montant ici ferait mentir la projection sur l'état d'Odoo,
        et rendrait l'annulation indistinguable d'un encaissement à zéro.
        """
        reference = self._creer_dossier()
        self._encaisser(reference, 100000.0)
        self._collections(reference).write({"state": "cancelled"})
        paiement = self._projeter()[0]["payments"][0]
        self.assertEqual(paiement["amount_xof"], 100000.0)
        self.assertEqual(paiement["currency_code"], "XOF")

    def test_un_encaissement_annule_ne_libere_jamais_sa_cle(self):
        """Un nouvel encaissement porte sa propre identité, jamais l'ancienne."""
        reference = self._creer_dossier()
        self._encaisser(reference, 100000.0, "TWANNUL1")
        ancienne = self._collections(reference)
        cle_annulee = ancienne.external_payment_key
        ancienne.write({"state": "cancelled"})
        self._encaisser(reference, 50000.0, "TWANNUL2")

        paiements = self._projeter()[0]["payments"]
        self.assertEqual(len(paiements), 2)
        par_cle = {p["payment_key"]: p for p in paiements}
        self.assertEqual(len(par_cle), 2)
        self.assertEqual(par_cle[cle_annulee]["state"], "cancelled")
        active = [p for p in paiements if p["payment_key"] != cle_annulee][0]
        self.assertNotEqual(active["state"], "cancelled")
        self.assertEqual(active["amount_xof"], 50000.0)

    def test_reprojeter_une_annulation_rend_toujours_la_meme_charge(self):
        """Le rejeu doit être sans surprise : même clé, même état."""
        reference = self._creer_dossier()
        self._encaisser(reference)
        self._collections(reference).write({"state": "cancelled"})
        shipment = self._shipment(reference)

        premiere = self._projeter()
        self._accuser(premiere)
        self._boite().enqueue_dossier(shipment)
        seconde = self._projeter()

        self.assertEqual(len(self._lignes("freight_dossier")), 1)
        self.assertEqual(premiere[0]["payments"], seconde[0]["payments"])

    def test_un_dossier_sans_encaissement_projette_une_liste_vide(self):
        self._creer_dossier()
        self.assertEqual(self._projeter()[0]["payments"], [])

    # ─── L'annulation réveille la projection ─────────────────────────

    def test_annuler_un_encaissement_reveille_la_projection(self):
        """Le défaut central : sans réveil, la pierre tombale attend.

        Une annulation qui ne réveille pas la boîte d'envoi laisse le classeur
        afficher un encaissement qu'Odoo a désavoué, jusqu'à ce qu'un
        événement étranger — un article, une facture — reprojette le dossier.
        Odoo fait autorité : l'annulation elle-même doit inscrire l'intention.
        """
        reference = self._creer_dossier()
        self._encaisser(reference)
        self._accuser(self._projeter())
        ligne = self._lignes("freight_dossier")
        self.assertEqual(ligne.state, "delivered")

        collection = self._collections(reference)
        collection.action_cancel_from_sync()

        self.assertEqual(collection.state, "cancelled")
        self.assertEqual(ligne.state, "pending")

    def test_annuler_inscrit_la_projection_quand_elle_a_disparu(self):
        reference = self._creer_dossier()
        self._encaisser(reference)
        collection = self._collections(reference)
        self._lignes("freight_dossier").unlink()
        self.assertFalse(self._lignes("freight_dossier"))

        collection.action_cancel_from_sync()

        lignes = self._lignes("freight_dossier")
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes.state, "pending")

    def test_rejouer_une_annulation_ne_cree_pas_une_seconde_intention(self):
        reference = self._creer_dossier()
        self._encaisser(reference)
        collection = self._collections(reference)
        collection.action_cancel_from_sync()
        collection.action_cancel_from_sync()
        self.assertEqual(len(self._lignes("freight_dossier")), 1)

    def test_deux_encaissements_annules_ne_donnent_quune_intention(self):
        """Un dossier se projette d'un bloc : deux annulations, une intention."""
        reference = self._creer_dossier()
        self._encaisser(reference, 100000.0, "TWDEUX001")
        self._encaisser(reference, 50000.0, "TWDEUX002")
        collections = self._collections(reference)
        self.assertEqual(len(collections), 2)
        self._accuser(self._projeter())

        collections.action_cancel_from_sync()

        lignes = self._lignes("freight_dossier")
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes.state, "pending")
        self.assertEqual(
            {p["state"] for p in self._projeter()[0]["payments"]}, {"cancelled"})

    def test_le_compteur_de_tentatives_survit_a_lannulation(self):
        """L'historique des échecs de transport n'est pas effacé par l'annulation.

        Le remettre à zéro ferait repartir le palier de reprise au minimum et
        masquerait un transport durablement en peine.
        """
        reference = self._creer_dossier()
        self._encaisser(reference)
        self._accuser(self._projeter(), ok=False, erreur="Google indisponible")
        ligne = self._lignes("freight_dossier")
        tentatives = ligne.attempt_count
        self.assertTrue(tentatives)

        self._collections(reference).action_cancel_from_sync()

        self.assertEqual(ligne.attempt_count, tentatives)
        self.assertEqual(ligne.state, "pending")
        self.assertFalse(ligne.last_error)

    def test_un_paiement_comptabilise_refuse_lannulation_sans_rien_inscrire(self):
        """`super()` reste l'autorité : son refus ne laisse aucune trace.

        Le refus se rattrape à la main plutôt qu'avec `assertRaises` : celui
        d'Odoo enveloppe le bloc dans un `savepoint` et le rembobine dès que
        l'exception attendue survient. Une inscription faite **avant** l'appel
        à `super()` serait annulée avec elle, et le test la manquerait —
        mesuré : sous `assertRaises`, la mutation « inscrire avant `super()` »
        passe inaperçue.
        """
        reference = self._creer_dossier()
        self._encaisser(reference)
        collection = self._collections(reference)
        paiement = self.env["account.payment"].sudo().create({
            "payment_type": "inbound", "partner_type": "customer",
            "partner_id": self.partner.id, "amount": 100.0,
            "journal_id": self.company_data["default_journal_bank"].id,
        })
        collection.write({"payment_id": paiement.id})
        self._accuser(self._projeter())
        ligne = self._lignes("freight_dossier")
        self.assertEqual(ligne.state, "delivered")

        try:
            collection.action_cancel_from_sync()
        except UserError:
            pass
        else:
            self.fail("un encaissement comptabilisé doit refuser l'annulation")

        self.assertNotEqual(collection.state, "cancelled")
        self.assertEqual(
            ligne.state, "delivered",
            "un refus métier ne doit réveiller aucune projection")

    def test_lannulation_inscrit_apres_super_jamais_avant(self):
        """L'ordre est la garantie, et il se lit dans le code.

        La transaction seule ne suffit pas à le prouver : selon l'endroit d'où
        l'annulation est appelée, un rembobinage peut masquer une inscription
        prématurée. On fixe donc aussi l'ordre à la source.
        """
        from odoo.addons.dally_ops_mobile.models import ops_sheet_outbox
        surcharge = code_seul(
            ops_sheet_outbox.DallyFreightCollection.action_cancel_from_sync)
        self.assertLess(
            surcharge.index("super()"), surcharge.index("enqueue_dossier"),
            "l'inscription doit suivre `super()`, jamais le précéder")

    def test_lannulation_inscrit_la_meme_cle_metier_que_le_dossier(self):
        reference = self._creer_dossier()
        self._encaisser(reference)
        shipment = self._shipment(reference)
        self._lignes("freight_dossier").unlink()

        self._collections(reference).action_cancel_from_sync()

        ligne = self._lignes("freight_dossier")
        self.assertEqual(ligne.business_key, shipment.sync_source_key)
        self.assertEqual(ligne.resource_model, "dally.shipment")
        self.assertEqual(ligne.resource_id, shipment.id)
        self.assertEqual(ligne.resource_reference, shipment.external_reference)

    def test_lannulation_reprend_le_repli_de_cle_des_dossiers_anciens(self):
        """Les dossiers antérieurs à `sync_source_key` restent projetables.

        `sync_source_key` est immuable une fois la collecte allouée — on ne
        peut donc pas le retirer d'un dossier Ops, et il ne faut pas essayer.
        Le repli concerne les dossiers plus anciens que cette convention :
        c'est un tel dossier qu'on reconstitue ici.
        """
        ancien = self.env["dally.shipment"].sudo().create({
            "partner_id": self.partner.id,
            "company_id": self.societe.id,
            "external_reference": "AIR-LEGACY-SHEET-0001",
            "transport_mode": "air",
            "direction": "export",
        })
        self.assertFalse(ancien.sync_source_key)
        collection = self.env["dally.freight.collection"].sudo().create({
            "external_payment_key": "AIR-LEGACY-SHEET-0001|P|1",
            "shipment_id": ancien.id,
            "amount": 100000.0,
            "currency_id": self.xof.id,
            "payment_date": "2026-08-29",
            "source_method": "wave",
        })
        self.assertFalse(self._lignes("freight_dossier").filtered(
            lambda ligne: ligne.resource_id == ancien.id))

        collection.action_cancel_from_sync()

        ligne = self._lignes("freight_dossier").filtered(
            lambda ligne: ligne.resource_id == ancien.id)
        self.assertEqual(len(ligne), 1)
        self.assertEqual(ligne.business_key, ancien.external_reference)
        self.assertEqual(ligne.state, "pending")

    def test_lannulation_ne_fabrique_aucune_cle_de_son_cote(self):
        """La surcharge délègue : elle ne recalcule jamais une identité.

        C'est ce qui garantit que le repli, les champs de ressource et
        l'idempotence restent ceux d'`enqueue_dossier` — une seconde règle de
        clé, même identique aujourd'hui, divergerait un jour.
        """
        from odoo.addons.dally_ops_mobile.models import ops_sheet_outbox
        surcharge = code_seul(ops_sheet_outbox.DallyFreightCollection)
        self.assertIn("enqueue_dossier", surcharge)
        for interdit in ("business_key", "sync_source_key",
                         "collection_local_ref", "resource_model"):
            self.assertNotIn(interdit, surcharge)

    def test_lannulation_n_ouvre_aucune_connexion_reseau(self):
        """Une annulation ne doit jamais dépendre de Google pour aboutir.

        C'est toute la raison d'être de la boîte d'envoi : la transaction
        métier écrit l'intention, et le transport vient plus tard.
        """
        from odoo.addons.dally_ops_mobile.models import ops_sheet_outbox
        code = code_seul(ops_sheet_outbox)
        for primitive in ("requests", "urllib", "urlopen", "http",
                          "socket", "UrlFetch"):
            self.assertNotIn(primitive, code)

    # ─── Facture ─────────────────────────────────────────────────────

    def test_le_numero_de_facture_met_a_jour_le_dossier_sans_nouvelle_ligne(self):
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        projections = self._projeter()
        self._accuser(projections)
        self.assertEqual(projections[0]["identity"]["invoice_number"], "")

        facture = self.env["account.move"].sudo().create({
            "move_type": "out_invoice", "partner_id": self.partner.id,
            "company_id": self.societe.id, "invoice_date": "2026-08-29",
            "currency_id": self.eur.id,
        })
        shipment.sudo().write({"invoice_id": facture.id})
        self._boite().enqueue_dossier(shipment)

        # La même ligne repart ; aucune seconde intention n'est créée.
        self.assertEqual(len(self._lignes("freight_dossier")), 1)
        suivantes = self._projeter()
        self.assertEqual(len(suivantes), 1)
        self.assertEqual(suivantes[0]["identity"]["invoice_id"], facture.id)
        self.assertEqual(suivantes[0]["identity"]["invoice_number"], "Brouillon")
        self.assertEqual(
            suivantes[0]["business_key"], projections[0]["business_key"])

    # ─── Dépenses et transferts ──────────────────────────────────────

    def _depenser(self, wave=None):
        return (self.env["dally.ops.expense.service"]
                .with_user(self.gilles).with_company(self.societe)
                .record_expense({
                    "request_uuid": str(uuid.uuid4()),
                    "consolidation_reference": self.air.name,
                    "expense_date": "2026-08-29", "category": "Manutention",
                    "description": "Portage", "beneficiary": "Équipe",
                    "amount": 15000.0, "currency_code": "XOF",
                    "payment_method": "cash", "comment": "",
                }))

    def test_une_depense_est_projetee_vers_son_onglet(self):
        self._depenser()
        lignes = self._lignes("cash_expense")
        self.assertEqual(len(lignes), 1)
        projection = [p for p in self._projeter()
                      if p["projection_type"] == "cash_expense"][0]
        self.assertEqual(projection["sheet"], "Dépenses")
        depense = projection["expense"]
        self.assertTrue(depense["external_expense_key"].startswith("ops:"))
        self.assertEqual(depense["total_amount"], 15000.0)
        self.assertEqual(depense["currency_code"], "XOF")
        self.assertEqual(depense["allocations"], [{"actor": "Gilles", "amount": 15000.0}])
        self.assertEqual(depense["consolidation_reference"], self.air.name)

    def test_une_depense_de_tableur_sans_depart_reste_projetable(self):
        """Le champ `consolidation_reference` n'est jamais obligatoire.

        Les lignes historiques n'ont pas de départ et n'en auront jamais ;
        l'exiger refuserait des dépenses parfaitement exactes.
        """
        depense, _cree = (self.env["dally.cash.expense"].sudo()
                          .with_company(self.societe)
                          .upsert_from_sync(
                              {"external_expense_key": "sheet:legacy:1",
                               "expense_date": "2026-08-20", "category": "Gasoil",
                               "description": "Carburant",
                               "currency_id": self.xof.id,
                               "source": "google_sheets"},
                              [{"actor_name": "Papa", "amount": 30000.0}]))
        ligne = self._boite().enqueue(
            "cash_expense", depense.external_expense_key, depense)
        projection = ligne._projection()
        self.assertEqual(projection["expense"]["consolidation_reference"], "")
        self.assertEqual(projection["expense"]["total_amount"], 30000.0)

    def test_un_transfert_est_projete_vers_son_onglet(self):
        (self.env["dally.ops.cash.transfer.service"]
         .with_user(self.gilles).with_company(self.societe)
         .record_transfer({
             "request_uuid": str(uuid.uuid4()), "to_actor": "Dalanda",
             "transfer_date": "2026-08-29", "amount": 100000.0,
             "currency_code": "XOF", "payment_method": "cash",
             "reason": "Remise du soir", "comment": "",
         }))
        projection = [p for p in self._projeter()
                      if p["projection_type"] == "cash_transfer"][0]
        self.assertEqual(projection["sheet"], "Transferts caisse")
        transfert = projection["transfer"]
        self.assertEqual(transfert["from_actor"], "Gilles")
        self.assertEqual(transfert["to_actor"], "Dalanda")
        self.assertEqual(transfert["amount"], 100000.0)
        self.assertTrue(transfert["external_transfer_key"].startswith("ops:"))

    def test_un_transfert_ne_devient_jamais_un_paiement_ni_une_depense(self):
        (self.env["dally.ops.cash.transfer.service"]
         .with_user(self.gilles).with_company(self.societe)
         .record_transfer({
             "request_uuid": str(uuid.uuid4()), "to_actor": "Dalanda",
             "transfer_date": "2026-08-29", "amount": 100000.0,
             "currency_code": "XOF", "payment_method": "cash",
             "reason": "Remise", "comment": "",
         }))
        types = self._lignes().mapped("projection_type")
        self.assertEqual(types, ["cash_transfer"])
        self.assertEqual(len(self._lignes("cash_expense")), 0)
        self.assertEqual(len(self._lignes("freight_dossier")), 0)

    def test_une_depense_et_un_transfert_rejoues_restent_uniques(self):
        service_depense = (self.env["dally.ops.expense.service"]
                           .with_user(self.gilles).with_company(self.societe))
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "consolidation_reference": self.air.name,
            "expense_date": "2026-08-29", "category": "Manutention",
            "description": "Portage", "beneficiary": "", "amount": 15000.0,
            "currency_code": "XOF", "payment_method": "cash", "comment": "",
        }
        service_depense.record_expense(charge)
        service_depense.record_expense(dict(charge))
        self.assertEqual(len(self._lignes("cash_expense")), 1)

        service_transfert = (self.env["dally.ops.cash.transfer.service"]
                             .with_user(self.gilles).with_company(self.societe))
        remise = {
            "request_uuid": str(uuid.uuid4()), "to_actor": "Dalanda",
            "transfer_date": "2026-08-29", "amount": 100000.0,
            "currency_code": "XOF", "payment_method": "cash",
            "reason": "Remise", "comment": "",
        }
        service_transfert.record_transfer(remise)
        service_transfert.record_transfer(dict(remise))
        self.assertEqual(len(self._lignes("cash_transfer")), 1)

    # ─── Le transport ────────────────────────────────────────────────

    def test_une_panne_de_transport_ne_defait_jamais_le_metier(self):
        """La propriété qui justifie toute la boîte d'envoi."""
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        projections = self._projeter()
        self._accuser(projections, ok=False, erreur="google indisponible")

        # Le dossier existe toujours, avec son numéro serveur.
        self.assertTrue(shipment.exists())
        self.assertEqual(shipment.external_reference, reference)
        self.assertEqual(len(shipment.package_ids), 1)
        # Et l'intention attend son heure.
        ligne = self._lignes("freight_dossier")
        self.assertEqual(ligne.state, "retry")
        self.assertEqual(ligne.last_error, "google indisponible")
        self.assertGreaterEqual(ligne.attempt_count, 1)

    def test_une_reprise_espace_les_tentatives(self):
        self._creer_dossier()
        premiere = self._projeter()
        self._accuser(premiere, ok=False, erreur="réseau")
        ligne = self._lignes("freight_dossier")
        # Le second palier place la reprise dans le futur.
        self.assertGreater(ligne.next_attempt_at, ligne.last_attempt_at)
        self.assertEqual(self._projeter(), [])

    def test_un_accuse_perdu_se_rejoue_sans_dommage(self):
        """Le classeur a été écrit, l'accusé s'est perdu.

        Le second passage refait un UPSERT sur la même ligne — la clé métier
        n'a pas bougé — et l'accusé finit par être accepté.
        """
        reference = self._creer_dossier()
        premier = self._projeter()
        cle = premier[0]["business_key"]
        # L'accusé n'arrive jamais : la ligne est reprise après expiration.
        self._boite().search([]).write({
            "last_attempt_at": "2020-01-01 00:00:00"})
        self.assertEqual(self._boite().release_stale(), 1)
        second = self._projeter()
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["business_key"], cle)
        self.assertEqual(
            second[0]["identity"]["global_external_reference"], reference)

        self._accuser(second)
        self.assertEqual(self._lignes("freight_dossier").state, "delivered")
        # Un accusé rejoué sur une ligne déjà livrée reste inoffensif.
        self._accuser(second)
        self.assertEqual(self._lignes("freight_dossier").state, "delivered")

    def test_une_erreur_permanente_ne_bloque_pas_les_autres(self):
        self._creer_dossier(self.air)
        self._creer_dossier(self.air2)
        projections = self._projeter()
        self.assertEqual(len(projections), 2)
        self._boite().acknowledge(self.societe, [
            {"outbox_id": projections[0]["outbox_id"], "ok": False,
             "permanent": True, "error": "ligne invalide"},
            {"outbox_id": projections[1]["outbox_id"], "ok": True},
        ])
        etats = sorted(self._lignes("freight_dossier").mapped("state"))
        self.assertEqual(etats, ["delivered", "failed"])
        # La ligne en échec n'est plus servie : elle n'occupe plus le transport.
        self.assertEqual(self._projeter(), [])

    def test_le_retrait_didentite_terminalise_loutbox_obsolete(self):
        for etat in ("pending", "retry", "processing"):
            with self.subTest(etat=etat):
                self._boite().search([]).unlink()
                reference = self._creer_dossier()
                shipment = self._shipment(reference)
                ancienne_reference = shipment.external_reference
                ancienne_locale = shipment.collection_local_ref
                ligne = self._lignes("freight_dossier")
                self.assertEqual(len(ligne), 1)
                ligne.write({"state": etat, "last_error": False})
                if etat == "processing":
                    ligne.write({"last_attempt_at": "2026-09-03 00:00:00"})
                nombre_avant = len(self._lignes("freight_dossier"))
                shipment.action_cancel()
                messages_avant = len(shipment.message_ids)

                self.env["dally.freight.intake.identity.recovery"].apply(
                    [shipment.id],
                    expected=self._recovery_expected(shipment),
                    database=self.env.cr.dbname,
                )

                self.assertEqual(len(self._lignes("freight_dossier")), nombre_avant)
                self.assertTrue(shipment.exists())
                self.assertEqual(shipment.state, "cancelled")
                self.assertEqual(ligne.state, "failed")
                self.assertIn("intake_identity_retired:%s" % ancienne_reference, ligne.last_error)
                self.assertGreater(len(shipment.message_ids), messages_avant)
                self.assertEqual(self._projeter(), [])
                projection = ligne._projection()
                self.assertNotEqual(
                    projection["identity"]["global_external_reference"],
                    ancienne_reference,
                )
                self.assertNotEqual(projection["dossier"]["reference"], ancienne_locale)

    def test_apply_rolls_back_every_change_when_late_step_fails(self):
        """Une réparation partielle serait pire que pas de réparation.

        Le service mute plusieurs choses : la boîte d'envoi, le chargement, le
        plan de départ, l'identité, le chatter. Si l'une des dernières étapes
        échoue, tout doit disparaître — un départ délesté de ses colis mais
        gardant son identité d'origine serait un état que personne n'a voulu et
        que rien ne décrit.

        ## Trois précautions sans lesquelles ce test serait un faux vert

        **La frontière de rollback.** `assertRaises` autour d'`apply` ne prouve
        rien : l'exception serait capturée dans la même transaction et les
        écritures resteraient. Le `savepoint` est donc le contexte le plus
        interne, et l'exception doit en **sortir** avant d'être capturée — c'est
        à sa sortie que PostgreSQL exécute le `ROLLBACK TO SAVEPOINT`. Le
        `try/except` est ici volontairement explicite plutôt qu'un
        `assertRaises` englobant : l'ordre est le sujet du test.

        **La confirmation avant l'échec.** La fonction injectée vérifie que les
        mutations sont réellement visibles avant de lever. Si `apply` échouait
        plus tôt un jour, un test naïf verrait « rien n'a changé » et se
        déclarerait vert sans rien prouver.

        **La relecture.** Après le rollback, plus rien n'est lu depuis un
        recordset ayant traversé la transaction : cache vidé, re-browse depuis
        les identifiants capturés, et une lecture SQL brute qui court-circuite
        entièrement l'ORM — seule preuve que c'est bien la base, et non le
        cache, qui a retrouvé son état.
        """
        reference = self._creer_dossier()
        shipment = self._shipment(reference)
        ligne_outbox = self._lignes("freight_dossier")
        self.assertEqual(len(ligne_outbox), 1)
        shipment.action_cancel()

        # L'état initial, en identifiants et en valeurs nues : rien ici ne doit
        # dépendre d'un recordset qui vivra la transaction annulée.
        shipment_id = shipment.id
        outbox_id = ligne_outbox.id
        avant = {
            "outbox_state": ligne_outbox.state,
            "outbox_error": ligne_outbox.last_error,
            "planned": shipment.planned_consolidation_id.id,
            "sequence": shipment.collection_sequence,
            "local_ref": shipment.collection_local_ref,
            "external_reference": shipment.external_reference,
            "sync_source_key": shipment.sync_source_key,
            "state": shipment.state,
            "intake": shipment.intake_consolidation_id.id,
            "lines": {
                l.id: (l.package_id.id, l.quantity_loaded, l.weight_loaded)
                for l in shipment.consolidation_line_ids
            },
            "packages": {
                p.id: (p.description, p.quantity, p.total_weight_kg)
                for p in shipment.package_ids
            },
            "message_ids": set(shipment.message_ids.ids),
        }
        self.assertTrue(avant["lines"], "le dossier doit être chargé, comme en production")
        self.assertTrue(avant["planned"], "le dossier doit être planifié, comme en production")
        self.assertTrue(avant["packages"], "le dossier doit porter au moins un colis")

        observe = {}
        late_failure_reached = []

        def _echec_tardif(service, shipment_mute, archive, detail):
            shipment_mute.invalidate_recordset()
            observe["planned"] = shipment_mute.planned_consolidation_id.id
            observe["lines"] = len(shipment_mute.consolidation_line_ids)
            observe["local_ref"] = shipment_mute.collection_local_ref
            observe["external_reference"] = shipment_mute.external_reference
            observe["messages"] = len(shipment_mute.message_ids)
            observe["outbox_state"] = (
                self.env["dally.ops.sheet.outbox"].sudo()
                .browse(outbox_id).read(["state"])[0]["state"])
            # Confirmation AVANT de lever. Une AssertionError ici se distingue
            # de l'échec injecté : le test tombera dessus au lieu de se croire
            # vert sur une réparation qui n'aurait rien muté.
            assert observe["planned"] is False, "le plan n'a pas été vidé avant l'échec"
            assert observe["lines"] == 0, "le chargement n'a pas été retiré avant l'échec"
            assert observe["local_ref"] != avant["local_ref"], (
                "l'identité d'archive n'a pas été appliquée avant l'échec")
            assert observe["external_reference"] != avant["external_reference"], (
                "la référence globale n'a pas été réécrite avant l'échec")
            assert observe["outbox_state"] == "failed", (
                "l'outbox n'a pas été terminalisée avant l'échec")
            assert observe["messages"] > len(avant["message_ids"]), (
                "la trace chatter n'a pas été posée avant l'échec")
            late_failure_reached.append(True)
            raise UserError("échec injecté après toutes les mutations")

        Service = type(self.env["dally.freight.intake.identity.recovery"])
        attendu = self._recovery_expected(shipment)
        sortie = None
        with patch.object(Service, "_verifier_postconditions", _echec_tardif):
            try:
                # L'exception doit SORTIR de ce contexte : c'est à sa sortie que
                # le ROLLBACK TO SAVEPOINT est émis.
                with self.env.cr.savepoint():
                    self.env["dally.freight.intake.identity.recovery"].apply(
                        [shipment_id], expected=attendu, database=self.env.cr.dbname)
            except UserError as erreur:
                sortie = erreur

        self.assertTrue(late_failure_reached, "le point d'échec tardif n'a jamais été atteint")
        self.assertIsNotNone(sortie, "l'exception n'est pas sortie du savepoint")
        self.assertIn("échec injecté", str(sortie))

        # Relecture stricte : cache vidé, puis re-browse depuis les ids initiaux.
        self.env.invalidate_all()
        dossier = self.env["dally.shipment"].with_context(active_test=False).browse(shipment_id)
        boite = self.env["dally.ops.sheet.outbox"].sudo().browse(outbox_id)
        self.assertTrue(dossier.exists())
        self.assertTrue(boite.exists())

        self.assertEqual(dossier.state, avant["state"])
        self.assertEqual(dossier.intake_consolidation_id.id, avant["intake"])
        self.assertEqual(dossier.planned_consolidation_id.id, avant["planned"])
        self.assertEqual(dossier.collection_sequence, avant["sequence"])
        self.assertEqual(dossier.collection_local_ref, avant["local_ref"])
        self.assertEqual(dossier.external_reference, avant["external_reference"])
        self.assertEqual(dossier.sync_source_key, avant["sync_source_key"])
        self.assertEqual(boite.state, avant["outbox_state"])
        self.assertEqual(boite.last_error, avant["outbox_error"])

        self.assertEqual(
            {l.id: (l.package_id.id, l.quantity_loaded, l.weight_loaded)
             for l in dossier.consolidation_line_ids},
            avant["lines"],
            "les lignes de chargement doivent revenir à l'identique, mêmes ids",
        )
        self.assertEqual(
            {p.id: (p.description, p.quantity, p.total_weight_kg)
             for p in dossier.package_ids},
            avant["packages"],
            "les colis doivent revenir à l'identique, mêmes ids",
        )

        # Le chatter est relu depuis mail.message, pas depuis le dossier.
        messages = self.env["mail.message"].sudo().search([
            ("model", "=", "dally.shipment"), ("res_id", "=", shipment_id),
        ])
        self.assertEqual(set(messages.ids), avant["message_ids"],
                         "aucune trace de réparation ne doit subsister")
        self.assertFalse(
            any("identité de collecte" in (m.body or "").lower() for m in messages),
            "le chatter ne doit porter aucune trace du retrait annulé",
        )

        # La preuve que c'est PostgreSQL qui a rollbacké, et non l'ORM qui
        # relit une valeur restée en cache : on interroge la base directement.
        self.env.cr.execute(
            "SELECT planned_consolidation_id, collection_sequence, "
            "collection_local_ref, external_reference, sync_source_key, state "
            "FROM dally_shipment WHERE id = %s", (shipment_id,))
        brut = self.env.cr.fetchone()
        self.assertEqual(brut[0], avant["planned"])
        self.assertEqual(brut[1], avant["sequence"])
        self.assertEqual(brut[2], avant["local_ref"])
        self.assertEqual(brut[3], avant["external_reference"])
        self.assertEqual(brut[4], avant["sync_source_key"])
        self.assertEqual(brut[5], avant["state"])
        self.env.cr.execute(
            "SELECT id FROM dally_freight_consolidation_line WHERE shipment_id = %s "
            "ORDER BY id", (shipment_id,))
        self.assertEqual(
            [rangee[0] for rangee in self.env.cr.fetchall()],
            sorted(avant["lines"]),
            "les lignes doivent exister en base, pas seulement dans le cache",
        )
        self.env.cr.execute(
            "SELECT state, last_error FROM dally_ops_sheet_outbox WHERE id = %s",
            (outbox_id,))
        brut_boite = self.env.cr.fetchone()
        self.assertEqual(brut_boite[0], avant["outbox_state"])
        # PostgreSQL rend `None` là où l'ORM rend `False` pour un Char vide :
        # on compare l'absence de valeur, pas sa représentation.
        self.assertEqual(brut_boite[1] or False, avant["outbox_error"] or False)

    def test_un_lot_est_borne(self):
        for _index in range(3):
            self._creer_dossier(self.air)
        self.assertLessEqual(len(self._boite().claim_batch(self.societe, 2)), 2)

    def test_deux_transports_ne_se_partagent_pas_la_meme_ligne(self):
        self._creer_dossier(self.air)
        self._creer_dossier(self.air2)
        premier = self._boite().claim_batch(self.societe, 1)
        second = self._boite().claim_batch(self.societe, 1)
        self.assertEqual(len(premier), 1)
        self.assertEqual(len(second), 1)
        # Réservée par le premier passage, la ligne n'est pas resservie.
        self.assertNotEqual(premier[0]["outbox_id"], second[0]["outbox_id"])

    def test_la_projection_est_cloisonnee_par_societe(self):
        self._creer_dossier()
        self.assertEqual(len(self._projeter(self.societe)), 1)
        self.assertEqual(self._boite().claim_batch(self.autre_societe), [])

    # ─── Ce que la projection ne contient pas ────────────────────────

    def test_aucun_secret_ne_traverse_la_projection(self):
        reference = self._creer_dossier()
        self._encaisser(reference)
        self._depenser()
        rendu = json.dumps(self._projeter(), default=str).lower()
        for interdit in ("api_key", "apikey", "password", "secret", "bearer",
                         "otp", "pin", "token", "private_key", "client_secret",
                         "credential", "session_id", "cookie"):
            self.assertNotIn(interdit, rendu)

    def test_l_agenda_n_est_pas_projete(self):
        """L'agenda est hors périmètre du classeur Freight."""
        client = self.env["dally.ops.customer.service"].with_user(
            self.gilles).with_company(self.societe)
        jeton = client.get_or_create_handle(self.partner)
        (self.env["dally.ops.appointment.service"]
         .with_user(self.gilles).with_company(self.societe)
         .create_appointment({
             "request_uuid": str(uuid.uuid4()), "customer_reference": jeton,
             "kind": "dropoff", "start_at": "2026-09-01T09:00:00+00:00",
             "end_at": "2026-09-01T09:30:00+00:00",
             "consolidation_reference": None, "location": "Dépôt", "note": "",
         }))
        self.assertEqual(len(self._lignes()), 0)
        types = set(self._boite().search([]).mapped("projection_type"))
        self.assertNotIn("appointment", types)

    def test_une_ressource_disparue_ne_bloque_pas_la_file(self):
        self._creer_dossier()
        ligne = self._lignes("freight_dossier")
        ligne.write({"resource_id": 999999999})
        self.assertEqual(self._projeter(), [])
        self.assertEqual(ligne.state, "delivered")
        self.assertEqual(ligne.last_error, "resource_missing")


@tagged("post_install", "-at_install", "dally")
class TestOpsSheetOutboxEndpoint(HttpCase):
    """La surface que le connecteur interroge, éprouvée par HTTP réel.

    Le privilège est le point sensible : lire une file d'attente ne doit
    donner ni le droit de créer un dossier, ni celui d'émettre une facture, ni
    celui de toucher à la caisse.
    """

    def setUp(self):
        super().setUp()
        self.billing_user = self.env.ref(
            "dally_freight_billing.user_dally_freight_billing_integration")
        self.cle = self.env["dally.api.key"].create({
            "name": "Sheet Outbox Test Key",
            "scopes": "freight:sheet",
            "allowed_ips": "",
            "user_id": self.billing_user.id,
        })
        self.cle_brute = self.cle.key_to_display

    def _get(self, chemin, cle=None):
        entetes = {}
        valeur = self.cle_brute if cle is None else cle
        if valeur:
            entetes["X-API-Key"] = valeur
        return self.url_open(chemin, headers=entetes, timeout=30)

    def _post(self, chemin, corps, cle=None):
        entetes = {"Content-Type": "application/json"}
        valeur = self.cle_brute if cle is None else cle
        if valeur:
            entetes["X-API-Key"] = valeur
        return self.url_open(
            chemin, data=json.dumps(corps), headers=entetes, timeout=30)

    def test_le_lot_est_servi_a_une_cle_dediee(self):
        reponse = self._get("/api/v1/freight/sheet-outbox")
        self.assertEqual(reponse.status_code, 200, reponse.content[:400])
        charge = json.loads(reponse.content)
        self.assertTrue(charge["success"])
        self.assertIn("projections", charge["data"])
        self.assertIsInstance(charge["data"]["projections"], list)

    def test_sans_cle_la_file_reste_fermee(self):
        self.assertEqual(self._get("/api/v1/freight/sheet-outbox", cle="").status_code, 401)

    def test_une_cle_d_un_autre_perimetre_est_refusee(self):
        """Le scope dédié n'est pas une formalité.

        Une clé de synchronisation Freight ne doit pas pouvoir lire la file de
        projection, et réciproquement.
        """
        autre = self.env["dally.api.key"].create({
            "name": "Sheet Outbox Wrong Scope",
            "scopes": "freight:write",
            "allowed_ips": "",
            "user_id": self.billing_user.id,
        })
        reponse = self._get(
            "/api/v1/freight/sheet-outbox", cle=autre.key_to_display)
        self.assertEqual(reponse.status_code, 403)

    def test_la_cle_de_projection_n_ouvre_pas_les_autres_routes(self):
        for chemin in ("/api/v1/freight/expense", "/api/v1/freight/cash-transfer",
                       "/api/v1/freight/sync"):
            reponse = self._post(chemin, {"request_uuid": str(uuid.uuid4())})
            self.assertEqual(reponse.status_code, 403, chemin)

    def test_un_accuse_refuse_un_champ_inconnu(self):
        reponse = self._post("/api/v1/freight/sheet-outbox/ack", {
            "request_uuid": str(uuid.uuid4()),
            "results": [],
            "sheet_row": 12,
        })
        self.assertEqual(reponse.status_code, 422)

    def test_un_accuse_refuse_un_resultat_mal_forme(self):
        for resultats in ("tout", [{"outbox_id": 1, "row": 3}], [7]):
            reponse = self._post("/api/v1/freight/sheet-outbox/ack", {
                "request_uuid": str(uuid.uuid4()), "results": resultats,
            })
            self.assertEqual(reponse.status_code, 422, resultats)

    def test_un_accuse_sur_une_ligne_inconnue_est_sans_effet(self):
        reponse = self._post("/api/v1/freight/sheet-outbox/ack", {
            "request_uuid": str(uuid.uuid4()),
            "results": [{"outbox_id": 999999999, "ok": True}],
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(json.loads(reponse.content)["data"]["unknown"], 1)

    def test_la_reponse_ne_contient_aucun_secret(self):
        contenu = self._get("/api/v1/freight/sheet-outbox").content.decode().lower()
        for interdit in ("api_key", "password", "secret", "bearer", "private_key",
                         "client_secret", "credential"):
            self.assertNotIn(interdit, contenu)
