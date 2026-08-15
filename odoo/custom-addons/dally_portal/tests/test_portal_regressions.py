# -*- coding: utf-8 -*-
"""Non-régressions : trois défauts trouvés le 15 août 2026, et leurs gardes.

Chacun de ces tests existe parce que le problème correspondant a été RÉELLEMENT
observé sur une instance Odoo 19, pas parce qu'il était concevable. Le commentaire
de chaque classe décrit ce qui s'était produit — sans quoi un futur relecteur
pourrait juger le test inutile et le supprimer, ce qui rouvrirait la porte.
"""

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestFieldsGetGuard(TransactionCase):
    """`fields_get` n'était contrôlé par rien.

    Un utilisateur portail authentifié obtenait, via `/web/dataset/call_kw`, la
    description complète de modèles sur lesquels il n'a AUCUNE ACL : nom des
    champs, libellés, textes d'aide. Aucune donnée ne fuitait — `fields_get` ne
    renvoie pas d'enregistrements — mais la réponse contenait `landed_unit_cost`,
    `overall_score`, `internal_notes` et leurs aides, qui décrivent comment nous
    comparons des fournisseurs et construisons une proposition.
    """

    #: Exactement la liste que garde `internal_schema_guard.py`, plus dally.api.key
    #: qui se protège lui-même dans son propre module.
    GUARDED_MODELS = (
        "dally.sourcing.offer",
        "dally.sourcing.supplier",
        "dally.trade.cost",
        "dally.trade.commission",
        "dally.api.key",
    )

    def setUp(self):
        super().setUp()
        company = self.env["res.partner"].create({
            "name": "REG Société", "is_company": True,
        })
        contact = self.env["res.partner"].create({
            "name": "REG Contact", "parent_id": company.id,
        })
        self.portal_user = self.env["res.users"].create({
            "name": "REG Portail",
            "login": "reg.portal@regression-test.invalid",
            "partner_id": contact.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })

    def test_portal_cannot_describe_internal_models(self):
        for model in self.GUARDED_MODELS:
            with self.assertRaises(
                AccessError, msg=f"{model}.fields_get répond à un utilisateur portail",
            ):
                self.env[model].with_user(self.portal_user).fields_get()

    def test_staff_can_still_describe_them(self):
        """Le garde-fou ne doit pas casser les écrans internes.

        C'est la moitié qui compte vraiment : refuser tout le monde serait facile
        et rendrait l'interface interne inutilisable. Un utilisateur qui a l'ACL
        ne doit voir aucune différence.
        """
        for model in self.GUARDED_MODELS:
            described = self.env[model].fields_get()
            self.assertIn("id", described, f"{model} n'est plus descriptible en interne")


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestNoGhostModels(TransactionCase):
    """Odoo 19 a changé le sens de `_inherit` sous forme de liste.

    Écrire `_inherit = ["dally.quote.request", "un.mixin"]` SANS `_name` ne
    signifie plus « étendre ce modèle ». Odoo dérive un nom depuis le nom de la
    classe et crée un modèle NEUF — `dally.quote.request.portal` — avec sa propre
    table. Les projections avaient silencieusement disparu des vrais modèles, et
    un `upgrade` en production aurait créé quatre tables inutiles.

    Rien n'avait échoué : ni le chargement, ni les tests d'alors. Seule
    l'inspection du MRO l'a montré. D'où ce test, qui interroge le registre.
    """

    GHOSTS = (
        "dally.quote.request.portal",
        "dally.sourcing.request.portal",
        "dally.trade.opportunity.portal",
        "dally.shipment.portal",
    )

    def test_no_ghost_model_exists_in_the_registry(self):
        present = [name for name in self.GHOSTS if name in self.env.registry]
        self.assertEqual(
            present, [],
            "modèle(s) fantôme(s) recréé(s) : un `_inherit` en liste a perdu son "
            "`_name`, et les projections ont quitté les vrais modèles",
        )

    def test_no_model_name_ends_with_dot_portal(self):
        """Filet plus large : la même faute sur un futur modèle.

        La liste ci-dessus ne couvre que les quatre cas connus. Ce test attrape
        aussi `dally.autre.chose.portal`, que personne n'a encore écrit.
        """
        suspects = [name for name in self.env.registry if name.endswith(".portal")]
        self.assertEqual(suspects, [], f"modèles suspects : {suspects}")

    def test_projections_live_on_the_real_models(self):
        """Le pendant positif : les vrais modèles ont bien les deux projections.

        Sans lui, supprimer les classes ferait passer les tests ci-dessus.
        """
        for name in ("dally.quote.request", "dally.sourcing.request",
                     "dally.trade.opportunity", "dally.shipment",
                     "dally.portal.document"):
            model = self.env[name]
            self.assertTrue(
                hasattr(type(model), "_dally_portal_payload"),
                f"{name} a perdu sa projection portail",
            )
            self.assertTrue(
                hasattr(type(model), "_dally_portal_detail_payload"),
                f"{name} a perdu sa projection de détail",
            )


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestDocumentLinkConstraint(TransactionCase):
    """`@api.constrains` ne se déclenchait pas quand AUCUN lien n'était fourni.

    À la création, Odoo ne valide que les champs présents dans les valeurs. Un
    document créé sans aucun rattachement ne touchait donc aucun champ surveillé
    et échappait à `_check_exactly_one_business_link`.

    Ce n'était pas exploitable — sans `commercial_partner_id`, la record rule ne
    le montre à personne — mais un état interdit qui existe finit par être traité
    comme autorisé.
    """

    def setUp(self):
        super().setUp()
        self.attachment = self.env["ir.attachment"].create({
            "name": "regression.txt", "datas": b"cmVncmVzc2lvbg==",
        })
        partner = self.env["res.partner"].create({
            "name": "REG DOC Société", "is_company": True,
        })
        self.shipment = self.env["dally.shipment"].create({
            "partner_id": partner.id, "transport_mode": "sea",
        })
        self.sourcing = self.env["dally.sourcing.request"].create({
            "customer_id": partner.id, "product_name": "REG produit",
            "quantity": 1.0,
        })

    def _create(self, **links):
        return self.env["dally.portal.document"].create({
            "name": "REG document",
            "attachment_id": self.attachment.id,
            "document_type": "other",
            **links,
        })

    def test_zero_link_is_refused(self):
        with self.assertRaises(ValidationError):
            self._create()

    def test_one_link_is_accepted(self):
        document = self._create(shipment_id=self.shipment.id)
        self.assertTrue(document.exists())
        self.assertTrue(document.commercial_partner_id)

    def test_two_links_are_refused(self):
        with self.assertRaises(ValidationError):
            self._create(
                shipment_id=self.shipment.id,
                sourcing_request_id=self.sourcing.id,
            )

    def test_clearing_the_only_link_is_refused(self):
        """Et à l'écriture aussi, pas seulement à la création."""
        document = self._create(shipment_id=self.shipment.id)
        with self.assertRaises(ValidationError):
            document.write({"shipment_id": False})
