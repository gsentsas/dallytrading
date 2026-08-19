# -*- coding: utf-8 -*-
"""L'expédition, branchée sur la politique et sur la file.

## Ce que ce fichier remplace

`dally_tracking` décidait de publier un événement selon la présence d'une
phrase dans un dictionnaire écrit en Python. Ce dictionnaire était la seconde
liste de vérité qu'on voulait supprimer : il vivait dans le code, se déployait,
et ne disait rien au portail. `_dally_public_state_wording` lit désormais la
politique, et tout ce qui en dépend suit sans autre changement — la visibilité
de l'événement en découlait déjà.

## Où la file se remplit

Dans `create()` de l'événement, et non dans le `write()` de l'expédition. C'est
plus sûr et plus simple : l'événement automatique **est** la matérialisation
d'une vraie transition — `dally_tracking` saute déjà le cas « on réécrit l'état
qu'il a déjà » — donc s'y accrocher donne exactement « une transition, au plus
un message » sans avoir à comparer quoi que ce soit.

Un événement saisi à la main ne notifie pas : il décrit souvent un fait
intermédiaire, et l'opérateur qui veut écrire au client le fera explicitement.
"""

from odoo import api, fields, models

from .dally_shipment_notification import (
    MOTIF_NON_PUBLIE,
    MOTIF_POLITIQUE,
    MOTIF_REFUS_CLIENT,
    MOTIF_SANS_ADRESSE,
    MOTIF_SANS_DESTINATAIRE,
    MOTIF_SANS_GABARIT,
)


class DallyShipment(models.Model):
    # `_name` explicite : sans lui, Odoo 19 créerait un modèle fantôme.
    _name = "dally.shipment"
    _inherit = "dally.shipment"

    notification_ids = fields.One2many(
        comodel_name="dally.shipment.notification",
        inverse_name="shipment_id",
        string="Notifications",
    )
    dally_portal_visible = fields.Boolean(
        string="Visible au portail",
        compute="_compute_dally_portal_visible",
        store=True,
        index=True,
        help="Dérivé de la politique de l'état courant. Stocké et indexé "
             "parce qu'une règle d'enregistrement doit pouvoir s'y appuyer : "
             "un champ calculé non stocké ne se cherche pas.",
    )

    @api.depends("state")
    def _compute_dally_portal_visible(self):
        Politique = self.env["dally.freight.state.policy"]
        for shipment in self:
            politique = Politique._dally_policy_for(shipment.state)
            shipment.dally_portal_visible = bool(politique.visible_in_portal)

    # ------------------------------------------------------------------
    # La politique remplace la liste codée en dur
    # ------------------------------------------------------------------

    @api.model
    def _dally_public_state_wording(self):
        """Libellés client des états publiables, lus dans la politique.

        Même contrat que la méthode qu'elle remplace : un état absent du
        dictionnaire produit un événement interne. Ici, « absent » veut dire
        sans politique, politique archivée, ou politique qui ne publie pas —
        trois façons de dire non, et aucune de dire oui par défaut.
        """
        return self.env["dally.freight.state.policy"]._dally_labels_by_state()

    # ------------------------------------------------------------------
    # Alignement du portail
    # ------------------------------------------------------------------

    def _dally_public_payload(self):
        """Le suivi public respecte aussi la politique **du jour**.

        Un événement porte `visible_to_customer`, décidé au moment de la
        transition : c'est un fait historique, et il reste écrit. Mais la
        décision de montrer cet état, elle, doit rester révocable — décocher
        « visible au suivi » doit retirer immédiatement les anciens événements
        de l'API publique, sans réécrire l'histoire.

        Les deux conditions sont donc exigées, comme au portail : publié alors,
        et publiable aujourd'hui.
        """
        payload = super()._dally_public_payload()

        publiables = self._dally_tracking_states()
        visibles = self.event_ids.filtered(
            lambda evenement: evenement.visible_to_customer
            and evenement.status in publiables
        )
        payload["timeline"] = visibles._dally_public_event_payload()

        # `lastUpdate` doit suivre la même règle : sinon la page annoncerait une
        # mise à jour dont elle ne montre plus la ligne.
        dernier = visibles.sorted(
            key=lambda e: (e.event_date, e.id), reverse=True)[:1]
        payload["lastUpdate"] = (
            dernier.event_date.isoformat() if dernier and dernier.event_date
            else None
        )

        politique = self.env["dally.freight.state.policy"]._dally_policy_for(
            self.state)
        if politique.customer_label:
            payload["statusLabel"] = politique.customer_label
        return payload

    @api.model
    def _dally_tracking_states(self):
        """États dont les événements sortent aujourd'hui par le suivi public."""
        return set(self.env["dally.freight.state.policy"].sudo().search([
            ("visible_in_tracking", "=", True)]).mapped("state"))

    def _dally_portal_timeline(self):
        """Événements publiables **au portail**.

        Deux conditions, et non une : l'événement doit avoir été publié
        (`visible_to_customer`, décidé au moment de la transition) et son état
        doit être visible au portail aujourd'hui. La première est un fait
        historique, la seconde une décision révocable — décocher un état retire
        ses événements de l'espace client sans réécrire l'histoire.
        """
        self.ensure_one()
        etats = set(self.env["dally.freight.state.policy"].sudo().search([
            ("visible_in_portal", "=", True)]).mapped("state"))
        return self.event_ids.filtered(
            lambda evenement: evenement.visible_to_customer
            and evenement.status in etats
        )


