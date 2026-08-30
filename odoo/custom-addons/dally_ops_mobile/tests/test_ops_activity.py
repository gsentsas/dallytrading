# -*- coding: utf-8 -*-
"""Le journal métier public, sans exposer la table d'audit interne."""

import json
import uuid
from datetime import timedelta

from odoo import fields
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsNotFound


@tagged("post_install", "-at_install", "dally")
class TestOpsActivity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Ops Journal SA"})
        cls.other_company = cls.env["res.company"].create({"name": "Ops Journal Autre"})
        cls.gilles = cls._user(
            "journal.gilles", "Gilles Journal",
            "dally_ops_mobile.group_dally_ops_logistician", cls.company)
        cls.dalanda = cls._user(
            "journal.dalanda", "Dalanda Journal",
            "dally_ops_mobile.group_dally_ops_logistician", cls.company)
        cls.supervisor = cls._user(
            "journal.supervisor", "Responsable Journal",
            "dally_ops_mobile.group_dally_ops_supervisor", cls.company)
        cls.other_user = cls._user(
            "journal.other", "Autre Société",
            "dally_ops_mobile.group_dally_ops_logistician", cls.other_company)
        cls.partner = cls.env["res.partner"].create({
            "name": "Client Journal", "company_id": cls.company.id})
        cls.other_partner = cls.env["res.partner"].create({
            "name": "Client Autre", "company_id": cls.other_company.id})
        cls.family = cls.env["dally.freight.tariff.family"].create({
            "name": "Journal non alimentaire", "code": "journal_non_food"})
        cls.consolidation = cls._consolidation(cls.company, "AIR-JOURNAL-001")
        cls.other_consolidation = cls._consolidation(
            cls.other_company, "AIR-JOURNAL-AUTRE")
        cls.shipment = cls._shipment(
            cls.company, cls.partner, cls.consolidation, cls.gilles)
        cls.other_shipment = cls._shipment(
            cls.other_company, cls.other_partner, cls.other_consolidation,
            cls.other_user)
        cls.package = cls.shipment.package_ids[:1]
        # Les dossiers de fixture passent volontairement par le vrai service,
        # qui journalise leur création. Chaque test construit ensuite son jeu
        # d'événements exact ; retirer ces deux traces de fixture évite qu'elles
        # contaminent les assertions de pagination et d'isolation.
        cls.env.cr.execute(
            "DELETE FROM dally_ops_audit_event WHERE company_id IN %s",
            [tuple((cls.company | cls.other_company).ids)],
        )
        cls.env["dally.ops.audit.event"].invalidate_model()

    @classmethod
    def _user(cls, login, name, group, company):
        return cls.env["res.users"].create({
            "name": name, "login": login,
            "group_ids": [(6, 0, [cls.env.ref(group).id])],
            "company_id": company.id,
            "company_ids": [(6, 0, [company.id])],
            "tz": "Africa/Dakar",
        })

    @classmethod
    def _consolidation(cls, company, name):
        return cls.env["dally.freight.consolidation"].with_company(company).create({
            "name": name, "company_id": company.id, "state": "collecting",
            "active": True, "transport_mode": "air", "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })

    @classmethod
    def _shipment(cls, company, partner, consolidation, user):
        """Crée le dossier par le vrai service, jamais via l'identité protégée."""
        handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": partner.id, "company_id": company.id,
        })
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "consolidation_reference": consolidation.name,
            "customer_reference": handle.token,
            "received_on": "2026-08-30",
            "line": {
                "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
                "goods_category": "Non alimentaire", "description": "Savon",
                "quantity": 1, "announced_weight_kg": None,
                "exact_weight_kg": 13.5, "length_cm": None,
                "width_cm": None, "height_cm": None,
                "billing_method": "quote", "tariff_family_code": cls.family.code,
                "customs_value_xof": 25000,
            },
        }
        result = (cls.env["dally.ops.intake.service"]
                  .with_user(user).with_company(company).create_intake(payload))
        return cls.env["dally.shipment"].sudo().search([
            ("company_id", "=", company.id),
            ("external_reference", "=", result["intake"]["reference"]),
        ], limit=1)

    def setUp(self):
        super().setUp()
        self.Audit = self.env["dally.ops.audit.event"].sudo()

    def _event(self, action="intake_created", *, user=None, company=None,
               entity=None, request_uuid=None, created_at="2026-08-30 08:00:00",
               changes=None):
        company = company or self.company
        user = user or self.gilles
        entity = entity or self.shipment
        return self.Audit.create({
            "company_id": company.id, "operator_user_id": user.id,
            "action": action, "entity_model": entity._name,
            "entity_res_id": entity.id,
            "request_uuid": request_uuid or str(uuid.uuid4()),
            "created_at": created_at, "changes_json": changes or [],
        })

    def _service(self, user=None, company=None):
        return (self.env["dally.ops.activity.service"]
                .with_user(user or self.gilles)
                .with_company(company or self.company))

    def test_reception_dto_est_metier_et_sans_identifiant_interne(self):
        self._event()
        result = self._service().list_activity(date="2026-08-30")
        event = result["events"][0]
        self.assertEqual(event["label"], "Réception enregistrée")
        self.assertEqual(event["actor"], "Gilles Journal")
        self.assertEqual(event["dossier_label"], "A001")
        self.assertEqual(event["summary"], "Dossier A001")
        rendered = json.dumps(event)
        for forbidden in ("request_uuid", "entity_res_id", "operator_user_id",
                          "shipment_id", '"id"'):
            self.assertNotIn(forbidden, rendered)

    def test_mes_saisies_et_vue_equipe_respectent_le_role(self):
        self._event(user=self.gilles)
        self._event(action="intake_line_added", user=self.dalanda, entity=self.package)
        mine = self._service(self.gilles).list_activity(date="2026-08-30")
        self.assertEqual([e["actor"] for e in mine["events"]], ["Gilles Journal"])
        team = self._service(self.supervisor).list_activity(
            date="2026-08-30", scope="team")
        self.assertEqual({e["actor"] for e in team["events"]},
                         {"Gilles Journal", "Dalanda Journal"})
        with self.assertRaises(AccessError):
            self._service(self.gilles).list_activity(
                date="2026-08-30", scope="team")

    def test_company_isolation_generale_et_dossier(self):
        self._event()
        self._event(user=self.other_user, company=self.other_company,
                    entity=self.other_shipment)
        own = self._service().list_activity(date="2026-08-30")
        self.assertEqual(len(own["events"]), 1)
        with self.assertRaises(DallyOpsNotFound):
            self._service().intake_activity(self.other_shipment.external_reference)
        with self.assertRaises(ValidationError):
            self.Audit.create({
                "company_id": self.company.id,
                "operator_user_id": self.other_user.id,
                "shipment_id": self.shipment.id,
                "action": "intake_created",
                "request_uuid": str(uuid.uuid4()),
            })

    def test_une_trace_etrangere_ne_peut_meme_pas_designer_mon_dossier(self):
        """La barrière est à l'écriture, pas seulement à la lecture.

        L'agrégation d'une timeline retrouve les événements par
        ``entity_model``/``entity_res_id`` autant que par l'ancre. Ces deux
        champs sont libres — mais l'ancre en est **dérivée** à la création,
        puis validée : une société ne peut donc pas écrire une trace qui
        désigne le dossier d'une autre, quelle que soit la façon de la
        désigner. Le filtre société de la lecture reste, mais il ne porte plus
        seul.
        """
        for anchor in (
            {"entity_model": "dally.shipment", "entity_res_id": self.shipment.id},
            {"entity_model": "dally.shipment.package",
             "entity_res_id": self.package.id},
        ):
            with self.assertRaises(ValidationError):
                self.Audit.create(dict({
                    "company_id": self.other_company.id,
                    "operator_user_id": self.other_user.id,
                    "action": "payment_recorded",
                    "request_uuid": str(uuid.uuid4()),
                }, **anchor))

        # Et rien n'a été écrit : la timeline ne montre que ce qui la regarde.
        self._event(created_at="2026-08-30 07:43:00")
        page = self._service().intake_activity(self.shipment.external_reference)
        self.assertEqual([e["event"] for e in page["events"]], ["intake_created"])

    def test_timeline_dossier_agrege_reception_article_et_paiement(self):
        self._event(created_at="2026-08-30 07:43:00")
        self._event(action="intake_line_added", entity=self.package,
                    created_at="2026-08-30 07:44:00")
        page = self._service().intake_activity(self.shipment.external_reference)
        self.assertEqual(page["dossier_label"], "A001")
        self.assertEqual([e["event"] for e in page["events"]],
                         ["intake_line_added", "intake_created"])
        self.assertEqual(page["events"][0]["summary"], "Savon — 13,5 kg")

    def test_correction_conserve_old_new_structurellement(self):
        self._event(action="intake_line_updated", entity=self.package, changes=[{
            "field": "exact_weight_kg", "old_value": 7.8, "new_value": 8.1,
        }])
        event = self._service().intake_activity(
            self.shipment.external_reference)["events"][0]
        self.assertEqual(event["changes"], [{
            "field": "exact_weight_kg", "label": "Poids exact",
            "old_value": "7,8 kg", "new_value": "8,1 kg",
        }])
        self.assertEqual(event["summary"], "7,8 kg → 8,1 kg")

    def test_replay_identique_ne_duplique_pas_l_evenement(self):
        request_uuid = str(uuid.uuid4())
        first = self._event(request_uuid=request_uuid)
        second = self._event(request_uuid=request_uuid)
        self.assertEqual(first, second)
        self.assertEqual(self.Audit.search_count([
            ("company_id", "=", self.company.id),
            ("action", "=", "intake_created"),
            ("request_uuid", "=", request_uuid),
        ]), 1)

    def test_deux_operations_distinctes_restent_deux_evenements(self):
        self._event(request_uuid=str(uuid.uuid4()))
        self._event(request_uuid=str(uuid.uuid4()))
        self.assertEqual(len(self._service().list_activity(
            date="2026-08-30")["events"]), 2)

    def test_replays_et_retry_sheet_ne_polluent_pas_la_timeline(self):
        self._event()
        self._event(action="intake_request_replayed")
        self.env["dally.ops.sheet.outbox"].sudo().create({
            "company_id": self.company.id, "projection_type": "freight_dossier",
            "business_key": "ops:journal-a168", "resource_model": "dally.shipment",
            "resource_id": self.shipment.id, "state": "retry",
            "next_attempt_at": "2099-01-01 00:00:00", "last_error": "google indisponible",
        })
        events = self._service().list_activity(date="2026-08-30")["events"]
        self.assertEqual([e["event"] for e in events], ["intake_created"])

    def test_pagination_keyset_est_bornee(self):
        for minute in range(3):
            self._event(created_at="2026-08-30 08:0%d:00" % minute)
        first = self._service().list_activity(date="2026-08-30", limit=2)
        self.assertEqual(len(first["events"]), 2)
        self.assertTrue(first["next_cursor"])
        second = self._service().list_activity(
            date="2026-08-30", limit=2, cursor=first["next_cursor"])
        self.assertEqual(len(second["events"]), 1)
        self.assertFalse(second["next_cursor"])

    def test_aujourd_hui_utilise_la_borne_locale_dakar(self):
        self._event(created_at="2026-08-29 23:59:59")
        self._event(created_at="2026-08-30 00:00:00")
        events = self._service().list_activity(date="2026-08-30")["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["occurred_at"], "2026-08-30T00:00:00Z")

    def test_aujourd_hui_suit_le_fuseau_de_l_operateur_et_non_UTC(self):
        """Dakar est à UTC+0 : un test qui n'utilise que Dakar ne prouve rien.

        Un opérateur dont le fuseau est renseigné doit voir sa propre journée.
        Avec une lecture naïve en UTC, l'événement de 23h30 à Paris — donc du
        31 pour lui — serait rangé au 30, et « mes saisies du jour » perdrait
        la dernière heure de travail chaque soir.
        """
        self.gilles.sudo().write({"tz": "Europe/Paris"})
        # 21:30 UTC le 30 = 23:30 à Paris le 30.
        veille = self._event(created_at="2026-08-30 21:30:00")
        # 22:30 UTC le 30 = 00:30 à Paris le **31**.
        lendemain = self._event(created_at="2026-08-30 22:30:00")

        jour_30 = self._service().list_activity(date="2026-08-30")
        jour_31 = self._service().list_activity(date="2026-08-31")
        self.assertEqual(jour_30["timezone"], "Europe/Paris")
        self.assertEqual([e["occurred_at"] for e in jour_30["events"]],
                         ["2026-08-30T21:30:00Z"])
        self.assertEqual([e["occurred_at"] for e in jour_31["events"]],
                         ["2026-08-30T22:30:00Z"])
        self.assertTrue(veille and lendemain)

    def test_la_charge_utile_dit_dans_quel_fuseau_elle_a_ete_comptee(self):
        self._event()
        page = self._service().list_activity(date="2026-08-30")
        self.assertEqual(page["timezone"], "Africa/Dakar")
        dossier = self._service().intake_activity(self.shipment.external_reference)
        self.assertEqual(dossier["timezone"], "Africa/Dakar")

    def test_la_base_refuse_un_doublon_de_rejeu_meme_sans_l_orm(self):
        """La garantie tient sans le code, donc aussi sous concurrence.

        La lecture avant écriture de ``create`` suffit tant que les deux appels
        se suivent. Deux transactions concurrentes peuvent l'une et l'autre ne
        rien trouver avant d'insérer ; seule la base tranche alors. Le banc
        partagé ne permet pas de lancer deux vraies transactions Odoo
        simultanées — on éprouve donc la contrainte elle-même, en contournant
        l'ORM par un INSERT direct.
        """
        request_uuid = str(uuid.uuid4())
        premier = self._event(request_uuid=request_uuid)
        with self.assertRaises(IntegrityError):
            with mute_logger("odoo.sql_db"), self.env.cr.savepoint():
                self.env.cr.execute(
                    """
                    INSERT INTO dally_ops_audit_event
                        (event_uuid, company_id, operator_user_id, action,
                         entity_model, entity_res_id, request_uuid, created_at,
                         changes_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [str(uuid.uuid4()), self.company.id, self.gilles.id,
                     premier.action, premier.entity_model, premier.entity_res_id,
                     request_uuid, "2026-08-30 08:00:00", "[]"],
                )

    def test_deux_actions_du_meme_envoi_restent_deux_evenements(self):
        """Un même geste terrain produit parfois plusieurs actions distinctes.

        Une unicité portée sur le seul ``request_uuid`` les aurait fusionnées.
        """
        request_uuid = str(uuid.uuid4())
        self._event(action="intake_created", request_uuid=request_uuid)
        self._event(action="intake_line_added", entity=self.package,
                    request_uuid=request_uuid)
        actions = [e["event"] for e in self._service().list_activity(
            date="2026-08-30")["events"]]
        self.assertEqual(sorted(actions), ["intake_created", "intake_line_added"])

    def test_pagination_couvre_le_vide_la_page_pleine_et_le_debordement(self):
        vide = self._service().list_activity(date="2026-08-30")
        self.assertEqual(vide["events"], [])
        self.assertIsNone(vide["next_cursor"])

        self._event(created_at="2026-08-30 08:00:00")
        une = self._service().list_activity(date="2026-08-30", limit=25)
        self.assertEqual(len(une["events"]), 1)
        self.assertIsNone(une["next_cursor"])

        for minute in range(1, 26):
            self._event(created_at="2026-08-30 08:%02d:00" % minute)
        pleine = self._service().list_activity(date="2026-08-30", limit=25)
        self.assertEqual(len(pleine["events"]), 25)
        self.assertTrue(pleine["next_cursor"])
        suite = self._service().list_activity(
            date="2026-08-30", limit=25, cursor=pleine["next_cursor"])
        self.assertEqual(len(suite["events"]), 1)
        self.assertIsNone(suite["next_cursor"])

        # Aucun doublon ni trou entre les deux pages.
        instants = [e["occurred_at"] for e in pleine["events"] + suite["events"]]
        self.assertEqual(len(set(instants)), 26)

        self.assertEqual(len(self._service().list_activity(
            date="2026-08-30", limit=100)["events"]), 26)

    def test_deux_evenements_au_meme_instant_ne_se_perdent_pas_entre_deux_pages(self):
        """Le curseur porte l'identifiant, sinon l'un des deux disparaît."""
        for _ in range(3):
            self._event(created_at="2026-08-30 08:00:00")
        premiere = self._service().list_activity(date="2026-08-30", limit=2)
        seconde = self._service().list_activity(
            date="2026-08-30", limit=2, cursor=premiere["next_cursor"])
        self.assertEqual(len(premiere["events"]) + len(seconde["events"]), 3)

    def test_audit_est_immuable_meme_sous_sudo(self):
        event = self._event()
        with self.assertRaises(AccessError):
            event.write({"action": "payment_recorded"})
        with self.assertRaises(AccessError):
            event.unlink()

    def test_la_table_d_audit_reste_fermee_aux_comptes_de_terrain(self):
        """Le journal se lit par le service, jamais par le modèle.

        Aucune ACL n'ouvre `dally.ops.audit.event` aux groupes Ops : un
        logisticien ne peut donc ni le lire directement, ni y écrire, ni en
        supprimer une ligne. La vue publique passe entièrement par le service,
        qui décide de ce qui sort.
        """
        Audit = self.env["dally.ops.audit.event"]
        for utilisateur in (self.gilles, self.supervisor):
            for droit in ("read", "write", "create", "unlink"):
                self.assertFalse(
                    Audit.with_user(utilisateur).has_access(droit),
                    "%s ne doit pas avoir le droit %s" % (utilisateur.login, droit))

    def test_le_contrat_public_expose_exactement_les_champs_metier(self):
        self._event(action="intake_line_updated", entity=self.package, changes=[{
            "field": "description", "old_value": "Savon", "new_value": "Corrigé",
        }])
        event = self._service().list_activity(date="2026-08-30")["events"][0]
        self.assertEqual(set(event), {
            "event", "category", "label", "occurred_at", "actor",
            "dossier_reference", "dossier_label", "summary", "changes"})
        self.assertEqual(set(event["changes"][0]),
                         {"field", "label", "old_value", "new_value"})

    def test_aucune_route_ne_laisse_le_navigateur_ecrire_le_journal(self):
        """Les événements naissent des services métier, jamais d'un POST."""
        import ast
        import inspect
        from odoo.addons.dally_ops_mobile.controllers import ops_activity

        arbre = ast.parse(inspect.getsource(ops_activity))
        methodes = []
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.FunctionDef):
                continue
            for decorateur in noeud.decorator_list:
                if not isinstance(decorateur, ast.Call):
                    continue
                for mot in decorateur.keywords:
                    if mot.arg == "methods":
                        methodes.append(ast.literal_eval(mot.value))
        self.assertTrue(methodes)
        for autorisees in methodes:
            self.assertEqual(autorisees, ["GET"])
        code = ast.unparse(arbre)
        for interdit in ("create(", "write(", "unlink(", "sudo"):
            self.assertNotIn(interdit, code)

    def test_limite_type_et_curseur_invalides_sont_refuses(self):
        with self.assertRaises(Exception):
            self._service().list_activity(date="2026-08-30", limit=101)
        with self.assertRaises(Exception):
            self._service().list_activity(date="2026-08-30", event_type="sql")
        with self.assertRaises(Exception):
            self._service().list_activity(date="2026-08-30", cursor="pas-un-curseur")


@tagged("post_install", "-at_install", "dally")
class TestOpsActivityHttp(HttpCase):
    PASSWORD = "OpsActivity!2026#"

    def setUp(self):
        super().setUp()
        self.user = self.env["res.users"].create({
            "name": "Gilles HTTP Activité", "login": "activity.http",
            "password": self.PASSWORD,
            "group_ids": [(6, 0, [self.env.ref(
                "dally_ops_mobile.group_dally_ops_logistician").id])],
            "company_id": self.env.company.id,
            "company_ids": [(6, 0, [self.env.company.id])],
            "tz": "Africa/Dakar",
        })
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.user.id,
            "action": "appointment_recorded",
            "entity_model": "calendar.event", "entity_res_id": 0,
            "request_uuid": str(uuid.uuid4()),
        })

    def _get(self, path):
        self.authenticate("activity.http", self.PASSWORD)
        try:
            return self.url_open(path, timeout=30)
        finally:
            self.authenticate(None, None)

    def test_route_activite_est_authentifiee_bornee_et_sans_cache(self):
        response = self._get("/api/v1/ops/activity?limit=5")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        payload = response.json()["data"]
        self.assertEqual(len(payload["events"]), 1)
        rendered = json.dumps(payload)
        for forbidden in ("request_uuid", "entity_res_id", "operator_user_id"):
            self.assertNotIn(forbidden, rendered)

    def test_parametre_inconnu_et_limite_excessive_sont_refuses(self):
        self.assertEqual(self._get("/api/v1/ops/activity?sudo=1").status_code, 400)
        self.assertEqual(self._get("/api/v1/ops/activity?limit=5000").status_code, 400)


