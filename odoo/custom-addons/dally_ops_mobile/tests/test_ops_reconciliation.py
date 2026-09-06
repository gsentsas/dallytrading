# -*- coding: utf-8 -*-
"""L'état CRM / tableur / facturation, tel que le comptoir doit le lire.

## Ce que ces tests protègent

**Le vocabulaire.** L'outbox parle transport — `delivered`, `processing`,
`retry`. L'opérateur, lui, veut savoir si c'est passé. La traduction est testée
état par état, y compris la règle qui décide entre plusieurs projections : c'est
la plus mauvaise qui parle, parce qu'un dossier dont une projection a échoué est
en échec même si dix autres sont passées.

**Ce qui ne descend pas.** Aucune clé primaire Odoo, aucun message d'erreur de
transport. La vérification est structurelle — on parcourt le DTO et on refuse
les clés interdites — et non par recherche d'un nombre dans du texte, qui
retrouverait un identifiant au hasard dans un UUID.

**Qui a le droit de quoi.** La liste des actions vient du serveur. Un
logisticien ne relance pas une projection ; un responsable le peut, et
seulement quand elle est réellement en peine.
"""
import uuid

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged

#: Ce qu'un DTO d'opérateur ne doit jamais porter.
CLES_INTERDITES = frozenset({
    "id", "partner_id", "sale_order_id", "invoice_id", "company_id",
    "create_uid", "write_uid", "session_id", "api_key", "stack", "traceback",
    "last_error", "resource_id", "shipment_id", "outbox_id",
})