class DallyShipmentEvent(models.Model):
    _name = "dally.shipment.event"
    _inherit = "dally.shipment.event"

    notification_id = fields.One2many(
        comodel_name="dally.shipment.notification",
        inverse_name="event_id",
        string="Notification",
    )

    @api.model_create_multi
    def create(self, vals_list):
        evenements = super().create(vals_list)
        # Seuls les événements engendrés par une transition mettent en file.
        evenements.filtered("is_automatic")._dally_enqueue_notification()
        return evenements

    def _dally_enqueue_notification(self):
        """Poser au plus une intention de message par événement.

        Aucun envoi ici : on est dans la transaction métier, et un serveur de
        messagerie muet ne doit pas empêcher une expédition de passer en
        « livré ». On écrit ce qu'on voulait dire, et à qui ; le reste viendra
        d'ailleurs.

        Toutes les raisons de ne pas écrire produisent une ligne « ignorée »
        avec son motif, jamais un silence : c'est cette trace qui permettra de
        répondre à « pourquoi ce client n'a-t-il rien reçu ».
        """
        Notification = self.env["dally.shipment.notification"].sudo()
        Politique = self.env["dally.freight.state.policy"]

        for evenement in self:
            expedition = evenement.shipment_id
            if not expedition:
                continue

            politique = Politique._dally_policy_for(evenement.status)
            destinataire = expedition.partner_id

            motif = None
            # Premier contrôle, et le plus fort : on n'écrit au client que sur
            # ce qu'on lui montre.
            #
            # La séparation tient au **chemin de création**, non au code
            # d'état. Un événement projeté depuis `tk_freight` est créé avec
            # `visible_to_customer=False` en dur par la synchronisation, qui ne
            # consulte jamais la politique : même mappé un jour sur
            # `request_received`, il resterait fermé et ne partirait pas. Un
            # événement issu de notre propre transition, lui, tient sa
            # visibilité de la politique.
            #
            # La ligne est tout de même écrite, avec son motif : la file doit
            # pouvoir répondre à « pourquoi ce client n'a-t-il rien reçu ».
            if not evenement.visible_to_customer:
                motif = MOTIF_NON_PUBLIE
            elif not politique.notify_customer:
                motif = MOTIF_POLITIQUE
            elif not politique.email_template_id:
                motif = MOTIF_SANS_GABARIT
            elif not destinataire:
                motif = MOTIF_SANS_DESTINATAIRE
            elif not destinataire.email:
                motif = MOTIF_SANS_ADRESSE
            elif not destinataire.dally_freight_notify:
                motif = MOTIF_REFUS_CLIENT

            Notification.create({
                "shipment_id": expedition.id,
                "event_id": evenement.id,
                "partner_id": destinataire.id or False,
                "email": destinataire.email or False,
                "status": "skipped" if motif else "pending",
                "last_error": motif or False,
                # ── La photographie sûre ──
                #
                # Référence, libellé, trajet, date, lien : de quoi écrire un
                # message complet sans jamais relire l'expédition. Ni coût, ni
                # marge, ni note interne, ni transporteur : ce qui n'est pas
                # ici ne peut pas fuir dans un courriel rendu en
                # superutilisateur.
                "shipment_reference": expedition.reference or False,
                "customer_label": politique.customer_label or False,
                "customer_message": evenement.description or False,
                "origin_label": expedition._format_place(
                    expedition.origin_location, expedition.origin_city,
                    expedition.origin_country_id) or False,
                "destination_label": expedition._format_place(
                    expedition.destination_location, expedition.destination_city,
                    expedition.destination_country_id) or False,
                "event_date": evenement.event_date,
                "tracking_url": expedition.public_tracking_url or False,
            })
