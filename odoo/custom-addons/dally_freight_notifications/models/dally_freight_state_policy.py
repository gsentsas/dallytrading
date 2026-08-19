# -*- coding: utf-8 -*-
"""La politique d'un état : ce qui se montre, et ce qui s'écrit.

## Une seule table pour trois questions

Le portail, le suivi public et le courriel posaient la même question — « le
client doit-il savoir ? » — et y répondaient chacun à leur façon. Ici la
réponse est une ligne, et les trois la lisent.

C'est une **donnée** et non du code : couper un courriel trop bavard, corriger
un libellé, réordonner la frise se font dans l'interface, sans déploiement. Un
état ajouté demain apparaît sans politique et reste donc invisible jusqu'à ce
que quelqu'un décide ce qu'il en dit.

## Le sens de l'échec

`_dally_policy_for` rend un enregistrement vide quand rien n'est trouvé, et
tout ce qui en dépend s'interprète alors comme « non ». C'est ce qu'on veut :
l'oubli d'une ligne rend un état muet, jamais bavard.
"""

from odoo import api, fields, models

from odoo.addons.dally_freight.models.dally_shipment import SHIPMENT_STATES


class DallyFreightStatePolicy(models.Model):
    _name = "dally.freight.state.policy"
    _description = "Politique de publication d'un état d'expédition"
    _order = "sequence, id"

    state = fields.Selection(
        selection=SHIPMENT_STATES,
        string="État",
        required=True,
        index=True,
        help="Reprend la sélection de `dally.shipment` plutôt qu'une liste "
             "recopiée : un état ajouté là-bas apparaît ici sans rien changer.",
    )
    sequence = fields.Integer(string="Ordre", default=10)
    customer_label = fields.Char(
        string="Libellé client",
        required=True,
        translate=True,
        help="Le mot que le client lit — sur le badge de suivi comme dans la "
             "frise. Le code technique, lui, ne sort jamais.",
    )
    visible_in_portal = fields.Boolean(
        string="Visible au portail", default=False,
        help="L'espace client montre-t-il cet état et les événements qui le "
             "portent.",
    )
    visible_in_tracking = fields.Boolean(
        string="Visible au suivi public", default=False,
        help="Le suivi par jeton publie-t-il l'événement engendré par cette "
             "transition.",
    )
    notify_customer = fields.Boolean(
        string="Notifier le client", default=False,
        help="Une ligne de notification est-elle mise en file. L'envoi lui-même "
             "reste conditionné à l'existence d'un gabarit, à une adresse et au "
             "consentement du partenaire.",
    )
    email_template_id = fields.Many2one(
        comodel_name="mail.template",
        string="Gabarit",
        ondelete="set null",
        domain=[("model", "=", "dally.shipment.notification")],
        help="Vide : rien ne part, même si la notification est demandée. La "
             "file garde alors une trace « ignorée », avec son motif.",
    )
    active = fields.Boolean(string="Actif", default=True)

    _state_uniq = models.Constraint(
        "unique(state)", "Cet état a déjà une politique.")

    def write(self, vals):
        """Répercuter un changement de politique sur les dossiers en cours.

        `dally.shipment.dally_portal_visible` est **stocké** — une règle
        d'enregistrement doit pouvoir s'y appuyer — et ne dépend que de
        `state`. Sans ce rappel, décocher « visible au portail » ne changerait
        rien aux expéditions déjà dans cet état : elles resteraient visibles
        jusqu'à leur prochaine transition.

        Mesuré, et c'est le pire des deux mondes : la case décochée affiche une
        décision qui n'est pas appliquée.
        """
        resultat = super().write(vals)
        if {"visible_in_portal", "active", "state"} & set(vals):
            expeditions = self.env["dally.shipment"].sudo().search(
                [("state", "in", self.mapped("state"))])
            expeditions._compute_dally_portal_visible()
        return resultat

    @api.model
    def _dally_policy_for(self, state):
        """La politique d'un état, ou un enregistrement vide.

        Vide vaut « non » partout : c'est la seule interprétation qui garde le
        défaut du côté silencieux.
        """
        if not state:
            return self.browse()
        return self.sudo().search([("state", "=", state)], limit=1)

    @api.model
    def _dally_labels_by_state(self, only_tracking=True):
        """Libellés client, par état publiable.

        `only_tracking` reproduit exactement ce que faisait le dictionnaire codé
        en dur qu'elle remplace : n'y figurent que les états dont l'événement
        doit être publié.
        """
        domaine = [("visible_in_tracking", "=", True)] if only_tracking else []
        politiques = self.sudo().search(domaine)
        return {p.state: p.customer_label for p in politiques}