@tagged("post_install", "-at_install", "dally")
class TestOpsReconciliation(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.societe = cls.env.company
        cls.gilles = cls._compte(
            "recon.gilles", "dally_ops_mobile.group_dally_ops_logistician")
        cls.responsable = cls._compte(
            "recon.resp", "dally_ops_mobile.group_dally_ops_supervisor")

        Famille = cls.env["dally.freight.tariff.family"]
        Regle = cls.env["dally.freight.tariff.rule"]
        cls.famille = Famille.search([("code", "=", "non_food")], limit=1)
        if not cls.famille:
            cls.famille = Famille.create(
                {"name": "Recon Non alimentaire", "code": "non_food"})
        if not Regle.search([("family_id", "=", cls.famille.id),
                             ("transport_mode", "=", "air")], limit=1):
            Regle.create({
                "name": "Recon non_food air", "transport_mode": "air",
                "family_id": cls.famille.id, "customer_segment": "all",
                "price_per_kg_eur": 5.0,
            })

        cls.partner = cls.env["res.partner"].create({
            "name": "Aissatou Recon", "company_id": cls.societe.id,
            "phone": "+221770000031",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.depart = cls._consolidation("AIR-DSS-CDG-RECON-001")

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
    def _consolidation(cls, reference):
        return cls.env["dally.freight.consolidation"].create({
            "name": reference, "state": "collecting", "active": True,
            "company_id": cls.env.company.id,
            "transport_mode": "air", "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })

    def _creer_dossier(self, poids=3.55):
        resultat = (self.env["dally.ops.intake.service"]
                    .with_user(self.gilles).with_company(self.societe)
                    .create_intake({
                        "request_uuid": str(uuid.uuid4()),
                        "consolidation_reference": self.depart.name,
                        "customer_reference": self.handle.token,
                        "received_on": "2026-08-29",
                        "line": {
                            "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                            "goods_category": "Non alimentaire",
                            "description": "Pagne et parfum",
                            "quantity": 1, "announced_weight_kg": None,
                            "exact_weight_kg": poids, "length_cm": None,
                            "width_cm": None, "height_cm": None,
                            "billing_method": "real",
                            "tariff_family_code": self.famille.code,
                            "customs_value_xof": 25000,
                        },
                    }))
        reference = resultat["intake"]["reference"]
        return reference, self.env["dally.shipment"].sudo().search(
            [("external_reference", "=", reference)], limit=1)

    def _resume(self, shipment, utilisateur=None):
        return (self.env["dally.ops.reconciliation.service"]
                .with_user(utilisateur or self.gilles)
                .summary_for(shipment))

    @staticmethod
    def _cles(noeud, vues=None):
        """Toutes les clés du DTO, structurellement — pas par recherche de texte."""
        vues = vues if vues is not None else set()
        if isinstance(noeud, dict):
            for cle, valeur in noeud.items():
                vues.add(cle)
                TestOpsReconciliation._cles(valeur, vues)
        elif isinstance(noeud, list):
            for element in noeud:
                TestOpsReconciliation._cles(element, vues)
        return vues

    # ------------------------------------------------------------------
    # Le dossier neuf
    # ------------------------------------------------------------------

    def test_a_fresh_dossier_reports_recorded_and_unbilled(self):
        _reference, shipment = self._creer_dossier()
        resume = self._resume(shipment)

        self.assertEqual(resume["crm"]["state"], "recorded")
        self.assertEqual(resume["crm"]["reference"], shipment.external_reference)
        self.assertEqual(resume["billing"]["invoice_state"], "none")
        self.assertIsNone(resume["billing"]["invoice_number"])
        self.assertEqual(resume["billing"]["supplement_count"], 0)
        # Un colis reçu et non encore facturé est bien compté comme tel.
        self.assertEqual(resume["billing"]["unbilled_lines_count"], 1)

    def test_the_dto_never_carries_an_odoo_identifier(self):
        """Vérification structurelle : on inspecte les clés, pas le texte."""
        _reference, shipment = self._creer_dossier()
        resume = self._resume(shipment)

        interdites = self._cles(resume) & CLES_INTERDITES
        self.assertEqual(interdites, set(), "clés interdites dans le DTO : %s" % interdites)

    # ------------------------------------------------------------------
    # La facturation
    # ------------------------------------------------------------------

    def test_a_posted_invoice_is_reported_by_number_and_amount(self):
        _reference, shipment = self._creer_dossier()
        facture = shipment.action_prepare_native_freight_invoice()
        facture.action_post()

        resume = self._resume(shipment)

        self.assertEqual(resume["billing"]["invoice_state"], "posted")
        self.assertEqual(resume["billing"]["invoice_number"], facture.name)
        self.assertAlmostEqual(
            resume["billing"]["invoice_amount"], facture.amount_total, places=2)
        self.assertAlmostEqual(
            resume["billing"]["remaining_amount"], facture.amount_residual, places=2)
        # Tout est facturé : plus rien en attente.
        self.assertEqual(resume["billing"]["unbilled_lines_count"], 0)
        self.assertAlmostEqual(resume["billing"]["unbilled_amount"], 0.0, places=2)

    # ------------------------------------------------------------------
    # La projection vers le tableur
    # ------------------------------------------------------------------

    def _projection(self, shipment, etat, **extra):
        """Force l'état d'une projection existante, sans passer par le transport."""
        ligne = self.env["dally.ops.sheet.outbox"].sudo().search(
            [("resource_reference", "=", shipment.external_reference)], limit=1)
        self.assertTrue(ligne, "le dossier doit avoir produit une projection")
        ligne.write({"state": etat, **extra})
        return ligne

    def test_the_outbox_vocabulary_is_translated_for_the_operator(self):
        _reference, shipment = self._creer_dossier()
        for etat_outbox, attendu in (
            ("delivered", "synced"), ("pending", "pending"),
            ("processing", "pending"), ("retry", "retry"), ("failed", "failed"),
        ):
            self._projection(shipment, etat_outbox)
            resume = self._resume(shipment)
            self.assertEqual(
                resume["sheet"]["state"], attendu,
                "%s doit se dire %s" % (etat_outbox, attendu))
            self.assertTrue(resume["sheet"]["operator_message"])

    def test_the_worst_projection_speaks_for_the_dossier(self):
        """Une projection en échec parmi dix réussies : le dossier est en échec."""
        _reference, shipment = self._creer_dossier()
        premiere = self._projection(shipment, "delivered")
        seconde = premiere.sudo().copy({
            "state": "failed", "business_key": "recon:%s" % uuid.uuid4().hex,
        })
        self.assertEqual(seconde.state, "failed")

        resume = self._resume(shipment)

        self.assertEqual(resume["sheet"]["state"], "failed")
        self.assertEqual(resume["sheet"]["failed_count"], 1)

    def test_a_transport_error_never_reaches_the_operator(self):
        _reference, shipment = self._creer_dossier()
        self._projection(
            shipment, "failed",
            last_error="Traceback: psycopg2.OperationalError sur 10.0.0.4:5432")

        resume = self._resume(shipment)

        message = resume["sheet"]["operator_message"]
        self.assertNotIn("Traceback", message)
        self.assertNotIn("psycopg2", message)
        self.assertNotIn("10.0.0.4", message)
        self.assertNotIn("last_error", self._cles(resume))

    # ------------------------------------------------------------------
    # Les actions autorisées
    # ------------------------------------------------------------------

    def test_relaunching_a_projection_belongs_to_the_supervisor(self):
        _reference, shipment = self._creer_dossier()
        self._projection(shipment, "failed")

        self.assertNotIn("resync_sheet", self._resume(shipment, self.gilles)["allowed_actions"])
        self.assertIn(
            "resync_sheet", self._resume(shipment, self.responsable)["allowed_actions"])

    def test_a_healthy_projection_offers_no_relaunch(self):
        _reference, shipment = self._creer_dossier()
        self._projection(shipment, "delivered")

        self.assertNotIn(
            "resync_sheet", self._resume(shipment, self.responsable)["allowed_actions"])

    def test_a_late_package_is_offered_only_once_the_invoice_is_posted(self):
        _reference, shipment = self._creer_dossier()
        # Tant que rien n'est facturé, le colis s'ajoute par le chemin normal.
        self.assertNotIn("add_late_package", self._resume(shipment)["allowed_actions"])

        facture = shipment.action_prepare_native_freight_invoice()
        self.assertNotIn(
            "add_late_package", self._resume(shipment)["allowed_actions"],
            "une facture brouillon se réinitialise, elle n'appelle pas un complément")

        facture.action_post()
        self.assertIn("add_late_package", self._resume(shipment)["allowed_actions"])

    # ------------------------------------------------------------------
    # L'ajout tardif, après comptabilisation — le cas A004-like
    # ------------------------------------------------------------------

    def _ligne_tardive(self, description="Crème cheveux", poids=1.0, uuid_ligne=None):
        return {
            "request_uuid": str(uuid.uuid4()),
            "line": {
                "line_uuid": uuid_ligne or str(uuid.uuid4()),
                "package_type": "parcel", "goods_category": "Non alimentaire",
                "description": description, "quantity": 1,
                "announced_weight_kg": None, "exact_weight_kg": poids,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "billing_method": "real",
                "tariff_family_code": self.famille.code,
                "customs_value_xof": 5000,
            },
        }

    def _service_ligne(self, utilisateur=None):
        return (self.env["dally.ops.intake.line.service"]
                .with_user(utilisateur or self.gilles).with_company(self.societe))

    def _dossier_facture(self):
        """Un dossier A004-like : 3,55 kg à 5 €/kg = 17,75 €, comptabilisé."""
        reference, shipment = self._creer_dossier(poids=3.55)
        facture = shipment.action_prepare_native_freight_invoice()
        facture.action_post()
        self.assertEqual(facture.state, "posted")
        self.assertAlmostEqual(facture.amount_total, 17.75, places=2)
        return reference, shipment, facture

    def test_a_late_package_never_touches_the_posted_invoice(self):
        """TEST 1 et 2 : 17,75 € reste 17,75 €, et le tardif vaut 5 €."""
        reference, shipment, principale = self._dossier_facture()
        lignes_avant = list(principale.invoice_line_ids.mapped("id"))

        self._service_ligne().add_late_line(reference, self._ligne_tardive())

        principale.invalidate_recordset()
        self.assertEqual(principale.state, "posted")
        self.assertAlmostEqual(principale.amount_total, 17.75, places=2)
        self.assertEqual(list(principale.invoice_line_ids.mapped("id")), lignes_avant)
        self.assertEqual(len(shipment.sudo().package_ids), 2)

        # Le colis tardif est tarifé et compté comme non facturé.
        resume = self._resume(shipment)
        self.assertEqual(resume["billing"]["unbilled_lines_count"], 1)
        self.assertAlmostEqual(resume["billing"]["unbilled_amount"], 5.0, places=2)
        self.assertEqual(resume["billing"]["invoice_number"], principale.name)
        self.assertAlmostEqual(resume["billing"]["invoice_amount"], 17.75, places=2)

    def test_the_supplement_carries_only_the_late_package(self):
        reference, shipment, principale = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())

        complement, cree, nature = shipment.sudo()._prepare_freight_invoice()

        self.assertTrue(cree)
        self.assertEqual(nature, "supplement")
        self.assertEqual(complement.state, "draft")
        self.assertAlmostEqual(complement.amount_untaxed, 5.0, places=2)
        self.assertEqual(len(complement.invoice_line_ids), 1)
        self.assertNotEqual(complement, principale)
        self.assertAlmostEqual(principale.amount_total, 17.75, places=2)
        self.assertEqual(len(shipment.sudo()._supplement_orders()), 1)
        self.assertEqual(len(shipment.sudo()._supplement_invoices()), 1)

    def test_replaying_the_same_late_add_creates_nothing_more(self):
        """REPLAY : le même `request_uuid` rend le même résultat."""
        reference, shipment, _principale = self._dossier_facture()
        demande = self._ligne_tardive()

        premier = self._service_ligne().add_late_line(reference, demande)
        second = self._service_ligne().add_late_line(reference, demande)

        self.assertEqual(second["line"]["reference"], premier["line"]["reference"])
        self.assertEqual(len(shipment.sudo().package_ids), 2)
        shipment.sudo()._prepare_freight_invoice()
        self.assertEqual(len(shipment.sudo()._supplement_orders()), 1)
        self.assertEqual(len(shipment.sudo()._supplement_invoices()), 1)

    def test_preparing_the_supplement_twice_yields_one_document(self):
        """Double clic sur « émettre le complément » : une seule pièce."""
        reference, shipment, _principale = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())

        premier, cree_1, _n1 = shipment.sudo()._prepare_freight_invoice()
        second, cree_2, _n2 = shipment.sudo()._prepare_freight_invoice()

        self.assertTrue(cree_1)
        self.assertFalse(cree_2)
        self.assertEqual(second, premier)
        self.assertEqual(len(shipment.sudo()._supplement_invoices()), 1)

    def test_the_same_line_reference_is_refused_twice(self):
        """Deux gestes distincts visant la même ligne : le second est refusé."""
        reference, shipment, _principale = self._dossier_facture()
        uuid_ligne = str(uuid.uuid4())
        self._service_ligne().add_late_line(
            reference, self._ligne_tardive(uuid_ligne=uuid_ligne))

        with self.assertRaises(Exception) as capture:
            self._service_ligne().add_late_line(
                reference, self._ligne_tardive(
                    description="Autre", uuid_ligne=uuid_ligne))

        self.assertIn("existe déjà", str(capture.exception))
        self.assertEqual(len(shipment.sudo().package_ids), 2)

    def test_a_late_add_is_refused_while_the_invoice_is_draft(self):
        reference, shipment = self._creer_dossier(poids=3.55)
        shipment.action_prepare_native_freight_invoice()

        with self.assertRaises(Exception) as capture:
            self._service_ligne().add_late_line(reference, self._ligne_tardive())

        self.assertIn("comptabilis", str(capture.exception).lower())
        self.assertEqual(len(shipment.sudo().package_ids), 1)

    def test_a_late_add_is_refused_on_a_dossier_never_billed(self):
        reference, shipment = self._creer_dossier(poids=3.55)

        with self.assertRaises(Exception):
            self._service_ligne().add_late_line(reference, self._ligne_tardive())

        self.assertEqual(len(shipment.sudo().package_ids), 1)

    def test_an_old_invoiced_package_stays_untouchable(self):
        """L'ouverture au colis tardif ne rouvre pas les anciens."""
        reference, shipment, _principale = self._dossier_facture()
        ancien = shipment.sudo().package_ids[0]

        with self.assertRaises(Exception):
            ancien.write({"unit_weight_kg": 99.0})
        with self.assertRaises(Exception):
            ancien.unlink()
