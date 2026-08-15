# -*- coding: utf-8 -*-
"""Le client d'une proposition est celui de sa demande — invariant, pas convention.

## Ce qui avait été constaté

Une proposition créée directement, sans passer par ``_dally_draft_from_offer``,
gardait ``customer_id`` vide. La record rule portail filtre sur ce champ : la
proposition devenait alors invisible de **tous** les clients, sans la moindre
erreur. Découvert en validation E2E, où le détail d'une demande de sourcing
renvoyait ``"proposals": []`` alors que la proposition existait bien en état
``sent``.

L'échec était fermé — donc rien ne fuitait — mais il tenait entièrement à ce
qu'un seul chemin de création pense à recopier le champ.

## Ce que ces tests garantissent

Que la dérivation vient du modèle et non d'un appelant : quel que soit le chemin
de création, le client d'une proposition est celui de sa demande, et un état
divergent ne peut pas être construit.
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally", "dally_sourcing")
class TestProposalCustomerInvariant(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env.user.write({"group_ids": [(4, self.env.ref(
            "dally_sourcing.group_dally_sourcing_manager"
        ).id)]})
        Partner = self.env["res.partner"]
        self.customer_a = Partner.create({
            "name": "INV Client A", "is_company": True,
        })
        self.customer_b = Partner.create({
            "name": "INV Client B", "is_company": True,
        })
        self.request_a = self.env["dally.sourcing.request"].create({
            "product_name": "INV produit A",
            "quantity": 10.0,
            "customer_id": self.customer_a.id,
        })
        self.request_b = self.env["dally.sourcing.request"].create({
            "product_name": "INV produit B",
            "quantity": 10.0,
            "customer_id": self.customer_b.id,
        })

    def _proposal(self, request, **overrides):
        values = {
            "request_id": request.id,
            "product_name": "INV proposition",
            "quantity": 10.0,
            "selling_unit_price": 100.0,
        }
        values.update(overrides)
        return self.env["dally.sourcing.proposal"].create(values)

    # ─── 1. Création directe ─────────────────────────────────────────

    def test_direct_creation_derives_the_customer(self):
        """Le cas qui échouait : création sans mentionner le client."""
        proposal = self._proposal(self.request_a)
        self.assertEqual(
            proposal.customer_id, self.customer_a,
            "une proposition créée directement doit hériter du client de sa demande",
        )

    def test_creation_through_the_normal_flow_still_works(self):
        """Le flux existant ne doit pas régresser.

        `_dally_draft_from_offer` n'écrit plus `customer_id` — sur un champ
        `related`, l'écriture remonterait à la source et changerait le client de
        la demande. Le résultat doit être le même qu'avant.
        """
        supplier = self.env["dally.sourcing.supplier"].create({
            "request_id": self.request_a.id,
            "partner_id": self.env["res.partner"].create({
                "name": "INV Usine", "is_company": True,
            }).id,
        })
        offer = self.env["dally.sourcing.offer"].create({
            "request_id": self.request_a.id,
            "supplier_id": supplier.id,
            "quantity": 10.0,
            "unit_price": 50.0,
        })
        offer.action_create_proposal()
        proposal = self.env["dally.sourcing.proposal"].search(
            [("request_id", "=", self.request_a.id)], limit=1, order="id desc",
        )
        self.assertEqual(proposal.customer_id, self.customer_a)
        # Et la demande n'a pas été modifiée au passage.
        self.assertEqual(self.request_a.customer_id, self.customer_a)

    # ─── 2. État incohérent impossible ───────────────────────────────

    def test_a_conflicting_customer_at_creation_cannot_produce_a_bad_state(self):
        """Demande A + client B : l'état incohérent doit être impossible.

        Deux issues acceptables — la valeur fournie est ignorée au profit de
        celle de la demande, ou la création est refusée. Ce qui ne l'est pas,
        c'est une proposition enregistrée avec un client autre que celui de sa
        demande, et le test l'exprime ainsi plutôt que d'imposer un mécanisme.
        """
        try:
            proposal = self._proposal(self.request_a, customer_id=self.customer_b.id)
        except ValidationError:
            return
        self.assertEqual(
            proposal.customer_id, self.customer_a,
            "un client contradictoire a été accepté : l'état incohérent est possible",
        )

    # ─── 3. Modification incohérente ─────────────────────────────────

    def test_writing_a_conflicting_customer_is_refused(self):
        """La dérivation seule ne suffisait pas : mesuré.

        Odoo 19 accepte l'écriture d'un champ calculé STOCKÉ sans inverse, et la
        valeur persiste jusqu'au prochain recalcul. C'est la contrainte qui ferme
        cette fenêtre.
        """
        proposal = self._proposal(self.request_a)
        with self.assertRaises(ValidationError):
            proposal.write({"customer_id": self.customer_b.id})

    def test_a_refused_write_leaves_the_request_untouched(self):
        """Le danger précis qu'un champ `related` aurait créé.

        Avec `related`, l'écriture ne divergeait pas : elle REMONTAIT à la source
        et changeait le client de la DEMANDE. Ce test verrouille l'absence de cet
        effet, qui serait silencieux et bien pire qu'un refus.
        """
        proposal = self._proposal(self.request_a)
        with self.assertRaises(ValidationError):
            proposal.write({"customer_id": self.customer_b.id})
        self.request_a.invalidate_recordset()
        self.assertEqual(
            self.request_a.customer_id, self.customer_a,
            "l'écriture a remonté jusqu'à la demande et changé SON client",
        )

    def test_moving_the_proposal_to_another_request_follows(self):
        """Changer la demande change le client : c'est le sens de la dérivation."""
        proposal = self._proposal(self.request_a)
        proposal.write({"request_id": self.request_b.id})
        self.assertEqual(proposal.customer_id, self.customer_b)

    def test_qualifying_the_request_propagates_to_its_proposals(self):
        """Le cas métier réel : le client est identifié APRÈS la proposition.

        Une demande arrive sans client (c'est le comportement voulu à l'intake) ;
        la qualification le renseigne plus tard. La proposition déjà rédigée doit
        alors devenir visible du client, sans intervention.
        """
        anonymous = self.env["dally.sourcing.request"].create({
            "product_name": "INV produit anonyme",
            "quantity": 1.0,
            "contact_email": "prospect@example.invalid",
        })
        proposal = self._proposal(anonymous)
        self.assertFalse(proposal.customer_id)

        anonymous.write({"customer_id": self.customer_a.id})
        proposal.invalidate_recordset()
        self.assertEqual(
            proposal.customer_id, self.customer_a,
            "la qualification de la demande ne s'est pas propagée à la proposition",
        )

    # ─── 4. Le champ est bien stocké et cherchable ───────────────────

    def test_the_derived_field_is_stored_and_searchable(self):
        """La record rule portail fait un `search` dessus : il doit être stocké.

        Un champ dérivé non stocké serait cohérent à la lecture et introuvable à
        la recherche — la règle ne filtrerait alors plus rien.
        """
        field = self.env["dally.sourcing.proposal"]._fields["customer_id"]
        self.assertTrue(field.store, "customer_id doit être stocké")
        self.assertTrue(field.readonly, "customer_id doit être en lecture seule")

        proposal = self._proposal(self.request_a)
        found = self.env["dally.sourcing.proposal"].search([
            ("customer_id", "=", self.customer_a.id),
        ])
        self.assertIn(proposal, found)
