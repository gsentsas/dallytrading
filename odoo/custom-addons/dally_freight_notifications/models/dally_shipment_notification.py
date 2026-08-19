# -*- coding: utf-8 -*-
"""La file d'attente de ce qu'on écrit au client.

## Pourquoi une file plutôt qu'un envoi

Un courriel envoyé pendant la transaction ferait dépendre un changement d'état
métier de la santé du serveur de messagerie : un SMTP muet annulerait le
passage en « livré ». Ici, la transition écrit une **intention** en base, dans
sa propre transaction, et rend la main. L'envoi viendra après, d'ailleurs, et
pourra échouer sans rien casser.

## Pourquoi une ligne même quand rien ne part

Les lignes `skipped` sont l'essentiel de l'intérêt de cette table. La question
qu'on posera dans six mois n'est pas « combien de courriels sont partis » mais
« pourquoi ce client-là n'a rien reçu » — et un booléen sur l'expédition n'y
répond jamais. Chaque abstention porte donc son motif.

## L'unicité, et ce qu'elle garantit

`unique(event_id)` : une notification par événement de transition. Comme
l'événement n'est créé que sur une **vraie** transition — réécrire l'état qu'un
dossier a déjà n'en produit aucun — la propriété demandée tient sans surveiller
personne : une transition, au plus un message ; une réécriture, aucun.

## La photographie

Les colonnes `shipment_*`, `customer_*`, `origin_*`, `destination_*` et
`tracking_url` sont figées à la création. Le futur gabarit lira **elles**, et
jamais l'expédition. Ce n'est pas de la commodité : le rendu d'un courriel
s'exécute avec un utilisateur technique, pour qui le `groups=` qui protège un
coût d'achat ou une marge ne protège plus rien. Ce qui n'est pas dans cette
table ne peut pas fuir dans un courriel.
"""

from odoo import fields, models

#: Motifs d'abstention. Écrits une fois, lus dans les journaux et les tests.
#: L'événement n'a pas été publié au client. Motif **de chemin** et non
#: d'état : un événement projeté depuis `tk_freight` naît fermé, quel que soit
#: son code d'état, et ne peut donc jamais devenir un courriel.
MOTIF_NON_PUBLIE = "event_not_published"
MOTIF_POLITIQUE = "policy_no_notify"
MOTIF_SANS_GABARIT = "no_template"
MOTIF_SANS_ADRESSE = "no_email"
MOTIF_REFUS_CLIENT = "partner_opted_out"
MOTIF_SANS_DESTINATAIRE = "no_partner"


class DallyShipmentNotification(models.Model):
    _name = "dally.shipment.notification"
    _description = "Notification client d'une expédition"
    _order = "created_at desc, id desc"
    _rec_name = "shipment_reference"

    # ─── Rattachements ───────────────────────────────────────────────

    shipment_id = fields.Many2one(
        comodel_name="dally.shipment", string="Expédition",
        required=True, ondelete="cascade", index=True,
    )
    event_id = fields.Many2one(
        comodel_name="dally.shipment.event", string="Événement",
        required=True, ondelete="cascade", index=True,
        help="L'événement de transition qui a motivé ce message. C'est la clé "
             "d'unicité : un événement, au plus une notification.",
    )
    state = fields.Selection(
        related="event_id.status", string="État", store=True, index=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner", string="Destinataire",
        ondelete="restrict", index=True,
    )
    email = fields.Char(
        string="Adresse",
        help="Figée au moment de la mise en file : si le partenaire change "
             "d'adresse ensuite, on sait où le message est parti.",
    )

    # ─── Cycle de vie ────────────────────────────────────────────────

    status = fields.Selection(
        selection=[
            ("pending", "En attente"),
            ("sent", "Envoyée"),
            ("failed", "Échec"),
            ("skipped", "Ignorée"),
        ],
        string="Statut", default="pending", required=True, index=True,
    )
    mail_id = fields.Many2one(
        comodel_name="mail.mail", string="Courriel", ondelete="set null",
    )
    attempts = fields.Integer(string="Tentatives", default=0, readonly=True)
    last_error = fields.Char(
        string="Dernier motif",
        help="Motif d'abstention ou message d'échec. Toujours renseigné quand "
             "le statut n'est ni « en attente » ni « envoyée ».",
    )
    created_at = fields.Datetime(
        string="Créée le", required=True, readonly=True,
        default=fields.Datetime.now,
    )
    sent_at = fields.Datetime(string="Envoyée le", readonly=True)

    # ─── Photographie sûre, destinée au gabarit ──────────────────────

    shipment_reference = fields.Char(string="Référence", readonly=True)
    customer_label = fields.Char(string="Libellé client", readonly=True)
    customer_message = fields.Char(
        string="Message client", readonly=True,
        help="Phrase publiée dans la frise pour cette transition. Le gabarit "
             "s'en sert comme corps de message.",
    )
    origin_label = fields.Char(string="Origine", readonly=True)
    destination_label = fields.Char(string="Destination", readonly=True)
    event_date = fields.Datetime(string="Date de l'événement", readonly=True)
    tracking_url = fields.Char(
        string="Lien de suivi", readonly=True,
        help="Adresse publique portant le jeton de suivi. Aucun identifiant "
             "de base n'y figure.",
    )

    _event_uniq = models.Constraint(
        "unique(event_id)",
        "Cet événement a déjà sa notification.",
    )
