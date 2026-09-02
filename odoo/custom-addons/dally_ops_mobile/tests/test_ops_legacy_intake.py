# -*- coding: utf-8 -*-
"""La fiche en lecture seule d'un dossier que Dally Ops n'a pas créé.

## Ce que ces tests protègent

**La séparation des deux portes.** Le résolveur natif garde les mutations ;
celui-ci ne rend que du texte. Un dossier ne doit jamais s'ouvrir des deux
côtés — sinon la fiche en lecture seule deviendrait un contournement.

**La liste blanche.** Le DTO est énuméré, pas retranché. Ces tests le
comparent à un ensemble figé : un champ qui apparaîtrait plus tard dans une
brique voisine ne descendrait pas jusqu'au navigateur sans qu'une décision
soit prise ici.

**La clé de navigation.** `A001` est local à son départ. Deux consolidations
en ont chacune un, et seule la référence globale les départage.
"""

import ast
import inspect
import uuid

from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.dally_freight.models.dally_shipment import _STATE_BYPASS_TOKEN
from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError
from odoo.addons.dally_ops_mobile.models import ops_legacy_intake_service


#: Le DTO entier, figé. Toute addition doit passer par ce test.
CHAMPS_DTO = {
    "readonly", "reference", "local_reference", "state", "state_label",
    "transport_mode", "direction", "consolidation_reference", "received_on",
    "customer", "lines", "totals", "payments", "payment_summary",
}

CHAMPS_LIGNE = {
    "description", "goods_category", "package_type", "quantity",
    "announced_weight_kg", "exact_weight_kg",
    "length_cm", "width_cm", "height_cm", "volume_cbm",
}

CHAMPS_PAIEMENT = {
    "amount", "currency_code", "payment_date", "payment_method",
    "collector", "accounting_status",
}