@tagged("post_install", "-at_install", "dally")
class TestOpsActivityServicesReels(AccountTestInvoicingCommon):
    """Le journal, alimenté par les vrais gestes métier.

    ## Pourquoi cette classe existe à côté de la précédente

    Les tests qui fabriquent un événement d'audit à la main vérifient la
    lecture : le DTO, la pagination, l'isolation. Ils ne prouvent rien sur la
    **production** — un service qui cesserait de journaliser les laisserait
    tous verts.

    Ici, chaque test appelle le service que le terrain appelle, puis relit le
    journal. Et chaque geste est rejoué avec le même ``request_uuid``, parce
    qu'un réseau qui coupe après le commit est le cas ordinaire, pas le cas
    limite : le rejeu doit rendre le même objet **et** la même ligne de
    journal.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        cls.xof = cls.setup_other_currency("XOF")
        cls.eur = cls.setup_other_currency("EUR")
        cls.societe = cls.env.company
        cls.societe.sudo().write({"dally_ops_wave_beneficiary": "Gilles"})

        cls.gilles = cls._compte("journal.reel.gilles", "Gilles Réel",
                                 "dally_ops_mobile.group_dally_ops_logistician",
                                 acteur="Gilles")
        cls.dalanda = cls._compte("journal.reel.dalanda", "Dalanda Réelle",
                                  "dally_ops_mobile.group_dally_ops_logistician",
                                  acteur="Dalanda")

        cls._canal("wave", "Wave", cls.xof)
        cls._canal("cash", "Espèces", cls.eur)

        Famille = cls.env["dally.freight.tariff.family"]
        cls.famille = Famille.search([("code", "=", "non_food")], limit=1) or \
            Famille.create({"name": "Journal réel", "code": "non_food"})
        cls.partner = cls.env["res.partner"].create({
            "name": "Aïssatou Journal", "company_id": cls.societe.id,
            "phone": "+221770000021",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": cls.partner.id, "company_id": cls.societe.id,
        })
        cls.consolidation = cls.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-JOURNAL-REEL", "state": "collecting",
            "active": True, "company_id": cls.societe.id, "transport_mode": "air",
            "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })

    # ─── Fabriques ───────────────────────────────────────────────────

    @classmethod
    def _compte(cls, login, nom, groupe, acteur=None):
        valeurs = {
            "name": nom, "login": login, "tz": "Africa/Dakar",
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

    # ─── Outils ──────────────────────────────────────────────────────

    def _as(self, service, utilisateur=None):
        return (self.env[service].with_user(utilisateur or self.gilles)
                .with_company(self.societe))

    def _journal(self, utilisateur=None, **kwargs):
        return self._as("dally.ops.activity.service", utilisateur).list_activity(
            date=fields.Date.context_today(self.env.user).isoformat(), **kwargs)

    def _dossier_journal(self, reference, utilisateur=None):
        return self._as("dally.ops.activity.service",
                        utilisateur).intake_activity(reference)

    def _compter(self, action, request_uuid):
        return self.env["dally.ops.audit.event"].sudo().search_count([
            ("company_id", "=", self.societe.id),
            ("action", "=", action),
            ("request_uuid", "=", request_uuid),
        ])

    def _saisie_article(self, **changements):
        ligne = {
            "line_uuid": str(uuid.uuid4()), "package_type": "parcel",
            "goods_category": "Non alimentaire", "description": "Savon",
            "quantity": 1, "announced_weight_kg": None, "exact_weight_kg": 13.5,
            "length_cm": None, "width_cm": None, "height_cm": None,
            "billing_method": "quote",
            "tariff_family_code": self.famille.code, "customs_value_xof": 25000,
        }
        ligne.update(changements)
        return ligne

    def _creer_dossier(self, utilisateur=None, request_uuid=None):
        charge = {
            "request_uuid": request_uuid or str(uuid.uuid4()),
            "consolidation_reference": self.consolidation.name,
            "customer_reference": self.handle.token,
            "received_on": fields.Date.context_today(self.env.user).isoformat(),
            "line": self._saisie_article(),
        }
        resultat = self._as("dally.ops.intake.service",
                            utilisateur).create_intake(charge)
        return resultat["intake"]["reference"], charge

    # ─── Réception ───────────────────────────────────────────────────

    def test_une_reception_reelle_ecrit_une_ligne_de_journal(self):
        reference, charge = self._creer_dossier()
        evenements = self._dossier_journal(reference)["events"]
        creation = [e for e in evenements if e["event"] == "intake_created"]
        self.assertEqual(len(creation), 1)
        self.assertEqual(creation[0]["label"], "Réception enregistrée")
        self.assertEqual(creation[0]["actor"], "Gilles Réel")
        self.assertEqual(creation[0]["dossier_reference"], reference)
        self.assertTrue(creation[0]["summary"].startswith("Dossier A"))
        self.assertEqual(self._compter("intake_created", charge["request_uuid"]), 1)

    def test_le_rejeu_d_une_reception_ne_double_pas_la_ligne(self):
        reference, charge = self._creer_dossier()
        rejeu = self._as("dally.ops.intake.service").create_intake(charge)
        self.assertEqual(rejeu["intake"]["reference"], reference)
        self.assertEqual(self._compter("intake_created", charge["request_uuid"]), 1)
        creation = [e for e in self._dossier_journal(reference)["events"]
                    if e["event"] == "intake_created"]
        self.assertEqual(len(creation), 1)

    # ─── Articles et corrections ─────────────────────────────────────

    def test_un_article_ajoute_puis_corrige_laisse_deux_traces_distinctes(self):
        reference, _ = self._creer_dossier()
        ajout = {"request_uuid": str(uuid.uuid4()),
                 "line": self._saisie_article(description="Tissu",
                                              exact_weight_kg=7.8)}
        ligne = self._as("dally.ops.intake.line.service").add_line(reference, ajout)
        line_uuid = ajout["line"]["line_uuid"]

        correction = {"request_uuid": str(uuid.uuid4()),
                      "expected_revision": ligne["line"]["revision"],
                      "line": self._saisie_article(
                          line_uuid=line_uuid, description="Tissu",
                          exact_weight_kg=8.1)}
        self._as("dally.ops.intake.line.service",
                 self.dalanda).update_line(reference, line_uuid, correction)

        evenements = self._dossier_journal(reference)["events"]
        ajouts = [e for e in evenements if e["event"] == "intake_line_added"]
        corrections = [e for e in evenements if e["event"] == "intake_line_updated"]
        self.assertEqual(len(corrections), 1)
        self.assertGreaterEqual(len(ajouts), 1)

        # L'ancien événement n'est pas remplacé : l'historique s'ajoute.
        self.assertEqual(corrections[0]["actor"], "Dalanda Réelle")
        poids = [c for c in corrections[0]["changes"]
                 if c["field"] == "exact_weight_kg"]
        self.assertEqual(poids, [{
            "field": "exact_weight_kg", "label": "Poids exact",
            "old_value": "7,8 kg", "new_value": "8,1 kg",
        }])
        self.assertEqual(self._compter(
            "intake_line_updated", correction["request_uuid"]), 1)

    def test_le_rejeu_d_un_ajout_d_article_ne_double_pas_la_ligne(self):
        reference, _ = self._creer_dossier()
        ajout = {"request_uuid": str(uuid.uuid4()),
                 "line": self._saisie_article(description="Tissu")}
        self._as("dally.ops.intake.line.service").add_line(reference, ajout)
        self._as("dally.ops.intake.line.service").add_line(reference, ajout)
        self.assertEqual(self._compter(
            "intake_line_added", ajout["request_uuid"]), 1)

    # ─── Paiements ───────────────────────────────────────────────────

    def test_un_encaissement_wave_reel_apparait_avec_son_montant(self):
        reference, _ = self._creer_dossier()
        charge = {"request_uuid": str(uuid.uuid4()), "amount": 100000.0,
                  "currency": "XOF", "wave_reference": "TWJOURNAL01",
                  "paid_at": fields.Date.context_today(self.env.user).isoformat(),
                  "note": ""}
        self._as("dally.ops.wave.payment.service").record_wave_payment(
            reference, charge)

        paiements = [e for e in self._dossier_journal(reference)["events"]
                     if e["event"] == "wave_payment_recorded"]
        self.assertEqual(len(paiements), 1)
        self.assertEqual(paiements[0]["label"], "Paiement Wave")
        self.assertEqual(paiements[0]["summary"], "100 000 FCFA")
        self.assertEqual(paiements[0]["actor"], "Gilles Réel")

        # Rejeu du même envoi : un paiement, une ligne.
        self._as("dally.ops.wave.payment.service").record_wave_payment(
            reference, charge)
        self.assertEqual(self._compter(
            "wave_payment_recorded", charge["request_uuid"]), 1)

    def test_deux_encaissements_reels_restent_deux_lignes(self):
        reference, _ = self._creer_dossier()
        for montant, wave in ((100000.0, "TWJOURNAL02"), (50000.0, "TWJOURNAL03")):
            self._as("dally.ops.wave.payment.service").record_wave_payment(
                reference, {
                    "request_uuid": str(uuid.uuid4()), "amount": montant,
                    "currency": "XOF", "wave_reference": wave,
                    "paid_at": fields.Date.context_today(self.env.user).isoformat(),
                    "note": ""})
        resumes = [e["summary"] for e in self._dossier_journal(reference)["events"]
                   if e["event"] == "wave_payment_recorded"]
        self.assertEqual(sorted(resumes), ["100 000 FCFA", "50 000 FCFA"])

    def test_un_paiement_en_euros_garde_ses_centimes(self):
        """L'arrondi à l'unité aurait transformé 67,50 € en 68 €."""
        reference, _ = self._creer_dossier()
        self._as("dally.ops.payment.service").record_payment(reference, {
            "request_uuid": str(uuid.uuid4()), "amount": 67.5,
            "payment_date": fields.Date.context_today(self.env.user).isoformat(),
            "payment_method": "cash", "currency_code": "EUR",
        })
        paiements = [e for e in self._dossier_journal(reference)["events"]
                     if e["event"] == "payment_recorded"]
        self.assertEqual(len(paiements), 1)
        self.assertEqual(paiements[0]["summary"], "67,50 €")

    # ─── Caisse ──────────────────────────────────────────────────────

    def test_une_depense_reelle_apparait_dans_les_saisies_du_jour(self):
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "consolidation_reference": self.consolidation.name,
            "expense_date": fields.Date.context_today(self.env.user).isoformat(),
            "category": "Manutention", "description": "Portage entrepôt",
            "beneficiary": "Équipe entrepôt", "amount": 15000.0,
            "currency_code": "XOF", "payment_method": "cash", "comment": "",
        }
        self._as("dally.ops.expense.service").record_expense(charge)
        self._as("dally.ops.expense.service").record_expense(charge)

        depenses = [e for e in self._journal()["events"]
                    if e["event"] == "expense_recorded"]
        self.assertEqual(len(depenses), 1)
        self.assertEqual(depenses[0]["label"], "Dépense enregistrée")
        self.assertEqual(depenses[0]["summary"], "15 000 FCFA")
        self.assertEqual(self._compter("expense_recorded", charge["request_uuid"]), 1)

    def test_un_transfert_de_caisse_reel_apparait_avec_son_montant(self):
        charge = {
            "request_uuid": str(uuid.uuid4()), "to_actor": "Dalanda",
            "transfer_date": fields.Date.context_today(self.env.user).isoformat(),
            "amount": 100000.0, "currency_code": "XOF", "payment_method": "cash",
            "reason": "Remise caisse du soir", "comment": "",
        }
        self._as("dally.ops.cash.transfer.service").record_transfer(charge)
        self._as("dally.ops.cash.transfer.service").record_transfer(charge)

        transferts = [e for e in self._journal()["events"]
                      if e["event"] == "cash_transfer_recorded"]
        self.assertEqual(len(transferts), 1)
        self.assertEqual(transferts[0]["summary"], "100 000 FCFA")
        self.assertEqual(self._compter(
            "cash_transfer_recorded", charge["request_uuid"]), 1)

    # ─── Agenda ──────────────────────────────────────────────────────

    def test_un_rendez_vous_reel_et_ses_transitions_sont_journalises(self):
        demain = fields.Date.context_today(self.env.user) + timedelta(days=1)
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "customer_reference": self.handle.token, "kind": "dropoff",
            "start_at": "%sT10:00:00+00:00" % demain.isoformat(),
            "end_at": "%sT10:30:00+00:00" % demain.isoformat(),
            "consolidation_reference": self.consolidation.name,
            "location": "Dépôt Dakar", "note": "3 cartons annoncés",
        }
        rendu = self._as("dally.ops.appointment.service").create_appointment(charge)
        reference = rendu["appointment"]["reference"]
        self._as("dally.ops.appointment.service").create_appointment(charge)

        self._as("dally.ops.appointment.service").mark_present(
            reference, {"request_uuid": str(uuid.uuid4())})

        journal = self._journal()["events"]
        actions = [e["event"] for e in journal]
        self.assertEqual(actions.count("appointment_recorded"), 1)
        self.assertEqual(actions.count("appointment_marked_present"), 1)
        creation = [e for e in journal if e["event"] == "appointment_recorded"][0]
        # Le résumé dit quand, dans le fuseau de l'opérateur.
        self.assertIn(demain.strftime("%d/%m/%Y"), creation["summary"])
        self.assertEqual(self._compter(
            "appointment_recorded", charge["request_uuid"]), 1)

    # ─── Ce que le journal ne dit pas ────────────────────────────────

    def test_consulter_un_recu_n_ecrit_aucune_ligne_de_journal(self):
        """Un journal métier n'est pas un journal de navigation."""
        reference, _ = self._creer_dossier()
        avant = len(self._dossier_journal(reference)["events"])
        for _ in range(3):
            self._as("dally.ops.receipt.service").receipt_dto(reference)
        self._as("dally.ops.receipt.service").receipt_pdf(reference)
        self.assertEqual(
            len(self._dossier_journal(reference)["events"]), avant)

    def test_le_journal_reste_lisible_quand_la_projection_sheet_echoue(self):
        reference, _ = self._creer_dossier()
        boite = self.env["dally.ops.sheet.outbox"].sudo().search([
            ("company_id", "=", self.societe.id),
            ("projection_type", "=", "freight_dossier"),
        ])
        self.assertTrue(boite)
        boite.write({"state": "retry", "last_error": "google indisponible"})
        evenements = self._dossier_journal(reference)["events"]
        self.assertTrue(evenements)
        self.assertNotIn("sheet", json.dumps(evenements))
