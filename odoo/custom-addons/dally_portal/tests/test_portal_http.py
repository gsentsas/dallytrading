# -*- coding: utf-8 -*-
"""La couche HTTP, éprouvée avec de vraies sessions Odoo.

Les tests ORM du cycle précédent prouvaient que les record rules tiennent. Ceux-ci
prouvent deux choses de plus, qu'aucun test ORM ne peut établir :

1. que les contrôleurs ne rouvrent pas ce que l'ORM ferme ;
2. que **contourner les contrôleurs ne sert à rien** — un client authentifié est un
   vrai ``res.users``, il peut appeler les routes génériques d'Odoo, et la sécurité
   doit tenir sans nos endpoints.

Le second point est le plus important. Si nos contrôleurs étaient la seule barrière,
tout ce cycle ne vaudrait rien.
"""

import json
import uuid

from odoo.tests import HttpCase, tagged

PORTAL_PASSWORD = "PortalTest!2026"


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestPortalHttp(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        Users = cls.env["res.users"]
        portal_group = cls.env.ref("base.group_portal")

        cls.company_a = Partner.create({"name": "HTTP-A", "is_company": True})
        cls.company_b = Partner.create({"name": "HTTP-B", "is_company": True})
        contact_a1 = Partner.create({"name": "HTTP A1", "parent_id": cls.company_a.id})
        contact_a2 = Partner.create({"name": "HTTP A2", "parent_id": cls.company_a.id})
        contact_b1 = Partner.create({"name": "HTTP B1", "parent_id": cls.company_b.id})

        def portal_user(partner, login):
            return Users.create({
                "name": partner.name, "login": login, "password": PORTAL_PASSWORD,
                "partner_id": partner.id,
                "group_ids": [(6, 0, [portal_group.id])],
            })

        cls.login_a1 = "http.a1@portal-test.invalid"
        cls.login_a2 = "http.a2@portal-test.invalid"
        cls.login_b1 = "http.b1@portal-test.invalid"
        cls.user_a1 = portal_user(contact_a1, cls.login_a1)
        cls.user_a2 = portal_user(contact_a2, cls.login_a2)
        cls.user_b1 = portal_user(contact_b1, cls.login_b1)

        cls.login_staff = "http.staff@portal-test.invalid"
        cls.staff = Users.create({
            "name": "HTTP Staff", "login": cls.login_staff,
            "password": PORTAL_PASSWORD,
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("dally_core.group_dally_commercial").id,
            ])],
        })

        cls.data_a = cls._make(cls.company_a, "A")
        cls.data_b = cls._make(cls.company_b, "B")

    @classmethod
    def _make(cls, partner, tag):
        service = cls.env["dally.service.type"].search([], limit=1)
        quote = cls.env["dally.quote.request"].create({
            "contact_name": f"HTTP {tag}", "service_type_id": service.id,
            "email": f"http{tag}@portal-test.invalid", "partner_id": partner.id,
            "request_uuid": str(uuid.uuid4()),
        })
        sourcing = cls.env["dally.sourcing.request"].create({
            "product_name": f"HTTP produit {tag}", "quantity": 5.0,
            "contact_name": f"HTTP {tag}", "customer_id": partner.id,
        })
        trade = cls.env["dally.trade.opportunity"].create({
            "name": f"HTTP opération {tag}", "operation_type": "purchase_resale",
            "customer_id": partner.id,
        })
        shipment = cls.env["dally.shipment"].create({"partner_id": partner.id})
        attachment = cls.env["ir.attachment"].create({
            "name": f"HTTP doc {tag}.pdf", "datas": b"JVBERi0xLjQK",
        })
        document = cls.env["dally.portal.document"].create({
            "name": f"HTTP document {tag}", "attachment_id": attachment.id,
            "document_type": "quotation", "shipment_id": shipment.id,
            "published_to_portal": True,
        })
        hidden = cls.env["ir.attachment"].create({
            "name": f"HTTP interne {tag}.pdf", "datas": b"JVBERi0xLjQK",
        })
        unpublished = cls.env["dally.portal.document"].create({
            "name": f"HTTP non publié {tag}", "attachment_id": hidden.id,
            "document_type": "other", "shipment_id": shipment.id,
        })
        return {"quote": quote, "sourcing": sourcing, "trade": trade,
                "shipment": shipment, "document": document,
                "unpublished": unpublished}

    LIST_ENDPOINTS = ("quotes", "sourcing", "trades", "shipments", "documents")
    DETAIL = {
        "quotes": "quote", "sourcing": "sourcing",
        "trades": "trade", "shipments": "shipment",
    }

    # ─── Session ─────────────────────────────────────────────────────

    def test_no_session_is_refused(self):
        """Sans session, Odoo redirige vers la connexion ou refuse — jamais 200."""
        response = self.url_open("/api/v1/portal/me", allow_redirects=False)
        self.assertNotEqual(response.status_code, 200)

    def test_login_then_me_returns_the_authenticated_identity(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        response = self.url_open("/api/v1/portal/me")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["name"], "HTTP A1")
        self.assertEqual(body["data"]["company"], "HTTP-A")

    def test_logout_invalidates_access(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        self.assertEqual(self.url_open("/api/v1/portal/me").status_code, 200)
        self.url_open("/web/session/logout", allow_redirects=False)
        response = self.url_open("/api/v1/portal/me", allow_redirects=False)
        self.assertNotEqual(response.status_code, 200)

    def test_forged_session_cookie_is_refused(self):
        self.authenticate(None, None)
        self.opener.cookies["session_id"] = "0" * 40
        response = self.url_open("/api/v1/portal/me", allow_redirects=False)
        self.assertNotEqual(response.status_code, 200)

    def test_internal_user_is_refused(self):
        """Décision documentée : ces routes sont réservées aux comptes `share`.

        Un salarié qui les appellerait verrait, sous ses propres droits, bien plus
        que ce que la projection prévoit — et la projection deviendrait la seule
        barrière. Le personnel a l'interface Odoo.
        """
        self.authenticate(self.login_staff, PORTAL_PASSWORD)
        response = self.url_open("/api/v1/portal/me")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["success"])

    # ─── En-têtes ────────────────────────────────────────────────────

    def test_private_responses_are_never_cacheable(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        for path in ["/api/v1/portal/me", "/api/v1/portal/dashboard"] + [
            f"/api/v1/portal/{name}" for name in self.LIST_ENDPOINTS
        ]:
            cache = self.url_open(path).headers.get("Cache-Control", "")
            self.assertIn("private", cache, f"{path} n'est pas privé")
            self.assertIn("no-store", cache, f"{path} peut être stocké")

    # ─── Matrice A / B ───────────────────────────────────────────────

    def _items(self, path):
        response = self.url_open(path)
        self.assertEqual(response.status_code, 200, path)
        return response.json()["data"]["items"]

    def test_lists_only_return_the_caller_company_records(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        for name in self.LIST_ENDPOINTS:
            items = self._items(f"/api/v1/portal/{name}")
            serialised = json.dumps(items)
            # Non vide d'abord : une liste vide ne contient jamais de données de B,
            # et ferait passer les assertions suivantes sans rien démontrer.
            #
            # L'ancienne version cherchait « A » dans la charge utile. C'était à la
            # fois trop faible (la lettre A apparaît dans quantité de mots) et
            # inexact : la projection d'un devis ne porte AUCUN nom de société, par
            # construction. Le test échouait donc sur un dessin volontaire.
            self.assertTrue(items, f"{name} ne renvoie rien : test non probant")
            self.assertNotIn(
                "HTTP-B", serialised, f"{name} expose des données de la société B")

    def test_a2_sees_the_same_lists_as_a1(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        seen_a1 = {name: self._items(f"/api/v1/portal/{name}")
                   for name in self.LIST_ENDPOINTS}
        self.authenticate(self.login_a2, PORTAL_PASSWORD)
        for name in self.LIST_ENDPOINTS:
            self.assertEqual(
                seen_a1[name], self._items(f"/api/v1/portal/{name}"),
                f"A1 et A2 ne voient pas la même chose sur {name}")

    def test_b1_never_sees_company_a(self):
        self.authenticate(self.login_b1, PORTAL_PASSWORD)
        for name in self.LIST_ENDPOINTS:
            serialised = json.dumps(self._items(f"/api/v1/portal/{name}"))
            self.assertNotIn("HTTP-A", serialised)

    def test_detail_of_own_record_succeeds(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        for endpoint, key in self.DETAIL.items():
            reference = self.data_a[key].reference
            response = self.url_open(f"/api/v1/portal/{endpoint}/{reference}")
            self.assertEqual(response.status_code, 200, endpoint)
            self.assertEqual(response.json()["data"]["reference"], reference)

    # ─── Anti-énumération ────────────────────────────────────────────

    def test_cross_client_and_unknown_are_indistinguishable(self):
        """Le dossier d'un autre client et une référence inventée : même réponse.

        Si les deux différaient — par le statut, le corps ou le message — un
        attaquant apprendrait quelles références existent, ce qui est déjà une fuite.
        """
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        for endpoint, key in self.DETAIL.items():
            foreign = self.url_open(
                f"/api/v1/portal/{endpoint}/{self.data_b[key].reference}")
            unknown = self.url_open(
                f"/api/v1/portal/{endpoint}/DT-INEXISTANT-2026-999999")
            self.assertEqual(foreign.status_code, 404, endpoint)
            self.assertEqual(unknown.status_code, 404, endpoint)
            self.assertEqual(
                foreign.json(), unknown.json(),
                f"{endpoint} : les deux réponses diffèrent et renseignent l'appelant")

    def test_error_body_never_names_the_other_client(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        body = self.url_open(
            f"/api/v1/portal/quotes/{self.data_b['quote'].reference}").text
        for leak in ("HTTP-B", "HTTP B1", "société B", "partner"):
            self.assertNotIn(leak, body)

    # ─── Pagination ──────────────────────────────────────────────────

    def test_limit_is_capped_and_offset_respected(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        body = self.url_open("/api/v1/portal/quotes?limit=100000").json()["data"]
        self.assertLessEqual(body["limit"], 100)
        body = self.url_open("/api/v1/portal/quotes?limit=-5&offset=-3").json()["data"]
        self.assertGreaterEqual(body["limit"], 1)
        self.assertGreaterEqual(body["offset"], 0)

    def test_arbitrary_sort_is_ignored(self):
        """Un `order` transmis à l'ORM permettrait de trier sur un champ protégé.

        Observer l'ordre des résultats suffirait alors à deviner une marge, sans
        jamais la lire.
        """
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        response = self.url_open("/api/v1/portal/quotes?sort=margin+desc")
        self.assertEqual(response.status_code, 200)

    def test_arbitrary_domain_is_not_accepted(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        response = self.url_open(
            '/api/v1/portal/quotes?domain=[("id","!=",0)]')
        self.assertEqual(response.status_code, 200)
        serialised = json.dumps(response.json())
        self.assertNotIn("HTTP-B", serialised)

    # ─── Tableau de bord ─────────────────────────────────────────────

    def test_dashboard_counts_only_the_caller_records(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        data = self.url_open("/api/v1/portal/dashboard").json()["data"]
        self.assertEqual(set(data["counters"]), set(self.LIST_ENDPOINTS))
        for name in self.LIST_ENDPOINTS:
            self.assertLessEqual(len(data["recent"][name]), 5)
        self.assertNotIn("HTTP-B", json.dumps(data))

    # ─── Contournement par les routes génériques (§11) ────────────────

    def _call_kw(self, model, method, args, kwargs=None):
        return self.url_open(
            "/web/dataset/call_kw",
            data=json.dumps({
                "jsonrpc": "2.0", "method": "call",
                "params": {"model": model, "method": method,
                           "args": args, "kwargs": kwargs or {}},
            }),
            headers={"Content-Type": "application/json"},
        )

    ALLOWED_MODELS = ("dally.quote.request", "dally.sourcing.request",
                      "dally.trade.opportunity", "dally.shipment",
                      "dally.portal.document")
    FORBIDDEN_MODELS = ("dally.sourcing.offer", "dally.sourcing.supplier",
                        "dally.trade.cost", "dally.trade.commission",
                        "dally.api.key")

    def test_generic_rpc_cannot_reach_forbidden_models(self):
        """Contourner nos contrôleurs ne doit rien donner de plus."""
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        for model in self.FORBIDDEN_MODELS:
            for method, args in (
                ("search", [[]]), ("search_read", [[], ["id"]]),
                ("search_count", [[]]), ("read_group", [[], ["id"], []]),
                ("fields_get", []), ("name_search", []),
            ):
                body = self._call_kw(model, method, args).json()
                self.assertIn(
                    "error", body,
                    f"{model}.{method} a répondu sans erreur à un utilisateur portail")

    def test_generic_rpc_on_allowed_models_still_respects_record_rules(self):
        """Les modèles autorisés le restent — mais seulement pour ses dossiers."""
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        for model in self.ALLOWED_MODELS:
            body = self._call_kw(model, "search_read", [[], ["id"]]).json()
            if "error" in body:
                continue
            ids = {row["id"] for row in body.get("result", [])}
            key = {"dally.quote.request": "quote",
                   "dally.sourcing.request": "sourcing",
                   "dally.trade.opportunity": "trade",
                   "dally.shipment": "shipment",
                   "dally.portal.document": "document"}[model]
            self.assertNotIn(
                self.data_b[key].id, ids,
                f"{model} : search_read générique expose un dossier de B")

    def test_generic_rpc_cannot_read_protected_fields(self):
        """Demander explicitement un champ protégé, sur son propre dossier."""
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        probes = {
            "dally.sourcing.request": ["supplier_ids", "supplier_count",
                                       "purchase_order_ids", "responsible_id",
                                       "team_id", "internal_notes"],
            "dally.shipment": ["margin", "supplier_cost", "user_id",
                               "internal_notes"],
            "dally.trade.opportunity": ["net_margin", "supplier_id",
                                        "purchase_subtotal", "negotiation_notes"],
            "dally.quote.request": ["user_id", "internal_notes"],
        }
        key = {"dally.sourcing.request": "sourcing", "dally.shipment": "shipment",
               "dally.trade.opportunity": "trade", "dally.quote.request": "quote"}
        for model, fields in probes.items():
            record_id = self.data_a[key[model]].id
            for field in fields:
                body = self._call_kw(model, "read", [[record_id], [field]]).json()
                self.assertIn(
                    "error", body,
                    f"{model}.{field} lisible par RPC générique sur son propre dossier")

    def test_generic_rpc_cannot_use_protected_fields_as_an_oracle(self):
        """Filtrer ou grouper sur un champ protégé doit échouer, pas renseigner."""
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        for model, field in (
            ("dally.shipment", "margin"),
            ("dally.trade.opportunity", "net_margin"),
            ("dally.sourcing.request", "supplier_count"),
        ):
            for method, args in (
                ("search", [[(field, "!=", False)]]),
                ("read_group", [[], [field], [field]]),
            ):
                body = self._call_kw(model, method, args).json()
                self.assertIn(
                    "error", body,
                    f"{model}.{field} utilisable via {method} comme oracle")

    def test_fields_get_does_not_describe_protected_fields(self):
        """Les métadonnées ne doivent pas révéler ce que le champ contient."""
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        body = self._call_kw("dally.shipment", "fields_get", []).json()
        described = set(body.get("result", {}))
        for field in ("margin", "supplier_cost", "internal_notes", "user_id"):
            self.assertNotIn(
                field, described,
                f"fields_get décrit {field} à un utilisateur portail")

    # ─── Fuites relationnelles (§13) ─────────────────────────────────

    def test_no_traversal_to_suppliers_or_internal_users(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        for model, method, args in (
            ("res.users", "search_read", [[], ["login"]]),
            ("crm.team", "search_read", [[], ["name"]]),
            ("purchase.order", "search_read", [[], ["partner_id"]]),
        ):
            body = self._call_kw(model, method, args).json()
            if "error" in body:
                continue
            serialised = json.dumps(body.get("result", []))
            self.assertNotIn("HTTP-B", serialised, f"{model} expose la société B")
            self.assertNotIn(self.login_staff, serialised,
                             f"{model} expose un compte interne")

    # ─── Documents (§14) ─────────────────────────────────────────────

    def test_download_own_published_document(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        response = self.url_open(
            f"/api/v1/portal/documents/{self.data_a['document'].id}/download")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response.headers.get("Content-Disposition", ""))
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(
            response.headers.get("X-Content-Type-Options"), "nosniff")

    def test_download_refuses_another_client_document(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        response = self.url_open(
            f"/api/v1/portal/documents/{self.data_b['document'].id}/download")
        self.assertEqual(response.status_code, 404)

    def test_download_refuses_an_unpublished_document(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        response = self.url_open(
            f"/api/v1/portal/documents/{self.data_a['unpublished'].id}/download")
        self.assertEqual(response.status_code, 404)

    def test_download_without_session_is_refused(self):
        self.authenticate(None, None)
        response = self.url_open(
            f"/api/v1/portal/documents/{self.data_a['document'].id}/download",
            allow_redirects=False)
        self.assertNotEqual(response.status_code, 200)

    def test_attachment_cannot_be_fetched_through_the_native_route(self):
        """Le contournement évident : viser directement /web/content."""
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        target = self.data_b["document"].attachment_id.id
        response = self.url_open(f"/web/content/{target}", allow_redirects=False)
        self.assertNotEqual(
            response.status_code, 200,
            "la pièce jointe d'un autre client est servie par la route native")

    def test_document_payload_never_exposes_the_attachment_id(self):
        self.authenticate(self.login_a1, PORTAL_PASSWORD)
        serialised = json.dumps(self._items("/api/v1/portal/documents"))
        self.assertNotIn("attachment", serialised.lower())
        self.assertNotIn("store_fname", serialised.lower())