@tagged("post_install", "-at_install", "dally")
class TestOpsLegacyIntake(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.societe = cls.env.company
        cls.autre_societe = cls.env["res.company"].create({"name": "Ops Legacy Autre"})

        cls.gilles = cls._compte("legacy.gilles", "Gilles Legacy",
                                 "dally_ops_mobile.group_dally_ops_logistician")
        cls.responsable = cls._compte("legacy.chef", "Chef Legacy",
                                      "dally_ops_mobile.group_dally_ops_supervisor")
        cls.temoin = cls._compte("legacy.temoin", "Temoin Legacy", "base.group_user")

        Famille = cls.env["dally.freight.tariff.family"]
        Regle = cls.env["dally.freight.tariff.rule"]
        cls.famille = Famille.search([("code", "=", "non_food")], limit=1)
        if not cls.famille:
            cls.famille = Famille.create(
                {"name": "Legacy Non alimentaire", "code": "non_food"})
        if not Regle.search([("family_id", "=", cls.famille.id),
                             ("transport_mode", "=", "air")], limit=1):
            Regle.create({
                "name": "Legacy non_food air", "transport_mode": "air",
                "family_id": cls.famille.id, "customer_segment": "all",
                "price_per_kg_eur": 5.0,
            })

        cls.partner = cls.env["res.partner"].create({
            "name": "Awa Legacy", "company_id": cls.societe.id,
            "phone": "+221 77 400 11 22",
            "email": "awa.legacy@invalid.local",
            "street": "Rue interdite",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.depart = cls._consolidation("AIR-DSS-CDG-LEGACY-001")

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

    def _dossier_ops(self):
        """Un dossier natif, créé par le vrai service d'entrée."""
        resultat = (self.env["dally.ops.intake.service"]
                    .with_user(self.gilles).with_company(self.societe)
                    .create_intake({
                        "request_uuid": str(uuid.uuid4()),
                        "consolidation_reference": self.depart.name,
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

    def _dossier_repris(self, reference, *, source="google_sheets",
                        cle_source=None, societe=None, partenaire=None,
                        local_ref=None, etat="goods_received"):
        """Un dossier tel que le tableur ou le classeur en ont laissé.

        Freight impose la création en brouillon : un dossier avance par une
        action métier, il ne naît pas au milieu de son parcours. Une reprise
        historique, elle, arrive déjà avancée — d'où le jeton, qui est
        exactement le chemin qu'emprunte un backfill.
        """
        valeurs = {
            "partner_id": (partenaire or self.partner).id,
            "company_id": (societe or self.societe).id,
            "transport_mode": "air", "direction": "export",
        }
        if reference is not None:
            valeurs["external_reference"] = reference
        if source:
            valeurs["sync_source"] = source
        dossier = self.env["dally.shipment"].sudo().create(valeurs)
        # `sync_source_key` et `collection_local_ref` sont des identifiants de
        # collecte : Freight les refuse à la création hors du service métier,
        # et les fige dès qu'une consolidation d'entrée existe. Un dossier
        # repris n'en a pas — l'écriture après coup est donc le chemin ouvert.
        identite = {}
        if cle_source:
            identite["sync_source_key"] = cle_source
        if local_ref:
            identite["collection_local_ref"] = local_ref
        if identite:
            dossier.sudo().write(identite)
        if etat and etat != "draft":
            dossier.sudo().with_context(
                _dally_state_bypass=_STATE_BYPASS_TOKEN).write({"state": etat})
        return dossier

    def _colis(self, dossier, cle_ligne, **surcharges):
        valeurs = {
            "shipment_id": dossier.id,
            "company_id": dossier.company_id.id,
            "package_type": "parcel",
            "description": "Carton repris",
            "goods_category": "Divers",
            "quantity": 2,
            "unit_weight_kg": 4.0,
            "external_line_key": cle_ligne,
        }
        valeurs.update(surcharges)
        return self.env["dally.shipment.package"].sudo().create(valeurs)

    def _encaissement(self, dossier, montant=15000.0, etat="registered"):
        return self.env["dally.freight.collection"].sudo().create({
            "external_payment_key": "sheets:pay:%s" % uuid.uuid4().hex[:10],
            "company_id": dossier.company_id.id,
            "shipment_id": dossier.id,
            "partner_id": dossier.partner_id.id,
            "amount": montant,
            "currency_id": dossier.company_id.currency_id.id,
            "payment_date": "2026-08-20",
            "source_method": "cash",
            "source": "google_sheets",
            "state": etat,
            "collected_by_name": "Gilles",
        })

    def _lire(self, reference, utilisateur=None):
        service = (self.env["dally.ops.legacy.intake.service"]
                   .with_user(utilisateur or self.gilles)
                   .with_company(self.societe))
        return service.get_legacy_intake(reference)["intake"]

    # ─── L01-L05 · qui a le droit, et sur quoi ───────────────────────

    def test_L01_le_logisticien_lit_un_dossier_repris(self):
        self._dossier_repris("LEGACY-L01")
        self.assertEqual(self._lire("LEGACY-L01")["reference"], "LEGACY-L01")

    def test_L02_le_responsable_aussi(self):
        self._dossier_repris("LEGACY-L02")
        self.assertEqual(
            self._lire("LEGACY-L02", self.responsable)["reference"], "LEGACY-L02")

    def test_L03_un_compte_sans_role_ops_est_refuse(self):
        self._dossier_repris("LEGACY-L03")
        with self.assertRaises(DallyOpsError) as erreur:
            self._lire("LEGACY-L03", self.temoin)
        self.assertEqual(erreur.exception.code, "ops_forbidden")
        self.assertEqual(erreur.exception.status, 403)

    def test_L04_un_dossier_d_une_autre_societe_est_invisible(self):
        autre_partenaire = self.env["res.partner"].create({
            "name": "Client Ailleurs", "company_id": self.autre_societe.id})
        self._dossier_repris("LEGACY-L04", societe=self.autre_societe,
                             partenaire=autre_partenaire)
        with self.assertRaises(DallyOpsError) as erreur:
            self._lire("LEGACY-L04")
        self.assertEqual(erreur.exception.code, "intake_not_found")

    def test_L05_un_dossier_ops_natif_est_refuse_par_ce_service(self):
        """Les deux portes restent disjointes.

        Si la fiche en lecture seule acceptait un dossier natif, elle
        deviendrait un second chemin de lecture pour des données que la fiche
        complète expose déjà — et le jour où l'une durcirait, l'autre non.
        """
        reference = self._dossier_ops()
        with self.assertRaises(DallyOpsError) as erreur:
            self._lire(reference)
        self.assertEqual(erreur.exception.code, "intake_not_found")
        # Et le chemin natif, lui, continue de l'ouvrir.
        natif = (self.env["dally.ops.intake.line.service"]
                 .with_user(self.gilles).with_company(self.societe)
                 .get_intake(reference))
        self.assertEqual(natif["intake"]["reference"], reference)

    # ─── L06-L08 · les origines reprises ─────────────────────────────

    def test_L06_un_dossier_google_sheets_est_lisible(self):
        self._dossier_repris("LEGACY-L06", source="google_sheets",
                             cle_source="sheets:L06")
        self.assertEqual(self._lire("LEGACY-L06")["reference"], "LEGACY-L06")

    def test_L07_un_dossier_du_classeur_est_lisible(self):
        self._dossier_repris("LEGACY-L07", source="legacy_xlsx")
        self.assertEqual(self._lire("LEGACY-L07")["reference"], "LEGACY-L07")

    def test_L08_une_reference_inconnue_repond_introuvable(self):
        with self.assertRaises(DallyOpsError) as erreur:
            self._lire("LEGACY-JAMAIS-VUE")
        self.assertEqual(erreur.exception.code, "intake_not_found")
        self.assertEqual(erreur.exception.status, 404)

    # ─── L09 · la collision des références locales ───────────────────

    def test_L09_deux_A001_restent_deux_dossiers(self):
        """Le cas qui justifie que la navigation soit globale.

        Deux départs distribuent chacun leur `A001`. Si la fiche se laissait
        ouvrir par la référence locale, l'un des deux clients verrait le
        dossier de l'autre.
        """
        self._dossier_repris("AIR-DSS-CDG-L09A-A001", local_ref="A001")
        self._dossier_repris("AIR-DSS-CDG-L09B-A001", local_ref="A001")

        premier = self._lire("AIR-DSS-CDG-L09A-A001")
        second = self._lire("AIR-DSS-CDG-L09B-A001")
        self.assertEqual(premier["local_reference"], "A001")
        self.assertEqual(second["local_reference"], "A001")
        self.assertNotEqual(premier["reference"], second["reference"])

        # Et la référence locale seule n'ouvre rien.
        with self.assertRaises(DallyOpsError):
            self._lire("A001")

    # ─── L10-L12 · ce qui ne sort jamais ─────────────────────────────

    def test_L10_le_client_se_limite_au_nom_et_au_numero(self):
        self._dossier_repris("LEGACY-L10")
        client = self._lire("LEGACY-L10")["customer"]
        self.assertEqual(set(client), {"name", "phone"})
        self.assertEqual(client["name"], "Awa Legacy")
        self.assertEqual(client["phone"], "+221 77 400 11 22")

    def test_L11_le_dto_est_exactement_la_liste_blanche(self):
        dossier = self._dossier_repris("LEGACY-L11")
        self._colis(dossier, "sheets:L11:line:1")
        self._encaissement(dossier)
        fiche = self._lire("LEGACY-L11")

        self.assertEqual(set(fiche), CHAMPS_DTO)
        self.assertEqual(set(fiche["lines"][0]), CHAMPS_LIGNE)
        self.assertEqual(set(fiche["payments"][0]), CHAMPS_PAIEMENT)
        self.assertEqual(set(fiche["totals"]),
                         {"lines_count", "weight_kg", "volume_cbm"})
        self.assertEqual(set(fiche["payment_summary"][0]),
                         {"currency_code", "amount"})

    def test_L12_aucun_identifiant_ni_clé_technique_ne_descend(self):
        dossier = self._dossier_repris("LEGACY-L12", cle_source="sheets:L12")
        self._colis(dossier, "sheets:L12:line:1")
        self._encaissement(dossier)
        texte = repr(self._lire("LEGACY-L12"))

        for interdit in ("sync_source", "external_line_key",
                         "external_payment_key", "partner_id", "shipment_id",
                         "invoice_id", "journal_id", "sheets:", "revision",
                         "pricing_status", "transport_amount_eur",
                         "customs_value_xof", "tariff_family",
                         "billable_weight_kg", "editable",
                         "allowed_transitions", "edit_block_reason"):
            self.assertNotIn(interdit, texte, interdit)
        # L'identifiant de base du dossier n'y figure pas non plus.
        self.assertNotIn('"id"', texte)
        self.assertNotIn("'id'", texte)

    # ─── L13-L14 · les deux familles de clé de ligne ─────────────────

    def test_L13_les_colis_du_tableur_sont_lus(self):
        dossier = self._dossier_repris("LEGACY-L13", cle_source="sheets:L13")
        self._colis(dossier, "sheets:L13:line:1")
        self.assertEqual(self._lire("LEGACY-L13")["totals"]["lines_count"], 1)

    def test_L14_les_colis_du_format_historique_sont_lus(self):
        """La convention du natif cacherait ces colis-là.

        Le DTO natif ne retient que les colis préfixés par la clé source du
        dossier. Un colis historique porte `<consolidation>|<localref>|A|<n>`
        et serait donc invisible — la fiche annoncerait un dossier vide.
        """
        dossier = self._dossier_repris("LEGACY-L14", source="legacy_xlsx")
        self._colis(dossier, "AIR-DSS-CDG-2026-002|A020|A|1")
        self._colis(dossier, "AIR-DSS-CDG-2026-002|A020|A|2")
        self.assertEqual(self._lire("LEGACY-L14")["totals"]["lines_count"], 2)

    def test_L15_un_dossier_sans_reference_globale_n_est_pas_navigable(self):
        self._dossier_repris(None, source="legacy_xlsx")
        with self.assertRaises(DallyOpsError) as erreur:
            self._lire("")
        self.assertEqual(erreur.exception.code, "intake_not_found")

    # ─── L16-L19 · les encaissements ─────────────────────────────────

    def test_L16_les_encaissements_repris_sont_inclus(self):
        dossier = self._dossier_repris("LEGACY-L16")
        self._encaissement(dossier, montant=15000.0)
        fiche = self._lire("LEGACY-L16")
        self.assertEqual(len(fiche["payments"]), 1)
        self.assertEqual(fiche["payments"][0]["amount"], 15000.0)
        self.assertEqual(fiche["payments"][0]["collector"], "Gilles")
        self.assertEqual(fiche["payments"][0]["accounting_status"], "registered")

    def test_L17_la_reference_de_paiement_ne_descend_pas(self):
        """`_reference_publique()` rend la clé externe telle quelle hors `ops:`.

        C'est une identité technique. Elle ne dit rien au logisticien, et elle
        n'a donc pas à sortir — même si le DTO des paiements la porte.
        """
        dossier = self._dossier_repris("LEGACY-L17")
        self._encaissement(dossier)
        paiement = self._lire("LEGACY-L17")["payments"][0]
        self.assertNotIn("reference", paiement)

        # Le service natif, lui, la porte toujours : rien n'a été retiré ailleurs.
        natif = self.env["dally.ops.payment.service"].sudo().payments_for(dossier)
        self.assertIn("reference", natif[0])

    def test_L18_un_encaissement_annule_est_ecarte(self):
        dossier = self._dossier_repris("LEGACY-L18")
        self._encaissement(dossier, montant=1000.0)
        annule = self._encaissement(dossier, montant=9999.0)
        annule.sudo().write({"state": "cancelled"})

        fiche = self._lire("LEGACY-L18")
        self.assertEqual(len(fiche["payments"]), 1)
        self.assertEqual(fiche["payments"][0]["amount"], 1000.0)

    def test_L19_le_total_est_donne_par_devise(self):
        dossier = self._dossier_repris("LEGACY-L19")
        self._encaissement(dossier, montant=1000.0)
        self._encaissement(dossier, montant=2500.0)
        resume = self._lire("LEGACY-L19")["payment_summary"]
        self.assertEqual(len(resume), 1)
        self.assertEqual(resume[0]["amount"], 3500.0)
        self.assertEqual(resume[0]["currency_code"],
                         self.societe.currency_id.name)

    # ─── L20-L24 · les invariants du service ─────────────────────────

    def test_L20_le_resolveur_natif_n_a_pas_bouge(self):
        """Le domaine natif, pris au mot plutôt que de confiance."""
        domaine = (self.env["dally.ops.intake.line.service"]
                   ._domaine_dossier_ops())
        self.assertEqual(domaine, [
            ("company_id", "=", self.env.company.id),
            ("sync_source", "=", "backoffice"),
            ("sync_source_key", "=like", "ops:%"),
            ("intake_consolidation_id", "!=", False),
        ])

    def test_L21_le_service_legacy_n_ecrit_rien(self):
        """Zéro écriture, prouvé sur l'arbre syntaxique.

        Les docstrings sont retirées : seul le code exécutable compte, sans
        quoi un mot cité dans un commentaire suffirait à faire tomber — ou à
        rassurer à tort.
        """
        arbre = ast.parse(inspect.getsource(ops_legacy_intake_service))
        for noeud in ast.walk(arbre):
            if isinstance(noeud, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                corps = noeud.body
                if (corps and isinstance(corps[0], ast.Expr)
                        and isinstance(corps[0].value, ast.Constant)
                        and isinstance(corps[0].value.value, str)):
                    noeud.body = corps[1:] or [ast.Pass()]

        appels = [n.func.attr for n in ast.walk(arbre)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        for interdit in ("create", "write", "unlink", "enqueue_dossier",
                         "action_set_state", "_dally_enqueue_notification"):
            self.assertEqual(appels.count(interdit), 0, interdit)

        code = ast.unparse(arbre)
        for motif in ("notification", "mail.", "sms", "outbox"):
            self.assertNotIn(motif, code, motif)

    def test_L22_aucune_donnee_d_evenement_ne_figure_dans_la_fiche(self):
        """Step 5 a gardé les événements derrière le domaine natif.

        Step 6 ne doit pas élargir cette surface par ricochet.
        """
        dossier = self._dossier_repris("LEGACY-L22")
        self.env["dally.shipment.event"].sudo().create({
            "shipment_id": dossier.id,
            "status": dossier.state,
            "description": "Événement de contrôle",
            "internal_note": "Note qui ne doit jamais descendre",
            "event_date": "2026-08-25 09:00:00",
            "visible_to_customer": False,
            "is_automatic": False,
        })
        texte = repr(self._lire("LEGACY-L22"))
        for interdit in ("events", "internal_note", "ops_event_kind",
                         "Note qui ne doit jamais descendre"):
            self.assertNotIn(interdit, texte, interdit)

    def test_L23_le_libelle_d_etat_vient_de_la_selection_du_modele(self):
        self._dossier_repris("LEGACY-L23", etat="preparing")
        fiche = self._lire("LEGACY-L23")
        attendu = dict(
            self.env["dally.shipment"]._fields["state"]
            ._description_selection(self.env))["preparing"]
        self.assertEqual(fiche["state"], "preparing")
        self.assertEqual(fiche["state_label"], attendu)

    def test_L24_les_totaux_somment_les_colis_reellement_lus(self):
        dossier = self._dossier_repris("LEGACY-L24")
        self._colis(dossier, "sheets:L24:line:1", quantity=2, unit_weight_kg=4.0)
        self._colis(dossier, "AIR|A001|A|2", quantity=1, unit_weight_kg=7.5)

        fiche = self._lire("LEGACY-L24")
        self.assertEqual(fiche["totals"]["lines_count"], 2)
        self.assertAlmostEqual(fiche["totals"]["weight_kg"], 15.5, places=3)
        self.assertAlmostEqual(
            fiche["totals"]["volume_cbm"],
            sum(ligne["volume_cbm"] for ligne in fiche["lines"]), places=6)

    def test_L25_la_fiche_se_declare_en_lecture_seule(self):
        self._dossier_repris("LEGACY-L25")
        self.assertIs(self._lire("LEGACY-L25")["readonly"], True)
