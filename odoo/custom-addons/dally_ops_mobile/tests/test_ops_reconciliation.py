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


class SocleReconciliation(AccountTestInvoicingCommon):
    """Le décor partagé : une société, deux opérateurs, un départ, un tarif.

    Sans méthode `test_`, donc sans test à lui. Il existe pour que la
    réconciliation et la supervision travaillent sur le même montage : deux
    décors parallèles finiraient par diverger, et un test passerait sur un
    monde que l'autre ne connaît pas.
    """

    @classmethod
    def setUpClass(cls):
        """Prépare les fixtures communes aux scénarios de réconciliation."""
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        # Une base installée sans données de démonstration laisse l'euro
        # inactif, et Odoo refuse alors de comptabiliser une pièce libellée
        # dans cette devise. Ces tests posent des factures : ils doivent donc
        # préparer eux-mêmes ce dont ils dépendent, plutôt que d'exiger un banc
        # préparé à la main — un test qui ne passe que sur une base particulière
        # ne dit plus rien sur le code.
        cls.env.ref("base.EUR").active = True

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
        """Crée un compte de test avec le rôle Ops demandé."""
        return cls.env["res.users"].create({
            "name": prefixe, "login": "%s.%s" % (prefixe, uuid.uuid4().hex[:6]),
            "group_ids": [(6, 0, [cls.env.ref(groupe).id])],
            "company_id": cls.env.company.id,
            "company_ids": [(6, 0, [cls.env.company.id])],
            "dally_ops_cash_actor": "Gilles",
        })

    @classmethod
    def _consolidation(cls, reference):
        """Crée une consolidation de test dans l'état demandé."""
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
        """Crée un dossier synthétique destiné aux scénarios de réconciliation."""
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

    def _ligne_tardive(self, description="Crème cheveux", poids=1.0, uuid_ligne=None):
        """Construit une charge synthétique d'article tardif."""
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
        """Retourne le service de mutation des lignes sous l'utilisateur de test."""
        return (self.env["dally.ops.intake.line.service"]
                .with_user(utilisateur or self.gilles).with_company(self.societe))

    def _dossier_facture(self):
        """Un dossier scénario tardif synthétique : 3,55 kg à 5 €/kg = 17,75 €, comptabilisé."""
        reference, shipment = self._creer_dossier(poids=3.55)
        facture = shipment.action_prepare_native_freight_invoice()
        facture.action_post()
        self.assertEqual(facture.state, "posted")
        self.assertAlmostEqual(facture.amount_total, 17.75, places=2)
        return reference, shipment, facture

    def _resume(self, shipment, utilisateur=None):
        """Retourne le résumé de réconciliation du dossier de test."""
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
                SocleReconciliation._cles(valeur, vues)
        elif isinstance(noeud, list):
            for element in noeud:
                SocleReconciliation._cles(element, vues)
        return vues

    # ------------------------------------------------------------------
    # Le dossier neuf
    # ------------------------------------------------------------------


