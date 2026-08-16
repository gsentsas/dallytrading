"""
Les deux seuls liens entre DallyTrading et `tk_freight`.

## Pourquoi deux, et pas trois

Le réflexe serait de poser sur le devis un lien vers le booking *et* un lien
vers l'expédition. C'est une clé étrangère de trop : `freight.shipment.booking_id`
est une relation du fournisseur, stable et vérifiée — l'expédition se retrouve
depuis le booking sans rien stocker de plus. Un second lien devrait être tenu à
jour en parallèle, et deux écritures qui doivent rester d'accord finissent
toujours par diverger.

Les deux liens conservés ancrent chacun une invariante différente :

* `shipment.freight.booking.dally_quote_request_id` ancre l'**idempotence du
  provisionnement** : un devis accepté produit au plus un booking.
* `dally.shipment.tk_shipment_id` ancre l'**unicité de la projection** : une
  expédition opérationnelle est projetée au plus une fois côté client.

## Pourquoi une contrainte SQL et non un `search()` suivi d'un `create()`

Deux transactions concurrentes exécutent toutes les deux le `search()`, n'en
trouvent aucune, et créent chacune la leur. Le contrôle applicatif ne voit rien
passer : la fenêtre est étroite mais réelle, et c'est exactement ce que produit
un double clic ou un rejeu Odoo après `SerializationFailure`.

Un index unique, lui, est évalué par PostgreSQL au moment de l'écriture. Il ne
peut pas être contourné par un ordre d'exécution malheureux, ni par un appelant
qui aurait oublié de passer par la méthode prévue.
"""

from odoo import fields, models


class ShipmentFreightBooking(models.Model):
    """Rattache un booking du fournisseur au devis Dally qui l'a provoqué."""

    _name = "shipment.freight.booking"
    _inherit = "shipment.freight.booking"

    dally_quote_request_id = fields.Many2one(
        comodel_name="dally.quote.request",
        string="Demande de devis DallyTrading",
        index=True,
        ondelete="restrict",
        copy=False,
        help="Devis dont l'acceptation a provoqué ce booking. Vide pour un "
             "booking saisi directement dans le back-office.",
    )

    # `ondelete="restrict"` ci-dessus, et non `cascade` : supprimer un devis ne
    # doit pas faire disparaître une expédition physique en cours. Le refus est
    # le bon comportement — il force à traiter le cas à la main.

    _dally_quote_unique = models.Constraint(
        "UNIQUE (dally_quote_request_id)",
        "Ce devis a déjà provoqué un booking fret.",
    )


class DallyShipment(models.Model):
    """Rattache la projection client à l'expédition opérationnelle du fournisseur."""

    _name = "dally.shipment"
    _inherit = "dally.shipment"

    tk_shipment_id = fields.Many2one(
        comodel_name="freight.shipment",
        string="Expédition opérationnelle",
        index=True,
        ondelete="set null",
        copy=False,
        # Jamais exposé au portail : le contrat client ne connaît que la
        # référence Dally. Voir la note de sécurité de `dally_portal`.
        groups="dally_core.group_dally_readonly",
        help="Expédition tk_freight dont cet enregistrement est la projection. "
             "Vide pour une expédition saisie hors du moteur fret.",
    )

    #: Source de vérité. `freight.shipment` est l'objet **opérationnel** ;
    #: `dally.shipment` en est la **projection client**. La synchronisation est
    #: à sens unique, tk → Dally. Rien dans le portail ne réécrit tk.
    _dally_tk_shipment_unique = models.Constraint(
        "UNIQUE (tk_shipment_id)",
        "Cette expédition opérationnelle est déjà projetée.",
    )
