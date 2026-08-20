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

    @api.model
    def _dally_refresh_portal_visibility(self, states):
        """Recalcule le drapeau stocké des dossiers portant ``states``.

        Le champ ``dally.shipment.dally_portal_visible`` doit être stocké pour
        pouvoir servir dans une règle d'enregistrement. Sa valeur dépend pourtant
        d'une *autre table* — la politique — qu'``@api.depends`` ne peut pas
        exprimer directement.

        Le recalcul doit donc être déclenché à chaque mutation de politique,
        y compris à sa **création**. C'est essentiel à l'installation du module :
        Odoo crée d'abord la colonne calculée sur les expéditions existantes, puis
        charge les lignes XML de politique. Sans ce rappel à la création, les
        dossiers existants gardent la valeur fail-closed calculée avant que les
        politiques n'existent et restent invisibles jusqu'à leur prochain changement
        d'état.
        """
        states = {state for state in states if state}
        if not states:
            return
        expeditions = self.env["dally.shipment"].sudo().search(
            [("state", "in", list(states))]
        )
        if expeditions:
            expeditions._compute_dally_portal_visible()

    @api.model_create_multi
    def create(self, vals_list):
        politiques = super().create(vals_list)
        politiques._dally_refresh_portal_visibility(politiques.mapped("state"))
        return politiques

    def write(self, vals):
        """Répercuter un changement de politique sur les dossiers en cours.

        ``dally.shipment.dally_portal_visible`` est stocké : décocher la
        visibilité, archiver une politique ou déplacer sa ligne vers un autre
        état doit donc recalculer immédiatement les dossiers concernés.

        Pour un changement de ``state``, on recalcule **l'ancien et le nouveau**
        code. Sinon les dossiers restés sur l'ancien état conserveraient une
        valeur périmée après le déplacement de la politique.
        """
        anciens_etats = set(self.mapped("state"))
        resultat = super().write(vals)
        if {"visible_in_portal", "active", "state"} & set(vals):
            nouveaux_etats = set(self.mapped("state"))
            self._dally_refresh_portal_visibility(anciens_etats | nouveaux_etats)
        return resultat

    def unlink(self):
        """Une politique supprimée ferme immédiatement les dossiers concernés."""
        etats = set(self.mapped("state"))
        resultat = super().unlink()
        self._dally_refresh_portal_visibility(etats)
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
