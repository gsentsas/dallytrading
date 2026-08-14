# -*- coding: utf-8 -*-
"""Le cloisonnement client, prouvé plutôt qu'affirmé.

Chaque test ci-dessous répond à la même question sous un angle différent : un
client peut-il atteindre les données d'un autre, ou les données internes de
DallyTrading, en s'y prenant autrement que par l'interface prévue ?

Les tentatives passent délibérément par l'ORM et non par une page : `search`,
`search_read`, `read` par identifiant deviné, domaine forgé. C'est la surface qu'un
contrôleur mal écrit expose, et celle qu'une record rule doit tenir seule.

Trois couches sont vérifiées séparément, parce qu'elles échouent différemment :

- l'**ACL** décide si le modèle est atteignable du tout ;
- la **record rule** décide quels enregistrements sont visibles ;
- les **``groups=``** décident quels champs sont chargés, y compris sur un
  enregistrement légitimement visible.

La troisième est la moins intuitive : posséder un dossier ne donne pas droit à tous
ses champs.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestPortalIsolation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        Users = cls.env["res.users"]
        portal_group = cls.env.ref("base.group_portal")

        # ── Société A, deux contacts ──
        cls.company_a = Partner.create({
            "name": "PORTAL-TEST Société A", "is_company": True,
            "email": "contact@portal-test-a.invalid",
        })
        cls.contact_a1 = Partner.create({
            "name": "PORTAL-TEST A1", "parent_id": cls.company_a.id,
            "email": "a1@portal-test-a.invalid",
        })
        cls.contact_a2 = Partner.create({
            "name": "PORTAL-TEST A2", "parent_id": cls.company_a.id,
            "email": "a2@portal-test-a.invalid",
        })

        # ── Société B, un contact ──
        cls.company_b = Partner.create({
            "name": "PORTAL-TEST Société B", "is_company": True,
            "email": "contact@portal-test-b.invalid",
        })
        cls.contact_b1 = Partner.create({
            "name": "PORTAL-TEST B1", "parent_id": cls.company_b.id,
            "email": "b1@portal-test-b.invalid",
        })

        def portal_user(partner, login):
            return Users.create({
                "name": partner.name, "login": login,
                "partner_id": partner.id,
                "group_ids": [(6, 0, [portal_group.id])],
            })

        cls.user_a1 = portal_user(cls.contact_a1, "portal.a1@portal-test.invalid")
        cls.user_a2 = portal_user(cls.contact_a2, "portal.a2@portal-test.invalid")
        cls.user_b1 = portal_user(cls.contact_b1, "portal.b1@portal-test.invalid")

        cls.staff = Users.create({
            "name": "PORTAL-TEST Staff", "login": "staff@portal-test.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("dally_core.group_dally_commercial").id,
            ])],
        })

        # ── Dossiers, un jeu par société ──
        cls.records_a = cls._business_records(cls.company_a, "A")
        cls.records_b = cls._business_records(cls.company_b, "B")

    @classmethod
    def _business_records(cls, partner, tag):
        """Un dossier de chaque type pour une société."""
        service = cls.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1,
        ) or cls.env["dally.service.type"].search([], limit=1)
        import uuid as _uuid
        quote = cls.env["dally.quote.request"].create({
            "contact_name": f"PORTAL-TEST {tag}", "service_type_id": service.id,
            "email": f"{tag.lower()}@portal-test.invalid", "partner_id": partner.id,
            "request_uuid": str(_uuid.uuid4()),
        })
        sourcing = cls.env["dally.sourcing.request"].create({
            "product_name": f"PORTAL-TEST produit {tag}", "quantity": 10.0,
            "contact_name": f"PORTAL-TEST {tag}", "customer_id": partner.id,
        })
        proposal = cls.env["dally.sourcing.proposal"].create({
            "request_id": sourcing.id, "customer_id": partner.id,
            "product_name": f"PORTAL-TEST produit {tag}", "quantity": 10.0,
            "selling_unit_price": 100.0, "state": "sent",
        })
        draft_proposal = cls.env["dally.sourcing.proposal"].create({
            "request_id": sourcing.id, "customer_id": partner.id,
            "product_name": f"PORTAL-TEST brouillon {tag}", "quantity": 1.0,
            "selling_unit_price": 999.0, "state": "draft",
        })
        trade = cls.env["dally.trade.opportunity"].create({
            "name": f"PORTAL-TEST opération {tag}", "operation_type": "purchase_resale",
            "customer_id": partner.id,
        })
        shipment = cls.env["dally.shipment"].create({"partner_id": partner.id})
        attachment = cls.env["ir.attachment"].create({
            "name": f"PORTAL-TEST doc {tag}.pdf", "datas": b"JVBERi0xLjQK",
        })
        document = cls.env["dally.portal.document"].create({
            "name": f"PORTAL-TEST document {tag}", "attachment_id": attachment.id,
            "document_type": "quotation", "shipment_id": shipment.id,
            "published_to_portal": True,
        })
        hidden_attachment = cls.env["ir.attachment"].create({
            "name": f"PORTAL-TEST interne {tag}.pdf", "datas": b"JVBERi0xLjQK",
        })
        unpublished = cls.env["dally.portal.document"].create({
            "name": f"PORTAL-TEST non publié {tag}", "attachment_id": hidden_attachment.id,
            "document_type": "other", "shipment_id": shipment.id,
            "published_to_portal": False,
        })
        return {
            "quote": quote, "sourcing": sourcing, "proposal": proposal,
            "draft_proposal": draft_proposal, "trade": trade,
            "shipment": shipment, "document": document, "unpublished": unpublished,
        }

    #: Modèle → clé du dossier, pour parcourir la matrice sans la réécrire.
    MODELS = (
        ("dally.quote.request", "quote"),
        ("dally.sourcing.request", "sourcing"),
        ("dally.sourcing.proposal", "proposal"),
        ("dally.trade.opportunity", "trade"),
        ("dally.shipment", "shipment"),
        ("dally.portal.document", "document"),
    )

    # ─── 1. Le client voit ses dossiers ───────────────────────────────

    def test_a1_sees_company_a_records(self):
        for model, key in self.MODELS:
            found = self.env[model].with_user(self.user_a1).search([])
            self.assertIn(
                self.records_a[key], found,
                f"A1 ne voit pas son propre {model}",
            )

    def test_a2_sees_the_same_records_as_a1(self):
        """La portée est la SOCIÉTÉ, pas le contact.

        C'est tout l'intérêt de `commercial_partner_id` : A2 n'a déposé aucun de ces
        dossiers, et doit pourtant les voir — ce sont ceux de son employeur.
        """
        for model, key in self.MODELS:
            seen_a1 = self.env[model].with_user(self.user_a1).search([]).ids
            seen_a2 = self.env[model].with_user(self.user_a2).search([]).ids
            self.assertEqual(
                set(seen_a1), set(seen_a2),
                f"A1 et A2 ne voient pas le même périmètre sur {model}",
            )

    # ─── 2. Le client ne voit pas ceux des autres ─────────────────────

    def test_search_never_returns_another_client_records(self):
        for model, key in self.MODELS:
            seen = self.env[model].with_user(self.user_a1).search([])
            self.assertNotIn(
                self.records_b[key], seen,
                f"A1 voit le {model} de la société B",
            )
            seen_b = self.env[model].with_user(self.user_b1).search([])
            self.assertNotIn(
                self.records_a[key], seen_b,
                f"B1 voit le {model} de la société A",
            )

    def test_read_by_forged_id_is_refused(self):
        """L'attaque la plus simple : deviner l'identifiant et le lire directement."""
        for model, key in self.MODELS:
            target = self.records_b[key]
            with self.assertRaises(
                AccessError,
                msg=f"A1 a pu lire {model} id={target.id} appartenant à B",
            ):
                self.env[model].with_user(self.user_a1).browse(target.id).read(["id"])

    def test_forged_domain_does_not_widen_the_scope(self):
        """Un domaine forgé ne peut pas élargir : la record rule est ANDée.

        Un développeur de contrôleur pourrait croire que filtrer soi-même suffit.
        L'inverse est vrai : ce que le contrôleur ajoute restreint, il n'ouvre rien.
        """
        for model, key in self.MODELS:
            target = self.records_b[key]
            found = self.env[model].with_user(self.user_a1).search([
                ("id", "=", target.id),
            ])
            self.assertFalse(
                found, f"un domaine forgé a exposé {model} de la société B",
            )

    def test_search_read_leaks_nothing(self):
        """`search_read` court-circuite `browse` : il doit être testé pour lui-même."""
        for model, key in self.MODELS:
            rows = self.env[model].with_user(self.user_a1).search_read(
                [], ["id"],
            )
            ids = {row["id"] for row in rows}
            self.assertNotIn(
                self.records_b[key].id, ids,
                f"search_read a exposé {model} de la société B",
            )

    def test_search_count_does_not_leak_existence(self):
        """Même le comptage ne doit pas révéler l'existence d'un dossier tiers."""
        for model, key in self.MODELS:
            count = self.env[model].with_user(self.user_a1).search_count([
                ("id", "=", self.records_b[key].id),
            ])
            self.assertEqual(count, 0, f"{model} : le comptage fuit")

    # ─── 3. Les modèles internes restent hors de portée ───────────────

    def test_internal_models_have_no_portal_access_at_all(self):
        """Aucune ACL : le modèle n'est pas atteignable, règle ou pas.

        `dally.sourcing.supplier`, `dally.trade.cost` et `dally.trade.commission`
        portent un `partner_id` qui désigne un FOURNISSEUR. Une règle générique
        « partner_id = mon partenaire » les aurait ouverts à un client également
        fournisseur. Ils n'ont donc aucune ACL portail du tout.
        """
        for model in (
            "dally.sourcing.offer", "dally.sourcing.supplier",
            "dally.trade.cost", "dally.trade.commission", "dally.trade.line",
            "dally.api.key", "dally.api.request",
        ):
            with self.assertRaises(
                AccessError, msg=f"le portail atteint {model}",
            ):
                self.env[model].with_user(self.user_a1).search([])

    # ─── 4. Les champs internes, sur un dossier pourtant légitime ─────

    #: Modèle → champs qu'un client ne doit jamais charger, même sur SON dossier.
    FORBIDDEN_FIELDS = {
        "dally.quote.request": ["internal_notes", "user_id"],
        "dally.sourcing.request": [
            "internal_notes", "supplier_ids", "supplier_count",
            "purchase_order_ids", "responsible_id", "team_id",
        ],
        "dally.sourcing.proposal": [
            "internal_notes", "cost_basis", "margin", "margin_rate",
            "price_validated", "price_validated_by_id", "source_offer_id",
        ],
        "dally.trade.opportunity": [
            "internal_notes", "negotiation_notes", "supplier_id",
            "purchase_subtotal", "gross_margin", "net_margin", "margin_rate",
            "cost_total_analysis", "commission_total_analysis",
            "approval_status", "cost_ids", "commission_ids",
        ],
        "dally.shipment": ["internal_notes", "supplier_cost", "margin", "user_id"],
    }

    def test_forbidden_fields_are_not_readable_on_own_records(self):
        """Posséder le dossier ne donne pas droit à tous ses champs.

        C'est la couche la moins intuitive : la record rule a laissé passer
        l'enregistrement, et pourtant l'ORM refuse le champ. Sans `groups=`, un
        appel `read(['margin'])` sur son propre dossier renverrait la marge.
        """
        for model, fields in self.FORBIDDEN_FIELDS.items():
            key = dict(self.MODELS)[model]
            record = self.records_a[key].with_user(self.user_a1)
            for field in fields:
                with self.assertRaises(
                    AccessError,
                    msg=f"{model}.{field} est lisible par un utilisateur portail",
                ):
                    record.read([field])

    def test_forbidden_fields_are_absent_from_a_plain_read(self):
        """Ils ne doivent pas non plus apparaître dans une lecture sans argument."""
        for model, fields in self.FORBIDDEN_FIELDS.items():
            key = dict(self.MODELS)[model]
            row = self.records_a[key].with_user(self.user_a1).read()[0]
            for field in fields:
                self.assertNotIn(
                    field, row,
                    f"{model}.{field} apparaît dans une lecture complète",
                )

    def test_forbidden_fields_cannot_be_reached_through_a_domain(self):
        """Filtrer sur un champ interdit ne doit pas être un oracle.

        Sans cette barrière, `search([('margin', '>', 0)])` permettrait de deviner
        une marge par dichotomie sans jamais la lire.
        """
        for model, fields in self.FORBIDDEN_FIELDS.items():
            for field in fields:
                model_obj = self.env[model].with_user(self.user_a1)
                if not isinstance(model_obj._fields.get(field), object):
                    continue
                with self.assertRaises(
                    (AccessError, ValueError),
                    msg=f"{model} : {field} utilisable dans un domaine",
                ):
                    model_obj.search([(field, "!=", False)])

    # ─── 5. Le chatter n'est pas ouvert par ricochet ──────────────────

    def test_chatter_is_not_exposed_by_owning_the_record(self):
        """Avoir accès au dossier n'ouvre pas les échanges internes qui s'y rattachent.

        `mail.thread` ajoute `message_ids` et `activity_ids` à tous nos modèles. Ces
        messages contiennent la discussion interne — négociation, arbitrages, notes
        d'équipe. Le portail n'a aucune ACL sur `mail.message` ni `mail.activity`,
        donc les traverser échoue.
        """
        record = self.records_a["sourcing"].with_user(self.user_a1)
        for field in ("message_ids", "activity_ids", "message_follower_ids"):
            if field not in record._fields:
                continue
            with self.assertRaises(
                AccessError, msg=f"le portail traverse {field}",
            ):
                record.read([field])

    def test_portal_cannot_search_internal_messages(self):
        for model in ("mail.message", "mail.activity"):
            with self.assertRaises(
                AccessError, msg=f"le portail atteint {model}",
            ):
                self.env[model].with_user(self.user_a1).search(
                    [("res_id", "=", self.records_a["sourcing"].id)],
                )

    # ─── 6. Documents ─────────────────────────────────────────────────

    def test_unpublished_document_is_invisible_to_its_own_client(self):
        """Appartenir ne suffit pas : il faut avoir été publié.

        Sans cette condition, tout fichier déposé sur un dossier client deviendrait
        téléchargeable au moment du dépôt.
        """
        found = self.env["dally.portal.document"].with_user(self.user_a1).search([])
        self.assertIn(self.records_a["document"], found)
        self.assertNotIn(
            self.records_a["unpublished"], found,
            "un document non publié est visible du client",
        )

    def test_document_of_another_client_is_unreachable(self):
        with self.assertRaises(AccessError):
            self.records_b["document"].with_user(self.user_a1).read(["name"])

    def test_download_helper_refuses_another_client_document(self):
        """Le contrôle est refait au téléchargement, pas seulement à l'affichage."""
        with self.assertRaises(AccessError):
            self.records_b["document"].with_user(
                self.user_a1,
            )._dally_portal_readable_attachment()

    def test_download_helper_refuses_an_unpublished_document(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises((AccessError, ValidationError)):
            self.records_a["unpublished"].with_user(
                self.user_a1,
            )._dally_portal_readable_attachment()

    def test_download_helper_returns_the_attachment_for_a_legitimate_document(self):
        attachment = self.records_a["document"].with_user(
            self.user_a1,
        )._dally_portal_readable_attachment()
        self.assertTrue(attachment)
        self.assertEqual(attachment, self.records_a["document"].attachment_id)

    def test_attachments_are_not_reachable_directly(self):
        """Le client ne doit pas pouvoir contourner le document en lisant la pièce."""
        target = self.records_b["document"].attachment_id
        found = self.env["ir.attachment"].with_user(self.user_a1).search([
            ("id", "=", target.id),
        ])
        self.assertFalse(found, "une pièce jointe d'un autre client est atteignable")

    # ─── 7. La proposition non envoyée ────────────────────────────────

    def test_draft_proposal_is_invisible_even_to_its_own_client(self):
        """Un prix non validé ne doit pas fuir avant d'avoir été proposé."""
        found = self.env["dally.sourcing.proposal"].with_user(self.user_a1).search([])
        self.assertIn(self.records_a["proposal"], found)
        self.assertNotIn(
            self.records_a["draft_proposal"], found,
            "une proposition en brouillon est visible du client",
        )

    # ─── 8. Le personnel garde son accès ──────────────────────────────

    def test_staff_still_sees_everything(self):
        """Le cloisonnement ne doit pas se retourner contre l'usage interne."""
        for model, key in self.MODELS:
            seen = self.env[model].with_user(self.staff).search([]).ids
            self.assertIn(self.records_a[key].id, seen, f"le staff perd {model} (A)")
            self.assertIn(self.records_b[key].id, seen, f"le staff perd {model} (B)")

    # ─── 9. L'identité ne vient jamais de la requête ──────────────────

    def test_portal_user_cannot_change_its_own_partner(self):
        """Sinon il suffirait de se réassigner au partenaire d'un autre client."""
        with self.assertRaises(AccessError):
            self.user_a1.with_user(self.user_a1).write({
                "partner_id": self.contact_b1.id,
            })

    def test_portal_user_cannot_grant_itself_internal_groups(self):
        with self.assertRaises(AccessError):
            self.user_a1.with_user(self.user_a1).write({
                "group_ids": [(4, self.env.ref("dally_core.group_dally_manager").id)],
            })

    def test_portal_user_holds_no_internal_group(self):
        for group in (
            "base.group_user", "dally_core.group_dally_readonly",
            "dally_core.group_dally_commercial", "dally_core.group_dally_sourcing",
            "dally_core.group_dally_finance", "dally_core.group_dally_manager",
            "dally_trade.group_dally_trade_user",
        ):
            self.assertFalse(
                self.user_a1.has_group(group),
                f"l'utilisateur portail détient {group}",
            )

    def test_portal_user_is_a_share_user(self):
        """`share = True` est ce qui exclut l'utilisateur des règles internes."""
        for user in (self.user_a1, self.user_a2, self.user_b1):
            self.assertTrue(user.share, f"{user.login} n'est pas un utilisateur share")
