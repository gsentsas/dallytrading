# -*- coding: utf-8 -*-
"""Décision devis portail : machine d'état, isolation et surface HTTP."""

import json
import threading
from unittest.mock import patch
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

from odoo import api
from odoo import SUPERUSER_ID
from odoo.sql_db import db_connect
from odoo.service.model import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..models.dally_quote_request import PortalQuoteDecisionConflict


PORTAL_PASSWORD = "PortalQuoteDecision!2026"


class QuoteDecisionFixture:

    @classmethod
    def _decision_users(cls):
        Partner = cls.env["res.partner"]
        Users = cls.env["res.users"]
        portal_group = cls.env.ref("base.group_portal")
        internal_group = cls.env.ref("base.group_user")

        cls.company_a = Partner.create({
            "name": "QUOTE DECISION Société A", "is_company": True,
        })
        cls.company_b = Partner.create({
            "name": "QUOTE DECISION Société B", "is_company": True,
        })
        cls.contact_a = Partner.create({
            "name": "QUOTE DECISION Contact A",
            "parent_id": cls.company_a.id,
            "email": "quote.decision.a@portal-test.invalid",
        })
        cls.contact_b = Partner.create({
            "name": "QUOTE DECISION Contact B",
            "parent_id": cls.company_b.id,
            "email": "quote.decision.b@portal-test.invalid",
        })
        cls.login_a = cls.contact_a.email
        cls.login_b = cls.contact_b.email
        cls.user_a = Users.create({
            "name": cls.contact_a.name,
            "login": cls.login_a,
            "password": PORTAL_PASSWORD,
            "partner_id": cls.contact_a.id,
            "group_ids": [(6, 0, [portal_group.id])],
        })
        cls.user_b = Users.create({
            "name": cls.contact_b.name,
            "login": cls.login_b,
            "password": PORTAL_PASSWORD,
            "partner_id": cls.contact_b.id,
            "group_ids": [(6, 0, [portal_group.id])],
        })
        cls.login_staff = "quote.decision.staff@portal-test.invalid"
        cls.staff = Users.create({
            "name": "QUOTE DECISION Staff",
            "login": cls.login_staff,
            "password": PORTAL_PASSWORD,
            "group_ids": [(6, 0, [internal_group.id])],
        })
        cls.service = cls.env["dally.service.type"].search([], limit=1)

    @classmethod
    def _make_quote(
        cls,
        tag,
        contact=None,
        request_state="quoted",
        order_state="sent",
    ):
        contact = contact or cls.contact_a
        quote = cls.env["dally.quote.request"].create({
            "partner_id": contact.id,
            "service_type_id": cls.service.id,
            "request_uuid": f"quote-decision-{tag}",
            "goods_description": f"QUOTE DECISION {tag}",
            "state": request_state,
        })
        if order_state is not None:
            cls.env["sale.order"].create({
                "partner_id": contact.id,
                "dally_quote_request_id": quote.id,
                "state": order_state,
            })
        return quote


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestPortalQuoteDecisionOrm(QuoteDecisionFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._decision_users()

    def test_portal_a_accepts_own_sent_quote_with_exact_identity(self):
        quote = self._make_quote("orm-accept")
        changed = quote.with_user(self.user_a)._dally_portal_decide("accept")

        quote.invalidate_recordset()
        self.assertTrue(changed)
        self.assertEqual(quote.state, "won")
        self.assertTrue(quote.customer_decision_at)
        self.assertEqual(quote.customer_decision_by_id, self.user_a)
        self.assertFalse(quote.customer_rejection_reason)

    def test_portal_a_rejects_own_sent_quote_with_optional_reason(self):
        quote = self._make_quote("orm-reject")
        changed = quote.with_user(self.user_a)._dally_portal_decide(
            "reject", "  Conditions non adaptées  ",
        )

        quote.invalidate_recordset()
        self.assertTrue(changed)
        self.assertEqual(quote.state, "lost")
        self.assertEqual(quote.customer_decision_by_id, self.user_a)
        self.assertEqual(
            quote.customer_rejection_reason, "Conditions non adaptées",
        )

    def test_cross_client_records_are_never_a_capability(self):
        quote_a = self._make_quote("orm-cross-a")
        quote_b = self._make_quote("orm-cross-b", contact=self.contact_b)

        with self.assertRaises(AccessError):
            quote_b.with_user(self.user_a)._dally_portal_decide("accept")
        with self.assertRaises(AccessError):
            quote_a.with_user(self.user_b)._dally_portal_decide("accept")

    def test_non_decidable_request_states_are_conflicts(self):
        for state in ("new", "qualified", "spam"):
            quote = self._make_quote(
                f"orm-state-{state}", request_state=state, order_state="sent",
            )
            with self.subTest(state=state), self.assertRaises(
                PortalQuoteDecisionConflict,
            ):
                quote.with_user(self.user_a)._dally_portal_decide("accept")

    def test_draft_and_cancelled_native_quotes_are_conflicts(self):
        for state in ("draft", "cancel"):
            quote = self._make_quote(
                f"orm-order-{state}", request_state="quoted", order_state=state,
            )
            with self.subTest(state=state), self.assertRaises(
                PortalQuoteDecisionConflict,
            ):
                quote.with_user(self.user_a)._dally_portal_decide("accept")

    def test_same_decision_is_idempotent_and_keeps_first_audit(self):
        quote = self._make_quote("orm-idempotent-accept")
        self.assertTrue(
            quote.with_user(self.user_a)._dally_portal_decide("accept"),
        )
        quote.invalidate_recordset()
        decided_at = quote.customer_decision_at
        decided_by = quote.customer_decision_by_id

        self.assertFalse(
            quote.with_user(self.user_a)._dally_portal_decide("accept"),
        )
        quote.invalidate_recordset()
        self.assertEqual(quote.customer_decision_at, decided_at)
        self.assertEqual(quote.customer_decision_by_id, decided_by)

    def test_same_rejection_is_idempotent_and_does_not_replace_reason(self):
        quote = self._make_quote("orm-idempotent-reject")
        quote.with_user(self.user_a)._dally_portal_decide("reject", "Premier motif")

        self.assertFalse(
            quote.with_user(self.user_a)._dally_portal_decide(
                "reject", "Motif concurrent",
            ),
        )
        quote.invalidate_recordset()
        self.assertEqual(quote.customer_rejection_reason, "Premier motif")

    def test_opposite_decisions_after_final_state_are_conflicts(self):
        accepted = self._make_quote("orm-accept-conflict")
        accepted.with_user(self.user_a)._dally_portal_decide("accept")
        with self.assertRaises(PortalQuoteDecisionConflict):
            accepted.with_user(self.user_a)._dally_portal_decide("reject")

        rejected = self._make_quote("orm-reject-conflict")
        rejected.with_user(self.user_a)._dally_portal_decide("reject")
        with self.assertRaises(PortalQuoteDecisionConflict):
            rejected.with_user(self.user_a)._dally_portal_decide("accept")

    def test_preexisting_staff_final_state_is_not_relabelled_as_customer_decision(self):
        for state, decision in (("won", "accept"), ("lost", "reject")):
            quote = self._make_quote(
                f"orm-staff-{state}", request_state=state, order_state="sent",
            )
            with self.subTest(state=state), self.assertRaises(
                PortalQuoteDecisionConflict,
            ):
                quote.with_user(self.user_a)._dally_portal_decide(decision)
            self.assertFalse(quote.customer_decision_at)

    def test_invalid_reason_and_decision_are_rejected_without_partial_write(self):
        for decision, reason in (
            ("maybe", None),
            ("accept", "reason forbidden"),
            ("reject", "x" * 501),
            ("reject", "<b>HTML</b>"),
            ("reject", "line\nbreak"),
        ):
            quote = self._make_quote(
                f"orm-invalid-{decision}-{len(reason or '')}",
            )
            with self.subTest(decision=decision, reason=reason), self.assertRaises(
                ValidationError,
            ):
                quote.with_user(self.user_a)._dally_portal_decide(decision, reason)
            quote.invalidate_recordset()
            self.assertEqual(quote.state, "quoted")
            self.assertFalse(quote.customer_decision_at)

    def test_staff_cannot_use_portal_decision_method(self):
        quote = self._make_quote("orm-staff")
        with self.assertRaises(AccessError):
            quote.with_user(self.staff)._dally_portal_decide("accept")

    def test_generic_portal_write_remains_refused(self):
        quote_a = self._make_quote("orm-rpc-a")
        quote_b = self._make_quote("orm-rpc-b", contact=self.contact_b)
        for quote in (quote_a, quote_b):
            with self.subTest(reference=quote.reference), self.assertRaises(AccessError):
                quote.with_user(self.user_a).write({"state": "won"})

    #: Identifiants propres au scénario de concurrence. Ils vivent hors de la
    #: transaction de test — il leur faut donc des valeurs qu'aucune autre fixture
    #: n'utilise, et un nettoyage explicite.
    CONCURRENT_LOGIN = "quote.decision.concurrent@portal-test.invalid"
    CONCURRENT_UUID = "quote-decision-orm-concurrent"

    @contextmanager
    def _independent_cursor(self):
        """Une connexion PostgreSQL RÉELLEMENT indépendante du test.

        ``self.registry.cursor()`` ne convient pas ici, et c'est la subtilité
        centrale de ce test. En mode test, Odoo renvoie un ``TestCursor``
        sérialisé derrière un verrou partagé avec le curseur du cas de test : deux
        threads qui en demandent chacun un ne s'exécutent pas en parallèle, le
        second attend que le premier relâche. Avec une barrière, cela produit un
        interblocage — le premier thread détient le verrou et attend le second,
        qui attend le verrou. Constaté : le run partait en timeout sans jamais
        atteindre PostgreSQL, aucune session concurrente n'apparaissant dans
        ``pg_stat_activity``.

        ``db_connect(...).cursor()`` ouvre une connexion neuve, avec sa propre
        transaction. C'est la seule façon d'observer réellement le verrou
        ``SELECT … FOR UPDATE`` de la méthode métier.
        """
        connection = db_connect(self.env.cr.dbname)
        cr = connection.cursor()
        try:
            yield cr
        finally:
            cr.close()

    def _committed_concurrency_fixture(self):
        """Crée, dans une transaction COMMITÉE, le strict nécessaire au scénario.

        Deux curseurs indépendants ne voient rien de la transaction de test, qui
        n'est jamais commitée. Le devis doit donc exister pour de bon en base,
        avec toute sa chaîne : société, contact, utilisateur portail, devis et
        commande liée.

        La version précédente appelait ``self.env.cr.commit()`` pour publier la
        fixture de classe. Odoo 19 l'interdit et le dit clairement : committer le
        curseur du test casse le rollback de toute la suite. Le contournement
        n'est pas de committer ailleurs par ruse, c'est de ne pas mêler les deux
        mondes — les données de ce test sont créées, puis supprimées, par des
        curseurs qui lui appartiennent.
        """
        with self._independent_cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            self._drop_concurrency_fixture(env)
            company = env["res.partner"].create({
                "name": "QUOTE DECISION Concurrence", "is_company": True,
            })
            contact = env["res.partner"].create({
                "name": "QUOTE DECISION Contact Concurrence",
                "parent_id": company.id,
                "email": self.CONCURRENT_LOGIN,
            })
            user = env["res.users"].create({
                "name": contact.name,
                "login": self.CONCURRENT_LOGIN,
                "password": PORTAL_PASSWORD,
                "partner_id": contact.id,
                "group_ids": [(6, 0, [env.ref("base.group_portal").id])],
            })
            quote = env["dally.quote.request"].create({
                "partner_id": contact.id,
                "service_type_id": env["dally.service.type"].search([], limit=1).id,
                "request_uuid": self.CONCURRENT_UUID,
                "goods_description": "QUOTE DECISION concurrence",
                "state": "quoted",
            })
            env["sale.order"].create({
                "partner_id": contact.id,
                "dally_quote_request_id": quote.id,
                "state": "sent",
            })
            cr.commit()
            return quote.id, user.id

    @classmethod
    def _drop_concurrency_fixture(cls, env):
        """Supprime les enregistrements commités, dans l'ordre des dépendances."""
        quote = env["dally.quote.request"].search([
            ("request_uuid", "=", cls.CONCURRENT_UUID),
        ])
        if quote:
            orders = env["sale.order"].search([
                ("dally_quote_request_id", "in", quote.ids),
            ])
            if orders:
                # `sale.order` refuse la suppression d'un devis envoyé ou d'une
                # commande confirmée tant qu'il n'est pas annulé — c'est une garde
                # du module `sale`, pas un détail de notre modèle. Le nettoyage doit
                # donc annuler avant de supprimer, sinon il échoue et laisse
                # derrière lui exactement les lignes qu'il devait retirer.
                orders.filtered(lambda order: order.state != "cancel")._action_cancel()
                orders.unlink()

            # Même classe de problème que ci-dessus, sur un autre dépendant :
            # quand `dally_freight_bridge` est installé, accepter un devis
            # provisionne un booking fret qui le référence en `restrict`. Le
            # refus est délibéré — supprimer l'origine commerciale d'une
            # expédition en cours est presque toujours une erreur — mais un
            # nettoyage de fixture doit, lui, retirer ce qu'il a créé.
            #
            # Le test du portail ne dépend pas du pont pour autant : le modèle
            # n'est touché que s'il existe dans le registre.
            if "shipment.freight.booking" in env:
                bookings = env["shipment.freight.booking"].sudo().search([
                    ("dally_quote_request_id", "in", quote.ids),
                ])
                if bookings:
                    shipments = env["freight.shipment"].sudo().search([
                        ("booking_id", "in", bookings.ids),
                    ])
                    projections = env["dally.shipment"].sudo().search([
                        ("tk_shipment_id", "in", shipments.ids),
                    ])
                    projections.unlink()
                    shipments.unlink()
                    bookings.unlink()

            quote.unlink()
        user = env["res.users"].search([("login", "=", cls.CONCURRENT_LOGIN)])
        partner = user.partner_id
        parent = partner.parent_id
        user.unlink()
        partner.unlink()
        parent.unlink()

    def _cleanup_concurrency_fixture(self):
        with self._independent_cursor() as cr:
            self._drop_concurrency_fixture(api.Environment(cr, SUPERUSER_ID, {}))
            cr.commit()

    def test_normalisation_accepts_its_own_output(self):
        """Non-régression du défaut du 16 août : la normalisation n'était pas idempotente.

        Elle renvoyait ``False`` pour « aucun motif » et refusait à l'entrée tout
        ``reason`` non ``None`` sur une acceptation. Comme elle est appelée deux
        fois sur le chemin HTTP — contrôleur puis méthode métier — son propre
        résultat lui revenait et elle levait : **toute acceptation échouait en
        400**, avec un payload pourtant conforme au contrat.

        L'assertion porte sur la propriété, pas sur le symptôme : f(f(x)) == f(x).
        """
        Quote = self.env["dally.quote.request"]
        for decision, reason in (
            ("accept", None),
            ("accept", False),
            ("accept", ""),
            ("accept", "   "),
            ("reject", "Motif synthétique"),
            ("reject", None),
        ):
            with self.subTest(decision=decision, reason=reason):
                once = Quote._dally_portal_normalize_decision(decision, reason)
                twice = Quote._dally_portal_normalize_decision(*once)
                self.assertEqual(once, twice)

    def test_acceptance_still_refuses_a_substantive_reason(self):
        """L'idempotence ne relâche pas la règle métier.

        Une acceptation ne porte pas de motif de refus. Rendre ``False`` et la
        chaîne vide acceptables ne devait pas rendre un motif réel acceptable.
        """
        Quote = self.env["dally.quote.request"]
        with self.assertRaises(ValidationError):
            Quote._dally_portal_normalize_decision("accept", "Je refuse en acceptant")

    def test_accept_through_the_business_method_after_controller_normalisation(self):
        """Reproduit le chemin exact qui échouait : deux normalisations en série.

        Le contrôleur normalise, puis passe son résultat à la méthode métier qui
        normalise de nouveau. Ce test enchaîne les deux sans passer par HTTP, pour
        que la régression soit attrapée même si la route changeait de forme.
        """
        quote = self._make_quote("orm-double-normalisation")
        Quote = self.env["dally.quote.request"]
        decision, reason = Quote._dally_portal_normalize_decision("accept", None)
        self.assertTrue(
            quote.with_user(self.user_a)._dally_portal_decide(decision, reason),
        )
        quote.invalidate_recordset()
        self.assertEqual(quote.state, "won")

    def test_two_concurrent_accepts_serialize_and_become_idempotent(self):
        """Deux transactions réelles, même devis, une seule transition gagnante.

        Ce que le test vérifie tient au verrou ``SELECT … FOR UPDATE`` de
        ``_dally_portal_decide`` : la seconde transaction attend la première, puis
        relit l'état commité et constate que la décision est déjà posée. Elle
        renvoie donc ``False`` — répétition idempotente — au lieu d'écrire une
        seconde transition.

        La barrière garantit que les deux transactions sont bien ouvertes et
        positionnées AVANT que l'une ne prenne le verrou. Sans elle, on
        n'observerait qu'une exécution séquentielle déguisée.
        """
        quote_id, user_id = self._committed_concurrency_fixture()
        # Enregistré immédiatement : la suppression doit avoir lieu même si les
        # assertions échouent, sans quoi la base garderait un devis fantôme qui
        # ferait échouer la prochaine exécution.
        self.addCleanup(self._cleanup_concurrency_fixture)

        barrier = threading.Barrier(2)
        results = []
        errors = []

        # Les curseurs ET les environnements sont construits ICI, dans le thread
        # principal.
        #
        # `api.Environment(...)` prend un verrou de registre qu'Odoo détient
        # pendant l'exécution d'une suite de tests : appelé depuis un thread de
        # travail, il ne rend jamais la main. Constaté par un vidage de piles
        # (SIGQUIT) — le thread était figé exactement sur cette ligne, ni sur le
        # curseur ni sur PostgreSQL.
        #
        # Les threads ne font donc plus que ce qui doit vraiment être concurrent :
        # appeler la méthode métier et committer.
        cursors = [db_connect(self.env.cr.dbname).cursor() for _ in range(2)]
        for cr in cursors:
            self.addCleanup(cr.close)
        quotes = [
            api.Environment(cr, user_id, {})["dally.quote.request"].browse(quote_id)
            for cr in cursors
        ]

        def decide(index):
            try:
                barrier.wait(timeout=30)
                changed = quotes[index]._dally_portal_decide("accept")
                cursors[index].commit()
                results.append(changed)
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(decide, range(2)))

        # ── Ce que la concurrence produit réellement ──
        #
        # Odoo ouvre ses connexions en REPEATABLE READ. Le perdant n'observe donc
        # pas la version commitée par le gagnant : PostgreSQL annule sa
        # transaction avec une `SerializationFailure`. Ce n'est PAS un défaut, et
        # ce n'est pas ce que voit le client : `odoo/service/model.py` rejoue ces
        # erreurs jusqu'à cinq fois (`PG_CONCURRENCY_EXCEPTIONS_TO_RETRY`), et le
        # rejeu observe l'état commité.
        #
        # L'invariant à prouver est donc : une seule transition écrite, et aucune
        # possibilité d'état contradictoire — pas « les deux appels rendent
        # gentiment un booléen ».
        self.assertEqual(
            results.count(True), 1,
            f"exactement une transition attendue ; obtenu {results} / {errors}",
        )
        for error in errors:
            self.assertIsInstance(
                error, PG_CONCURRENCY_EXCEPTIONS_TO_RETRY,
                "le perdant doit échouer par un conflit de sérialisation "
                "rejouable, jamais par une erreur métier ou une écriture partielle",
            )
        self.assertEqual(
            len(results) + len(errors), 2,
            "les deux transactions doivent avoir produit un résultat",
        )

        # ── Le rejeu, tel que la couche HTTP d'Odoo le ferait ──
        #
        # C'est ce qui transforme le conflit en 200 idempotent côté client.
        if errors:
            loser = cursors[results.index(True) ^ 1] if len(results) == 1 else cursors[1]
            loser.rollback()
            retried = api.Environment(loser, user_id, {})[
                "dally.quote.request"
            ].browse(quote_id)
            self.assertFalse(
                retried._dally_portal_decide("accept"),
                "le rejeu doit constater la décision déjà posée, non en écrire une seconde",
            )
            loser.commit()

        # L'état final est lu par un TROISIÈME curseur : celui du test n'a jamais
        # vu ces lignes, et son cache ne peut donc pas masquer le résultat réel.
        with self._independent_cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            final = env["dally.quote.request"].browse(quote_id)
            self.assertEqual(final.state, "won")
            self.assertEqual(final.customer_decision_by_id.id, user_id)
            self.assertTrue(final.customer_decision_at)
            self.assertFalse(final.customer_rejection_reason)


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestPortalQuoteDecisionHttp(QuoteDecisionFixture, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._decision_users()

    def _post(self, reference, payload):
        return self.url_open(
            f"/api/v1/portal/quotes/{reference}/decision",
            json=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Request-ID": "quote-decision-http",
            },
            allow_redirects=False,
        )

    def _call_kw(self, model, method, args, kwargs=None):
        return self.url_open(
            "/web/dataset/call_kw",
            data=json.dumps({
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "model": model,
                    "method": method,
                    "args": args,
                    "kwargs": kwargs or {},
                },
            }),
            headers={"Content-Type": "application/json"},
        )

    def test_valid_accept_returns_confirmed_projection_and_no_store(self):
        quote = self._make_quote("http-accept")
        self.authenticate(self.login_a, PORTAL_PASSWORD)

        response = self._post(quote.reference, {"decision": "accept"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "won")
        self.assertFalse(data["canDecide"])
        self.assertTrue(data["customerDecisionAt"])
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        quote.invalidate_recordset()
        self.assertEqual(quote.customer_decision_by_id, self.user_a)

    def test_valid_reject_returns_confirmed_projection(self):
        quote = self._make_quote("http-reject")
        self.authenticate(self.login_a, PORTAL_PASSWORD)

        response = self._post(quote.reference, {
            "decision": "reject",
            "reason": "Conditions synthétiques non adaptées",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "lost")
        self.assertNotIn("customerRejectionReason", response.json()["data"])
        quote.invalidate_recordset()
        self.assertEqual(
            quote.customer_rejection_reason,
            "Conditions synthétiques non adaptées",
        )

    def test_unknown_and_cross_client_share_identical_404(self):
        quote_b = self._make_quote("http-cross-b", contact=self.contact_b)
        self.authenticate(self.login_a, PORTAL_PASSWORD)

        cross = self._post(quote_b.reference, {"decision": "accept"})
        unknown = self._post("DT-2099-999999", {"decision": "accept"})

        self.assertEqual(cross.status_code, 404)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(cross.json(), unknown.json())

    def test_invalid_state_and_opposite_final_decision_are_conflicts(self):
        draft = self._make_quote(
            "http-draft", request_state="quoted", order_state="draft",
        )
        accepted = self._make_quote("http-conflict")
        accepted.with_user(self.user_a)._dally_portal_decide("accept")
        self.authenticate(self.login_a, PORTAL_PASSWORD)

        for quote, decision in ((draft, "accept"), (accepted, "reject")):
            response = self._post(quote.reference, {"decision": decision})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], "conflict")

    def test_same_decision_twice_is_200_idempotent(self):
        quote = self._make_quote("http-idempotent")
        self.authenticate(self.login_a, PORTAL_PASSWORD)

        self.assertEqual(
            self._post(quote.reference, {"decision": "accept"}).status_code, 200,
        )
        self.assertEqual(
            self._post(quote.reference, {"decision": "accept"}).status_code, 200,
        )

    def test_invalid_and_mass_assignment_payloads_are_400_and_atomic(self):
        payloads = (
            {},
            {"decision": "maybe"},
            {"decision": "accept", "reason": "interdit"},
            {"decision": "reject", "reason": "x" * 501},
            {"decision": "accept", "state": "won"},
            {
                "decision": "accept",
                "partner_id": self.contact_b.id,
                "margin": 0,
                "user_id": self.staff.id,
            },
        )
        self.authenticate(self.login_a, PORTAL_PASSWORD)
        for index, payload in enumerate(payloads):
            quote = self._make_quote(f"http-invalid-{index}")
            with self.subTest(payload=payload):
                response = self._post(quote.reference, payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json()["error"]["code"], "invalid_request",
                )
                quote.invalidate_recordset()
                self.assertEqual(quote.state, "quoted")
                self.assertFalse(quote.customer_decision_at)

    def test_staff_and_missing_session_are_refused(self):
        quote = self._make_quote("http-auth")

        self.authenticate(self.login_staff, PORTAL_PASSWORD)
        self.assertEqual(
            self._post(quote.reference, {"decision": "accept"}).status_code, 403,
        )

        self.authenticate(None, None)
        self.assertNotEqual(
            self._post(quote.reference, {"decision": "accept"}).status_code, 200,
        )

    def test_concurrency_exception_is_not_swallowed_by_the_controller(self):
        """Le contrôleur doit LAISSER REMONTER ce qu'Odoo sait rejouer.

        Sous REPEATABLE READ, la décision perdante lève une
        `SerializationFailure`. `odoo/service/model.py:retrying` la rattrape,
        annule et rejoue — mais seulement si elle lui parvient. Un
        `except Exception` dans le contrôleur la convertissait en 500 : mesuré en
        HTTP réel, deux acceptations simultanées donnaient 200 puis 503.

        Ce test remplace la méthode métier par une qui lève l'exception de
        concurrence, et vérifie qu'elle ressort du contrôleur au lieu d'être
        traduite. C'est la propriété exacte que le correctif garantit.
        """
        from psycopg2 import errors

        class SimulatedSerializationFailure(errors.SerializationFailure):
            """A retryable PostgreSQL error with the real SQLSTATE attached.

            Instantiating ``psycopg2.errors.SerializationFailure`` directly
            leaves ``pgcode`` empty. Odoo 19's HTTP retry layer correctly
            relies on SQLSTATE ``40001`` to decide that it can replay the
            request; the bare synthetic exception therefore exercised a
            KeyError in the framework instead of the intended code path.
            """

            @property
            def pgcode(self):
                return "40001"

        quote = self._make_quote("http-concurrency-propagation")
        self.authenticate(self.login_a, PORTAL_PASSWORD)

        original_decide = type(
            self.env["dally.quote.request"]
        )._dally_portal_decide
        attempts = {"count": 0}

        def raising(self, *args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise SimulatedSerializationFailure("could not serialize access")
            return original_decide(self, *args, **kwargs)

        with patch.object(
            type(self.env["dally.quote.request"]),
            "_dally_portal_decide", raising,
        ):
            response = self._post(quote.reference, {"decision": "accept"})

        # Le premier appel est rejeté par PostgreSQL, Odoo rejoue la requête,
        # puis le second appel observe le flux métier normal. Si le contrôleur
        # avalait l'exception, il retournerait une réponse ``unavailable`` et
        # cette seconde exécution n'aurait jamais lieu.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(attempts["count"], 2)

    def test_generic_exception_is_still_converted(self):
        """L'autre moitié : une panne inconnue reste traduite, pas propagée.

        Élargir le `raise` à toutes les exceptions transformerait chaque bogue en
        erreur brute exposée au client. Le gestionnaire générique doit continuer
        de rendre une réponse contrôlée.
        """
        quote = self._make_quote("http-generic-error")
        self.authenticate(self.login_a, PORTAL_PASSWORD)

        def raising(self, *args, **kwargs):
            raise RuntimeError("panne interne synthétique")

        with patch.object(
            type(self.env["dally.quote.request"]),
            "_dally_portal_decide", raising,
        ):
            response = self._post(quote.reference, {"decision": "accept"})

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "unavailable")
        # Le message interne ne doit pas ressortir.
        self.assertNotIn("synthétique", response.text or "")

    def test_generic_rpc_and_private_method_are_refused(self):
        quote = self._make_quote("http-rpc")
        self.authenticate(self.login_a, PORTAL_PASSWORD)

        generic = self._call_kw(
            "dally.quote.request", "write",
            [[quote.id], {"state": "won"}],
        ).json()
        private = self._call_kw(
            "dally.quote.request", "_dally_portal_decide",
            [[quote.id], "accept"],
        ).json()

        self.assertIn("error", generic)
        self.assertIn("error", private)
        quote.invalidate_recordset()
        self.assertEqual(quote.state, "quoted")