@tagged("post_install", "-at_install", "dally")
class TestOpsReconciliation(SocleReconciliation):

    def test_a_fresh_dossier_reports_recorded_and_unbilled(self):
        """Vérifie le scénario « a fresh dossier reports recorded and unbilled »."""
        _reference, shipment = self._creer_dossier()
        resume = self._resume(shipment)

        self.assertEqual(resume["crm"]["state"], "recorded")
        self.assertEqual(resume["crm"]["reference"], shipment.external_reference)
        self.assertEqual(resume["billing"]["primary_invoice_state"], "none")
        self.assertIsNone(resume["billing"]["primary_invoice_number"])
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
        """Vérifie le scénario « a posted invoice is reported by number and amount »."""
        _reference, shipment = self._creer_dossier()
        facture = shipment.action_prepare_native_freight_invoice()
        facture.action_post()

        resume = self._resume(shipment)

        self.assertEqual(resume["billing"]["primary_invoice_state"], "posted")
        self.assertEqual(resume["billing"]["primary_invoice_number"], facture.name)
        self.assertAlmostEqual(
            resume["billing"]["primary_invoice_amount"], facture.amount_total, places=2)
        self.assertAlmostEqual(
            resume["billing"]["primary_remaining_amount"], facture.amount_residual, places=2)
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
        """Vérifie le scénario « the outbox vocabulary is translated for the operator »."""
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

    def test_one_projection_per_dossier_and_company(self):
        """Le modèle garantit l'unicité ; la lecture s'appuie dessus.

        `UNIQUE(company_id, projection_type, business_key)` interdit une
        seconde projection `freight_dossier` pour le même dossier. L'agrégation
        « la pire parle » reste dans le service — elle protège le jour où
        d'autres types de projection entreront dans la lecture — mais elle n'a
        aujourd'hui qu'une seule ligne à considérer, et ce test le fixe.
        """
        _reference, shipment = self._creer_dossier()
        ligne = self._projection(shipment, "delivered")

        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                ligne.sudo().copy({"state": "failed"})

        self.assertEqual(self._resume(shipment)["sheet"]["state"], "synced")

    def test_a_projection_of_another_type_never_speaks_for_the_dossier(self):
        """Seules les projections de dossier comptent pour l'état du dossier."""
        _reference, shipment = self._creer_dossier()
        self._projection(shipment, "delivered")
        cle = self.env["dally.ops.sheet.outbox"].business_key_for(shipment)
        self.env["dally.ops.sheet.outbox"].sudo().create({
            "company_id": shipment.company_id.id,
            "projection_type": "cash_expense",
            "business_key": cle,
            "resource_model": "dally.shipment", "resource_id": shipment.id,
            "resource_reference": shipment.external_reference, "state": "failed",
        })

        self.assertEqual(self._resume(shipment)["sheet"]["state"], "synced")

    def test_a_transport_error_never_reaches_the_operator(self):
        """Vérifie le scénario « a transport error never reaches the operator »."""
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

    def test_no_projection_relaunch_is_published_without_a_route_to_run_it(self):
        """`resync_sheet` n'est annoncée à personne — pas même au responsable.

        Elle l'était, et c'était le défaut : aucune route ne l'expose. Relancer
        une projection est une mutation, et la surface mutante de l'API Ops
        attend d'abord sa protection inter-origine. Annoncer l'action donnerait
        à l'écran un bouton sans destination.

        Le test vaut pour les deux rôles : c'est la disponibilité du geste qui
        manque, pas le droit de le faire.
        """
        _reference, shipment = self._creer_dossier()
        self.env["dally.ops.sheet.outbox"].enqueue_dossier(shipment)
        ligne = self.env["dally.ops.sheet.outbox"].sudo().search(
            [("company_id", "=", self.societe.id)], order="id desc", limit=1)
        ligne.write({"state": "failed"})

        for utilisateur in (self.gilles, self.responsable):
            self.assertNotIn(
                "resync_sheet",
                self._resume(shipment, utilisateur)["allowed_actions"])

    def test_a_healthy_projection_offers_no_relaunch(self):
        """Vérifie le scénario « a healthy projection offers no relaunch »."""
        _reference, shipment = self._creer_dossier()
        self._projection(shipment, "delivered")

        self.assertNotIn(
            "resync_sheet", self._resume(shipment, self.responsable)["allowed_actions"])

    def test_a_late_package_is_offered_only_once_the_invoice_is_posted(self):
        """Vérifie le scénario « a late package is offered only once the invoice is posted »."""
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
    # L'ajout tardif, après comptabilisation — le cas scénario tardif synthétique
    # ------------------------------------------------------------------

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
        self.assertEqual(resume["billing"]["primary_invoice_number"], principale.name)
        self.assertAlmostEqual(resume["billing"]["primary_invoice_amount"], 17.75, places=2)

    def test_the_supplement_carries_only_the_late_package(self):
        """Vérifie le scénario « the supplement carries only the late package »."""
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
        """Vérifie le scénario « a late add is refused while the invoice is draft »."""
        reference, shipment = self._creer_dossier(poids=3.55)
        shipment.action_prepare_native_freight_invoice()

        with self.assertRaises(Exception) as capture:
            self._service_ligne().add_late_line(reference, self._ligne_tardive())

        self.assertIn("comptabilis", str(capture.exception).lower())
        self.assertEqual(len(shipment.sudo().package_ids), 1)

    def test_a_late_add_is_refused_on_a_dossier_never_billed(self):
        """Vérifie le scénario « a late add is refused on a dossier never billed »."""
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

    # ------------------------------------------------------------------
    # L'isolation entre sociétés
    # ------------------------------------------------------------------

    def test_two_companies_sharing_a_reference_never_contaminate_each_other(self):
        """Deux dossiers homonymes dans deux sociétés restent étrangers.

        `sudo()` retire le filtre de société : sans le triplet autoritaire
        (société, type, clé métier), la projection de l'une parlerait pour
        l'autre. Le test le prouve dans les deux sens.
        """
        Outbox = self.env["dally.ops.sheet.outbox"].sudo()
        autre_societe = self.env["res.company"].create({"name": "Recon Autre"})
        reference = "AIR-DSS-CDG-RECON-HOMONYME"

        # `sync_source_key` est réservé au service métier : on ne le force pas.
        # Sans lui, la clé métier retombe sur la référence globale — et c'est
        # précisément le cas homonyme le plus dangereux, puisque les deux
        # sociétés partagent alors la même clé.
        dossiers = {}
        for societe, etat in ((self.societe, "delivered"), (autre_societe, "failed")):
            dossier = self.env["dally.shipment"].sudo().create({
                "partner_id": self.partner.id, "company_id": societe.id,
                "external_reference": reference,
                "transport_mode": "air", "direction": "export",
            })
            self.assertEqual(
                Outbox.business_key_for(dossier), reference,
                "les deux dossiers doivent bien partager la même clé métier")
            Outbox.create({
                "company_id": societe.id, "projection_type": "freight_dossier",
                "business_key": reference,
                "resource_model": "dally.shipment", "resource_id": dossier.id,
                "resource_reference": reference, "state": etat,
            })
            dossiers[etat] = dossier

        self.assertEqual(self._resume(dossiers["delivered"])["sheet"]["state"], "synced")
        self.assertEqual(self._resume(dossiers["failed"])["sheet"]["state"], "failed")

    def test_a_dossier_without_business_key_reports_no_projection(self):
        """Vérifie le scénario « a dossier without business key reports no projection »."""
        dossier = self.env["dally.shipment"].sudo().create({
            "partner_id": self.partner.id, "company_id": self.societe.id,
            "external_reference": "", "transport_mode": "air", "direction": "export",
        })
        self.assertEqual(self._resume(dossier)["sheet"]["state"], "absent")

    # ------------------------------------------------------------------
    # Les montants : principale et dossier, nommés pour ce qu'ils sont
    # ------------------------------------------------------------------

    def test_a_posted_supplement_enters_the_dossier_total(self):
        """Vérifie le scénario « a posted supplement enters the dossier total »."""
        reference, shipment, principale = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())
        complement, _cree, _n = shipment.sudo()._prepare_freight_invoice()

        # Tant que le complément est brouillon, il n'est pas dû.
        resume = self._resume(shipment)
        self.assertAlmostEqual(resume["billing"]["total_invoiced_amount"], 17.75, places=2)
        self.assertAlmostEqual(resume["billing"]["total_remaining_amount"], 17.75, places=2)

        complement.action_post()

        resume = self._resume(shipment)
        self.assertAlmostEqual(
            resume["billing"]["primary_remaining_amount"], 17.75, places=2)
        self.assertAlmostEqual(
            resume["billing"]["total_invoiced_amount"], 22.75, places=2)
        self.assertAlmostEqual(
            resume["billing"]["total_remaining_amount"], 22.75, places=2,
            msg="le complément comptabilisé doit entrer dans le reste à payer")

    def test_a_cancelled_supplement_leaves_the_total_alone(self):
        """Vérifie le scénario « a cancelled supplement leaves the total alone »."""
        reference, shipment, _principale = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())
        complement, _cree, _n = shipment.sudo()._prepare_freight_invoice()
        complement.button_cancel()

        resume = self._resume(shipment)

        self.assertAlmostEqual(resume["billing"]["total_invoiced_amount"], 17.75, places=2)
        self.assertAlmostEqual(resume["billing"]["total_remaining_amount"], 17.75, places=2)

    # ------------------------------------------------------------------
    # La valorisation : celle de la facturation, pas une seconde
    # ------------------------------------------------------------------

    def test_the_unbilled_amount_uses_the_billing_valuation(self):
        """Aucune divergence entre Ops et le champ autoritaire de Freight."""
        reference, shipment, _principale = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())

        en_attente = shipment.sudo()._pending_packages()
        resume = self._resume(shipment)

        self.assertAlmostEqual(
            resume["billing"]["unbilled_amount"],
            sum(en_attente.mapped("transport_amount_eur")), places=2)

    def test_a_quote_package_is_worth_nothing_until_it_is_priced(self):
        """Un « sur devis » n'a pas de prix : le compter serait inventer."""
        reference, shipment, _principale = self._dossier_facture()
        demande = self._ligne_tardive()
        demande["line"]["billing_method"] = "quote"
        self._service_ligne().add_late_line(reference, demande)

        resume = self._resume(shipment)

        self.assertEqual(resume["billing"]["unbilled_lines_count"], 1)
        self.assertAlmostEqual(resume["billing"]["unbilled_amount"], 0.0, places=2)

    # ------------------------------------------------------------------
    # Aucune action impossible n'est annoncée
    # ------------------------------------------------------------------

    def test_no_action_is_published_without_a_screen_to_run_it(self):
        """Vérifie le scénario « no action is published without a screen to run it »."""
        reference, shipment, _principale = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())

        for utilisateur in (self.gilles, self.responsable):
            actions = self._resume(shipment, utilisateur)["allowed_actions"]
            self.assertNotIn("prepare_supplement", actions)

    def test_no_late_package_is_offered_once_the_consolidation_closes(self):
        """Annoncer un geste que l'API refusera aussitôt serait une promesse vide."""
        _reference, shipment, _principale = self._dossier_facture()
        self.assertIn("add_late_package", self._resume(shipment)["allowed_actions"])

        # Par l'action métier : l'état d'une consolidation ne s'écrit pas
        # directement, et le test n'a pas à contourner ce garde.
        self.depart.sudo().action_close_collection()

        self.assertNotIn("add_late_package", self._resume(shipment)["allowed_actions"])
        # Pas de remise en état : chaque test Odoo est annulé en fin de course.
