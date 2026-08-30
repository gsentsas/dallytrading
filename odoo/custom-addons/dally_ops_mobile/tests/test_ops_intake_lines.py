# -*- coding: utf-8 -*-
"""Un dossier à plusieurs articles, et leurs corrections.

Trois propriétés se jouent ici, et aucune ne se voit sans test.

**La projection reste vraie.** `dally.freight.consolidation.line` porte des
instantanés — quantité, poids, volume au moment du rattachement. Corriger un
colis sans reconstruire cette projection laisserait la consolidation croire
qu'elle transporte ce qui n'y est plus.

**Personne n'écrase personne.** Deux téléphones peuvent afficher le même
article ; celui qui écrit avec une version périmée doit être refusé.

**Le rejeu passe avant le verrou.** Une correction peut réussir, la facture
arriver, puis le téléphone rejouer sa demande : il relit son résultat au lieu
de se heurter à un verrou apparu depuis.
"""

import ast
import inspect
import json
import uuid

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

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
class TestOpsIntakeLines(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.societe = cls.env["res.company"].create({"name": "Ops Lignes SA"})
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Lignes Autre SA"})
        cls.logisticien = cls._compte(
            "lignes.logi", "Gilles Lignes",
            "dally_ops_mobile.group_dally_ops_logistician")
        cls.responsable = cls._compte(
            "lignes.resp", "Dalanda Lignes",
            "dally_ops_mobile.group_dally_ops_supervisor")
        cls.non_ops = cls._compte("lignes.autre", "Sans rôle", "base.group_user")
        cls.logisticien_ailleurs = cls.env["res.users"].create({
            "name": "Gilles Ailleurs", "login": "lignes.ailleurs",
            "group_ids": [(6, 0, [cls.env.ref(
                "dally_ops_mobile.group_dally_ops_logistician").id])],
            "company_id": cls.autre_societe.id,
            "company_ids": [(6, 0, [cls.autre_societe.id])],
        })

        cls.partner = cls.env["res.partner"].create({
            "name": "Aissatou Lignes", "company_id": cls.societe.id,
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.family = cls.env["dally.freight.tariff.family"].create({
            "name": "Lignes Non alimentaire", "code": "lignes_non_food", "sequence": 20,
        })
        cls.family_autre = cls.env["dally.freight.tariff.family"].create({
            "name": "Lignes Alimentaire", "code": "lignes_food", "sequence": 10,
        })
        cls.env["dally.freight.tariff.rule"].create({
            "name": "Lignes air 5 EUR", "transport_mode": "air",
            "family_id": cls.family.id, "customer_segment": "individual",
            "price_per_kg_eur": 5.0, "volumetric_ratio_kg_cbm": 167.0,
        })
        cls.c1 = cls._consolidation("AIR-DSS-CDG-LIG-001")
        cls.c2 = cls._consolidation("AIR-DSS-CDG-LIG-002")

    @classmethod
    def _compte(cls, login, nom, groupe):
        return cls.env["res.users"].create({
            "name": nom, "login": login,
            "group_ids": [(6, 0, [cls.env.ref(groupe).id])],
            "company_id": cls.societe.id,
            "company_ids": [(6, 0, [cls.societe.id])],
        })

    @classmethod
    def _consolidation(cls, reference, **valeurs):
        defauts = {
            "name": reference, "state": "collecting", "active": True,
            "company_id": cls.societe.id, "transport_mode": "air",
            "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        }
        defauts.update(valeurs)
        return cls.env["dally.freight.consolidation"].create(defauts)

    # ─── Fabriques ───────────────────────────────────────────────────

    def _lignes(self, utilisateur=None):
        return (self.env["dally.ops.intake.line.service"]
                .with_user(utilisateur or self.logisticien)
                .with_company(self.societe))

    def _intakes(self, utilisateur=None):
        return (self.env["dally.ops.intake.service"]
                .with_user(utilisateur or self.logisticien)
                .with_company(self.societe))

    def _ligne_saisie(self, **changements):
        ligne = {
            "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
            "goods_category": "Non alimentaire", "description": "Savon",
            "quantity": 1, "announced_weight_kg": None, "exact_weight_kg": 13.5,
            "length_cm": None, "width_cm": None, "height_cm": None,
            "billing_method": "real", "tariff_family_code": self.family.code,
            "customs_value_xof": 25000,
        }
        ligne.update(changements)
        return ligne

    def _creer_dossier(self, consolidation=None, **ligne):
        """Un dossier d'une ligne, par le chemin de l'étape 7."""
        resultat = self._intakes().create_intake({
            "request_uuid": str(uuid.uuid4()),
            "consolidation_reference": (consolidation or self.c1).name,
            "customer_reference": self.handle.token,
            "received_on": "2026-08-28",
            "line": self._ligne_saisie(**ligne),
        })
        return resultat["intake"]["reference"]

    def _shipment(self, reference):
        return self.env["dally.shipment"].sudo().search(
            [("external_reference", "=", reference)], limit=1)

    def _projection(self, colis):
        return self.env["dally.freight.consolidation.line"].sudo().search(
            [("package_id", "=", colis.id)])

    def _colis(self, reference, line_uuid):
        shipment = self._shipment(reference)
        cle = "%s:line:%s" % (shipment.sync_source_key, line_uuid)
        return shipment.package_ids.filtered(
            lambda paquet: paquet.external_line_key == cle)[:1]

    # ─── Lecture du dossier ──────────────────────────────────────────

    def test_le_detail_expose_le_dossier_et_ses_lignes(self):
        # Une consolidation neuve : les séquences PostgreSQL ne se rejouent pas
        # d'un test à l'autre, donc un numéro littéral n'a de sens que sur un
        # départ créé ici.
        depart = self._consolidation("AIR-DSS-CDG-LIG-DETAIL")
        ligne = self._ligne_saisie()
        reference = self._creer_dossier(consolidation=depart, **ligne)
        detail = self._lignes().get_intake(reference)["intake"]

        self.assertEqual(detail["reference"], reference)
        self.assertEqual(detail["local_reference"], "A001")
        self.assertEqual(detail["consolidation_reference"], depart.name)
        self.assertEqual(detail["state"], "goods_received")
        self.assertEqual(len(detail["lines"]), 1)
        self.assertEqual(detail["lines"][0]["reference"], ligne["line_uuid"])
        self.assertTrue(detail["lines"][0]["revision"])

    def test_le_detail_ne_donne_du_client_que_son_nom(self):
        reference = self._creer_dossier()
        detail = self._lignes().get_intake(reference)["intake"]

        self.assertEqual(detail["customer"], {"name": "Aissatou Lignes"})
        # Le comptoir doit reconnaître le dossier, pas consulter une fiche.
        contenu = json.dumps(detail, ensure_ascii=False)
        for interdit in ("phone", "email", "street", "partner_id", "+221"):
            self.assertNotIn(interdit, contenu)

    def test_le_detail_ne_contient_aucun_identifiant_odoo(self):
        reference = self._creer_dossier()
        contenu = json.dumps(self._lignes().get_intake(reference), ensure_ascii=False)
        for interdit in ("shipment_id", "package_id", "consolidation_id",
                         "consolidation_line_id", "tariff_rule_id",
                         "sale_order_id", "invoice_id", "external_line_key",
                         "sync_source_key", "collection_sequence"):
            self.assertNotIn(interdit, contenu)

    def test_un_dossier_d_une_autre_societe_est_introuvable(self):
        reference = self._creer_dossier()
        autre = (self.env["dally.ops.intake.line.service"]
                 .with_user(self.logisticien_ailleurs)
                 .with_company(self.autre_societe))
        with self.assertRaises(DallyOpsNotFound):
            autre.get_intake(reference)

    def test_un_dossier_qui_n_est_pas_ops_est_introuvable(self):
        with self.assertRaises(DallyOpsNotFound):
            self._lignes().get_intake("AIR-DSS-CDG-LIG-001-A999")

    def test_le_detail_annonce_ce_qui_est_modifiable(self):
        reference = self._creer_dossier()
        detail = self._lignes().get_intake(reference)["intake"]
        self.assertTrue(detail["editable"])
        self.assertIsNone(detail["edit_block_reason"])

        self._shipment(reference).sudo().billing_locked = True
        detail = self._lignes().get_intake(reference)["intake"]
        self.assertFalse(detail["editable"])
        self.assertEqual(detail["edit_block_reason"], "billing_locked")

    def test_les_totaux_viennent_du_serveur(self):
        reference = self._creer_dossier(exact_weight_kg=13.5)
        detail = self._lignes().get_intake(reference)["intake"]
        self.assertEqual(detail["totals"]["lines_count"], 1)
        self.assertAlmostEqual(detail["totals"]["weight_kg"], 13.5, places=3)
        self.assertTrue(detail["totals"]["pricing_complete"])
        self.assertAlmostEqual(detail["totals"]["transport_amount_eur"], 67.5, places=2)

    def test_un_total_incomplet_ne_vaut_jamais_zero(self):
        """Afficher 0 € ferait croire à un prix ; il n'y en a pas encore."""
        reference = self._creer_dossier()
        self._lignes().add_line(reference, {
            "request_uuid": str(uuid.uuid4()),
            "line": self._ligne_saisie(description="Sur devis", billing_method="quote"),
        })
        totaux = self._lignes().get_intake(reference)["intake"]["totals"]
        self.assertFalse(totaux["pricing_complete"])
        self.assertIsNone(totaux["transport_amount_eur"])

    # ─── Rôles ───────────────────────────────────────────────────────

    def test_les_deux_roles_ops_peuvent_agir_et_les_autres_non(self):
        reference = self._creer_dossier()
        for utilisateur in (self.logisticien, self.responsable):
            resultat = self._lignes(utilisateur).add_line(reference, {
                "request_uuid": str(uuid.uuid4()),
                "line": self._ligne_saisie(description="Ajout %s" % utilisateur.login),
            })
            self.assertEqual(resultat["status"], "added")
        with self.assertRaises(AccessError):
            self._lignes(self.non_ops).get_intake(reference)

    # ─── Ajout ───────────────────────────────────────────────────────

    def test_un_ajout_ne_cree_ni_dossier_ni_numero(self):
        depart = self._consolidation("AIR-DSS-CDG-LIG-AJOUT")
        reference = self._creer_dossier(consolidation=depart)
        avant = self.env["dally.shipment"].sudo().search_count(
            [("intake_consolidation_id", "=", depart.id)])

        resultat = self._lignes().add_line(reference, {
            "request_uuid": str(uuid.uuid4()),
            "line": self._ligne_saisie(description="Bissap", exact_weight_kg=8.0),
        })

        self.assertEqual(resultat["status"], "added")
        self.assertEqual(resultat["intake"]["local_reference"], "A001")
        self.assertEqual(resultat["intake"]["reference"], reference)
        self.assertEqual(len(resultat["intake"]["lines"]), 2)
        # Aucune séquence consommée : pas de A002.
        self.assertEqual(
            self.env["dally.shipment"].sudo().search_count(
                [("intake_consolidation_id", "=", depart.id)]), avant)

    def test_un_ajout_projette_le_colis_dans_la_consolidation(self):
        reference = self._creer_dossier()
        ligne = self._ligne_saisie(description="Bissap", quantity=2, exact_weight_kg=8.0)
        self._lignes().add_line(reference, {
            "request_uuid": str(uuid.uuid4()), "line": ligne})

        colis = self._colis(reference, ligne["line_uuid"])
        projection = self._projection(colis)
        self.assertEqual(len(projection), 1)
        self.assertEqual(projection.quantity_loaded, 2)
        self.assertAlmostEqual(projection.weight_loaded, 8.0, places=3)
        self.assertEqual(colis.available_quantity, 0)

    def test_une_reference_de_ligne_deja_prise_est_refusee(self):
        ligne = self._ligne_saisie()
        reference = self._creer_dossier(**ligne)
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._lignes().add_line(reference, {
                "request_uuid": str(uuid.uuid4()),
                "line": self._ligne_saisie(
                    line_uuid=ligne["line_uuid"], description="Écrasement"),
            })
        self.assertEqual(erreur.exception.code, "line_reference_conflict")

    def test_une_reference_de_ligne_d_un_autre_dossier_ne_touche_pas_celui_ci(self):
        """La clé enferme l'article dans son dossier."""
        ligne_a = self._ligne_saisie()
        dossier_a = self._creer_dossier(**ligne_a)
        dossier_b = self._creer_dossier(consolidation=self.c2)

        # Le même `line_uuid` dans un autre dossier compose une autre clé : il
        # crée un article, il n'en écrase aucun.
        self._lignes().add_line(dossier_b, {
            "request_uuid": str(uuid.uuid4()),
            "line": self._ligne_saisie(
                line_uuid=ligne_a["line_uuid"], description="Autre dossier"),
        })
        self.assertEqual(self._colis(dossier_a, ligne_a["line_uuid"]).description, "Savon")

    def test_un_ajout_sur_consolidation_fermee_est_refuse(self):
        reference = self._creer_dossier()
        self.c1.sudo().action_close_collection()
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._lignes().add_line(reference, {
                "request_uuid": str(uuid.uuid4()), "line": self._ligne_saisie()})
        self.assertEqual(erreur.exception.code, "consolidation_not_open")

    def test_un_champ_reserve_au_serveur_est_refuse(self):
        reference = self._creer_dossier()
        for cle in ("package_id", "shipment_id", "external_line_key",
                    "manual_unit_price_eur"):
            with self.subTest(cle=cle):
                ligne = self._ligne_saisie()
                ligne[cle] = 1
                with self.assertRaises(DallyOpsError):
                    self._lignes().add_line(reference, {
                        "request_uuid": str(uuid.uuid4()), "line": ligne})

    # ─── Correction ──────────────────────────────────────────────────

    def _preparer_correction(self, **ligne):
        saisie = self._ligne_saisie(**ligne)
        reference = self._creer_dossier(**saisie)
        detail = self._lignes().get_intake(reference)["intake"]
        return reference, saisie, detail["lines"][0]["revision"]

    def test_une_correction_de_libelle_aboutit(self):
        reference, saisie, revision = self._preparer_correction()
        resultat = self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()),
            "expected_revision": revision,
            "line": dict(saisie, description="Savon de Marseille",
                         goods_category="Hygiène"),
        })
        self.assertEqual(resultat["status"], "updated")
        self.assertEqual(resultat["line"]["description"], "Savon de Marseille")
        self.assertEqual(resultat["line"]["goods_category"], "Hygiène")

    def test_une_correction_change_la_version(self):
        reference, saisie, revision = self._preparer_correction()
        resultat = self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
            "line": dict(saisie, description="Autre libellé"),
        })
        self.assertNotEqual(resultat["line"]["revision"], revision)

    def test_une_version_perimee_est_refusee(self):
        """Le scénario que la version existe pour empêcher."""
        reference, saisie, revision = self._preparer_correction()
        self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
            "line": dict(saisie, exact_weight_kg=14.0),
        })
        # Le second écran avait lu l'ancienne version.
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._lignes().update_line(reference, saisie["line_uuid"], {
                "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
                "line": dict(saisie, exact_weight_kg=12.0),
            })
        self.assertEqual(erreur.exception.code, "stale_line")

    def test_une_version_perimee_n_ecrase_rien(self):
        reference, saisie, revision = self._preparer_correction()
        self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
            "line": dict(saisie, exact_weight_kg=14.0),
        })
        with self.assertRaises(DallyOpsConflict):
            self._lignes().update_line(reference, saisie["line_uuid"], {
                "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
                "line": dict(saisie, exact_weight_kg=12.0),
            })
        colis = self._colis(reference, saisie["line_uuid"])
        self.assertAlmostEqual(colis.total_weight_kg, 14.0, places=3)

    def test_la_reference_du_chemin_prime_sur_le_corps(self):
        reference, saisie, revision = self._preparer_correction()
        with self.assertRaises(DallyOpsError):
            self._lignes().update_line(reference, saisie["line_uuid"], {
                "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
                "line": dict(saisie, line_uuid=str(uuid.uuid4())),
            })

    def test_un_article_inconnu_est_introuvable(self):
        reference, _saisie, _revision = self._preparer_correction()
        inconnu = str(uuid.uuid4())
        with self.assertRaises(DallyOpsNotFound):
            self._lignes().update_line(reference, inconnu, {
                "request_uuid": str(uuid.uuid4()), "expected_revision": "x",
                "line": self._ligne_saisie(line_uuid=inconnu),
            })

    # ─── La projection, cas critique ─────────────────────────────────

    def test_une_correction_physique_reconstruit_la_projection(self):
        """Quatre cartons de 80 kg deviennent trois de 63.

        Écrire la nouvelle quantité pendant que l'ancienne est encore déclarée
        chargée serait refusé par la garde du modèle : on détache, on corrige,
        on rattache.
        """
        reference, saisie, revision = self._preparer_correction(
            quantity=4, exact_weight_kg=80.0,
            length_cm=50.0, width_cm=40.0, height_cm=30.0)

        colis = self._colis(reference, saisie["line_uuid"])
        projection = self._projection(colis)
        self.assertEqual(projection.quantity_loaded, 4)
        self.assertAlmostEqual(projection.weight_loaded, 80.0, places=3)

        self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
            "line": dict(saisie, quantity=3, exact_weight_kg=63.0,
                         length_cm=60.0, width_cm=40.0, height_cm=30.0),
        })

        colis.invalidate_recordset()
        projection = self._projection(colis)
        self.assertEqual(len(projection), 1)
        self.assertEqual(colis.quantity, 3)
        self.assertAlmostEqual(colis.total_weight_kg, 63.0, places=3)
        self.assertEqual(projection.quantity_loaded, 3)
        self.assertAlmostEqual(projection.weight_loaded, 63.0, places=3)
        self.assertAlmostEqual(
            projection.volume_loaded, colis.total_volume_cbm, places=4)
        self.assertEqual(colis.available_quantity, 0)

    def test_une_augmentation_de_quantite_est_projetee(self):
        reference, saisie, revision = self._preparer_correction(
            quantity=3, exact_weight_kg=30.0)
        self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
            "line": dict(saisie, quantity=5, exact_weight_kg=50.0),
        })
        colis = self._colis(reference, saisie["line_uuid"])
        projection = self._projection(colis)
        self.assertEqual(projection.quantity_loaded, 5)
        self.assertAlmostEqual(projection.weight_loaded, 50.0, places=3)
        self.assertEqual(colis.available_quantity, 0)

    def test_une_correction_non_physique_garde_la_projection(self):
        reference, saisie, revision = self._preparer_correction()
        colis = self._colis(reference, saisie["line_uuid"])
        projection_avant = self._projection(colis)
        identifiant = projection_avant.id

        self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
            "line": dict(saisie, description="Nouveau libellé"),
        })
        projection_apres = self._projection(colis)
        # Rien de physique n'a bougé : inutile de détacher quoi que ce soit.
        self.assertEqual(projection_apres.id, identifiant)

    def test_un_echec_apres_detachement_restaure_tout(self):
        """La transaction protège la projection autant que le colis."""
        reference, saisie, revision = self._preparer_correction(
            quantity=4, exact_weight_kg=80.0)
        colis = self._colis(reference, saisie["line_uuid"])
        avant = (colis.quantity, colis.total_weight_kg, self._projection(colis).id)

        # Une famille inconnue fait échouer le moteur après le détachement.
        with self.assertRaises(Exception):
            self._lignes().update_line(reference, saisie["line_uuid"], {
                "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
                "line": dict(saisie, quantity=2, exact_weight_kg=20.0,
                             tariff_family_code="famille_inexistante"),
            })

        colis.invalidate_recordset()
        projection = self._projection(colis)
        self.assertEqual(len(projection), 1)
        self.assertEqual((colis.quantity, colis.total_weight_kg), avant[:2])
        self.assertEqual(projection.quantity_loaded, 4)
        self.assertAlmostEqual(projection.weight_loaded, 80.0, places=3)

    # ─── Tarification ────────────────────────────────────────────────

    def test_la_tarification_est_recalculee_apres_correction(self):
        reference, saisie, revision = self._preparer_correction(exact_weight_kg=10.0)
        detail = self._lignes().get_intake(reference)["intake"]
        self.assertAlmostEqual(detail["lines"][0]["transport_amount_eur"], 50.0, places=2)

        resultat = self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
            "line": dict(saisie, exact_weight_kg=20.0),
        })
        self.assertEqual(resultat["line"]["pricing_status"], "automatic")
        self.assertAlmostEqual(resultat["line"]["transport_amount_eur"], 100.0, places=2)

    def test_une_famille_sans_grille_passe_en_tarif_a_valider(self):
        reference, saisie, revision = self._preparer_correction()
        resultat = self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
            "line": dict(saisie, tariff_family_code=self.family_autre.code),
        })
        self.assertEqual(resultat["line"]["pricing_status"], "manual_required")
        # Jamais 0 € présenté comme un prix.
        self.assertIsNone(resultat["line"]["transport_amount_eur"])

    def test_passer_sur_devis_reste_une_correction_valide(self):
        reference, saisie, revision = self._preparer_correction()
        resultat = self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
            "line": dict(saisie, billing_method="quote"),
        })
        self.assertEqual(resultat["line"]["pricing_status"], "quote")

    # ─── Verrou de facturation ───────────────────────────────────────

    def test_aucune_mutation_apres_engagement_de_la_facturation(self):
        reference, saisie, revision = self._preparer_correction()
        self._shipment(reference).sudo().billing_locked = True

        with self.assertRaises(DallyOpsConflict) as ajout:
            self._lignes().add_line(reference, {
                "request_uuid": str(uuid.uuid4()), "line": self._ligne_saisie()})
        self.assertEqual(ajout.exception.code, "billing_locked")

        # Dally Ops est volontairement plus strict que le moteur : même un
        # libellé est refusé.
        for changement in ({"description": "Autre"}, {"goods_category": "Autre"},
                           {"exact_weight_kg": 20.0}, {"customs_value_xof": 90000}):
            with self.subTest(changement=changement):
                with self.assertRaises(DallyOpsConflict) as erreur:
                    self._lignes().update_line(reference, saisie["line_uuid"], {
                        "request_uuid": str(uuid.uuid4()),
                        "expected_revision": revision,
                        "line": dict(saisie, **changement),
                    })
                self.assertEqual(erreur.exception.code, "billing_locked")

    def test_le_verrou_de_facturation_n_ecrit_rien(self):
        reference, saisie, revision = self._preparer_correction()
        colis = self._colis(reference, saisie["line_uuid"])
        avant = (colis.description, colis.total_weight_kg, colis.write_date)
        self._shipment(reference).sudo().billing_locked = True

        with self.assertRaises(DallyOpsConflict):
            self._lignes().update_line(reference, saisie["line_uuid"], {
                "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
                "line": dict(saisie, description="Ne doit pas passer"),
            })
        colis.invalidate_recordset()
        self.assertEqual((colis.description, colis.total_weight_kg, colis.write_date), avant)

    def test_un_dossier_hors_etat_modifiable_est_refuse(self):
        reference, saisie, revision = self._preparer_correction()
        shipment = self._shipment(reference)
        shipment.sudo()._write_state_from_operational_source("ready")
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._lignes().add_line(reference, {
                "request_uuid": str(uuid.uuid4()), "line": self._ligne_saisie()})
        self.assertEqual(erreur.exception.code, "intake_not_editable")

    # ─── Idempotence ─────────────────────────────────────────────────

    def test_un_ajout_rejoue_ne_double_pas_l_article(self):
        reference = self._creer_dossier()
        demande = {"request_uuid": str(uuid.uuid4()),
                   "line": self._ligne_saisie(description="Bissap")}
        premier = self._lignes().add_line(reference, demande)
        second = self._lignes().add_line(reference, demande)

        self.assertEqual(second, premier)
        self.assertEqual(len(self._shipment(reference).package_ids), 2)

    def test_une_correction_rejouee_rend_son_propre_resultat(self):
        """Le rejeu relit sa réponse, pas l'état actuel de la ligne."""
        reference, saisie, revision = self._preparer_correction()
        demande = {"request_uuid": str(uuid.uuid4()),
                   "expected_revision": revision,
                   "line": dict(saisie, exact_weight_kg=14.0)}
        premier = self._lignes().update_line(reference, saisie["line_uuid"], demande)

        # Une autre correction change la ligne entre-temps.
        self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()),
            "expected_revision": premier["line"]["revision"],
            "line": dict(saisie, exact_weight_kg=18.0),
        })

        rejeu = self._lignes().update_line(reference, saisie["line_uuid"], demande)
        self.assertEqual(rejeu, premier)
        self.assertAlmostEqual(rejeu["line"]["exact_weight_kg"], 14.0, places=3)
        # Et la ligne réelle n'a pas été ramenée en arrière.
        colis = self._colis(reference, saisie["line_uuid"])
        self.assertAlmostEqual(colis.total_weight_kg, 18.0, places=3)

    def test_le_meme_identifiant_avec_une_autre_intention_est_un_conflit(self):
        reference = self._creer_dossier()
        identifiant = str(uuid.uuid4())
        self._lignes().add_line(reference, {
            "request_uuid": identifiant, "line": self._ligne_saisie(description="A")})
        with self.assertRaises(DallyOpsConflict) as erreur:
            self._lignes().add_line(reference, {
                "request_uuid": identifiant, "line": self._ligne_saisie(description="B")})
        self.assertEqual(erreur.exception.code, "idempotency_conflict")

    def test_un_rejeu_passe_meme_apres_verrouillage_de_la_facturation(self):
        """L'ordre : idempotence d'abord, verrou métier ensuite.

        La correction a réussi, la facture est arrivée, le réseau a lâché.
        Rejouer doit relire le résultat — pas se heurter à un verrou apparu
        après coup.
        """
        reference, saisie, revision = self._preparer_correction()
        demande = {"request_uuid": str(uuid.uuid4()), "expected_revision": revision,
                   "line": dict(saisie, exact_weight_kg=14.0)}
        premier = self._lignes().update_line(reference, saisie["line_uuid"], demande)

        self._shipment(reference).sudo().billing_locked = True
        rejeu = self._lignes().update_line(reference, saisie["line_uuid"], demande)
        self.assertEqual(rejeu, premier)

    def test_le_registre_ne_recopie_aucune_donnee_personnelle(self):
        reference = self._creer_dossier()
        identifiant = str(uuid.uuid4())
        self._lignes().add_line(reference, {
            "request_uuid": identifiant, "line": self._ligne_saisie()})
        ligne = self.env["dally.ops.intake.line.request"].sudo().search(
            [("request_uuid", "=", identifiant)], limit=1)
        self.assertTrue(ligne)
        for interdit in ("Aissatou", "phone", "email", "+221"):
            self.assertNotIn(interdit, ligne.result_snapshot)

    # ─── Audit ───────────────────────────────────────────────────────

    def test_les_mutations_sont_attribuees_a_leur_operateur(self):
        reference, saisie, revision = self._preparer_correction()
        identifiant = str(uuid.uuid4())
        self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": identifiant, "expected_revision": revision,
            "line": dict(saisie, description="Corrigé"),
        })
        evenement = self.env["dally.ops.audit.event"].sudo().search(
            [("request_uuid", "=", identifiant),
             ("action", "=", "intake_line_updated")], limit=1)
        self.assertTrue(evenement)
        self.assertEqual(evenement.operator_user_id, self.logisticien)
        self.assertEqual(evenement.entity_model, "dally.shipment.package")
        self.assertEqual(evenement.shipment_id.external_reference, reference)
        self.assertIn({
            "field": "description", "old_value": "Savon",
            "new_value": "Corrigé",
        }, evenement.changes_json)

    def test_le_client_n_est_jamais_modifie(self):
        reference, saisie, revision = self._preparer_correction()
        avant = self.partner.write_date
        self._lignes().add_line(reference, {
            "request_uuid": str(uuid.uuid4()), "line": self._ligne_saisie()})
        self._lignes().update_line(reference, saisie["line_uuid"], {
            "request_uuid": str(uuid.uuid4()), "expected_revision": revision,
            "line": dict(saisie, description="Corrigé"),
        })
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.write_date, avant)

    # ─── Frontière de privilège ──────────────────────────────────────

    def test_le_controleur_ne_contient_aucun_sudo(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_intakes
        self.assertNotIn("sudo", code_seul(ops_intakes))

    def test_le_service_ne_privilegie_que_les_modeles_declares(self):
        from odoo.addons.dally_ops_mobile.models import ops_intake_line_service
        code = code_seul(ops_intake_line_service).replace("'", '"')
        prives = set(__import__("re").findall(r'self\.env\["([^"]+)"\]\.sudo\(\)', code))
        self.assertEqual(prives, {
            "dally.shipment",
            "dally.freight.consolidation.line",
            "dally.ops.intake.line.request",
            "dally.ops.audit.event",
            "dally.freight.sync.service",
        })

    def test_aucune_cle_d_api_ni_portee_freight(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_intakes
        code = code_seul(ops_intakes)
        for interdit in ("api_key", "required_scope", "freight:", "DallyApiController"):
            self.assertNotIn(interdit, code)
