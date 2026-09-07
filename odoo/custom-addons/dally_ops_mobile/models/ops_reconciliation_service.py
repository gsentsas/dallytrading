# -*- coding: utf-8 -*-
"""Ce que le comptoir doit savoir de l'état d'un dossier, en un seul coup d'œil.

Trois questions reviennent sans cesse et n'avaient jusqu'ici aucune réponse dans
Ops : le dossier est-il enregistré dans le CRM, a-t-il été projeté dans le
tableur, et où en est sa facturation ? L'opérateur ouvrait Odoo, puis le
classeur, puis recomptait de tête.

Ce service répond côté serveur. Il ne décide rien de neuf : il lit ce que Freight
et l'outbox savent déjà, et le traduit en vocabulaire d'opérateur.

## Ce qui ne descend jamais

Aucun identifiant Odoo. Ni `account.move.id`, ni `sale.order.id`, ni
`res.partner.id`, ni l'`id` d'une ligne d'outbox. Une facture se désigne par son
numéro comptable, un dossier par sa référence métier. Publier une clé primaire
inviterait l'écran à raisonner dessus, puis à la renvoyer un jour.

Le `last_error` de l'outbox ne descend pas davantage : c'est un message de
transport, écrit pour un journal, pas pour un opérateur. Un message métier
sanitisé le remplace.
"""
from odoo import _, api, models

#: L'état de projection, dit à l'opérateur plutôt qu'au transporteur.
#:
#: `processing` rejoint `pending` : qu'un envoi soit en vol ou en file d'attente
#: ne change rien pour le comptoir — dans les deux cas, ce n'est pas encore
#: arrivé, et il n'y a rien à faire.
ETAT_PROJECTION = {
    "delivered": "synced",
    "pending": "pending",
    "processing": "pending",
    "retry": "retry",
    "failed": "failed",
}

#: Les messages d'opérateur, un par état. Jamais l'erreur brute du transport.
MESSAGE_PROJECTION = {
    "synced": lambda: _("Synchronisé avec le tableur."),
    "pending": lambda: _("En attente de synchronisation."),
    "retry": lambda: _("Nouvelle tentative prévue."),
    "failed": lambda: _("Échec de synchronisation. Prévenez le responsable."),
    "absent": lambda: _("Aucune synchronisation demandée pour ce dossier."),
}

#: L'ordre de gravité. Un dossier dont une projection a échoué est en échec,
#: même si dix autres sont passées : c'est la mauvaise nouvelle qui compte.
GRAVITE = ("failed", "retry", "pending", "synced")


class DallyOpsReconciliationService(models.AbstractModel):
    _name = "dally.ops.reconciliation.service"
    _description = "DallyTrading Ops — état CRM / tableur / facturation"

    # ------------------------------------------------------------------
    # L'entrée publique
    # ------------------------------------------------------------------

    @api.model
    def summary_for(self, shipment):
        """L'état complet d'un dossier, en vocabulaire d'opérateur.

        Lecture seule : rien n'est écrit, rien n'est déclenché. La fiche appelle
        cette méthode, l'écran affiche ce qu'elle rend.
        """
        shipment.ensure_one()
        projection = self._projection(shipment)
        facturation = self._facturation(shipment)
        return {
            "crm": {"state": "recorded", "reference": shipment.external_reference},
            "sheet": projection,
            "billing": facturation,
            "allowed_actions": self._actions(shipment),
        }

    # ------------------------------------------------------------------
    # La projection vers le tableur
    # ------------------------------------------------------------------

    @api.model
    def _projection(self, shipment):
        """L'état de l'outbox pour ce dossier, réduit à ce qui se dit.

        Plusieurs projections peuvent viser le même dossier — le dossier
        lui-même, ses lignes, ses encaissements. L'opérateur n'a pas à les
        démêler : on retient la plus grave.
        """
        # L'identité autoritaire d'une projection est le triplet sous contrainte
        # UNIQUE du modèle : société, type, clé métier. Chercher sur la seule
        # référence lisible laisserait deux sociétés qui portent la même
        # référence se contaminer — et `sudo()` retire justement le filtre qui
        # l'aurait évité.
        cle = self.env["dally.ops.sheet.outbox"].business_key_for(shipment)
        if not cle:
            return self._projection_absente()
        lignes = self.env["dally.ops.sheet.outbox"].sudo().search([
            ("company_id", "=", shipment.company_id.id),
            ("projection_type", "=", "freight_dossier"),
            ("business_key", "=", cle),
        ])
        if not lignes:
            return self._projection_absente()

        etats = [ETAT_PROJECTION.get(ligne.state, "pending") for ligne in lignes]
        pire = next((etat for etat in GRAVITE if etat in etats), "synced")
        livrees = [ligne.delivered_at for ligne in lignes if ligne.delivered_at]
        return {
            "state": pire,
            "operator_message": MESSAGE_PROJECTION[pire](),
            "pending_count": sum(1 for etat in etats if etat in ("pending", "retry")),
            "failed_count": sum(1 for etat in etats if etat == "failed"),
            "last_synced_at": max(livrees).isoformat() if livrees else None,
        }

    @api.model
    def _projection_absente(self):
        """Construit le résumé métier quand aucune projection Sheet n'existe."""
        return {
            "state": "absent",
            "operator_message": MESSAGE_PROJECTION["absent"](),
            "pending_count": 0,
            "failed_count": 0,
            "last_synced_at": None,
        }

    # ------------------------------------------------------------------
    # La facturation
    # ------------------------------------------------------------------

    @api.model
    def _facturation(self, shipment):
        """Ce que le dossier doit, a facturé, et n'a pas encore facturé.

        Les compléments et les colis non facturés se lisent par les méthodes de
        Freight : la règle de couverture appartient à la facturation, pas à Ops.
        Les recopier ici en ferait deux versions qui divergeraient.
        """
        dossier = shipment.sudo()
        principale = dossier.invoice_id
        complements = dossier._supplement_invoices()
        en_attente = dossier._pending_packages()

        # `transport_amount_eur` est le champ autoritaire de la facturation :
        # il est stocké, calculé par Freight, et sait déjà qu'un article « sur
        # devis » ne vaut rien tant qu'il n'est pas chiffré. Refaire ici la
        # multiplication donnerait un montant pour un devis — un deuxième
        # moteur de valorisation, et une divergence le jour où la règle bouge.
        montant_attente = sum(en_attente.mapped("transport_amount_eur"))
        devise = (principale.currency_id.name if principale else None) or "EUR"

        # Deux niveaux, nommés pour ce qu'ils sont. Un champ « reste à payer »
        # qui ne parlerait que de la principale mentirait dès qu'un complément
        # comptabilisé reste impayé — et c'est précisément le cas que cette
        # phase introduit.
        #
        # Les totaux ne comptent que les pièces COMPTABILISÉES : un brouillon
        # n'est pas encore dû, une pièce annulée ne l'est plus.
        postees = complements.filtered(lambda piece: piece.state == "posted")
        pieces = (principale if principale.state == "posted" else
                  principale.browse()) | postees

        return {
            "currency": devise,
            "primary_invoice_number": principale.name if principale else None,
            "primary_invoice_state": principale.state if principale else "none",
            "primary_invoice_amount": round(
                principale.amount_total, 2) if principale else 0.0,
            "primary_paid_amount": round(
                principale.amount_total - principale.amount_residual, 2
            ) if principale else 0.0,
            "primary_remaining_amount": round(
                principale.amount_residual, 2) if principale else 0.0,
            "total_invoiced_amount": round(sum(pieces.mapped("amount_total")), 2),
            "total_paid_amount": round(
                sum(pieces.mapped("amount_total")) - sum(pieces.mapped("amount_residual")),
                2),
            "total_remaining_amount": round(sum(pieces.mapped("amount_residual")), 2),
            "unbilled_lines_count": len(en_attente),
            "unbilled_amount": round(montant_attente, 2),
            "supplement_count": len(complements),
            "supplement_amount": round(
                sum(complement.amount_total for complement in complements), 2),
            "supplements": [
                {
                    "invoice_number": complement.name,
                    "invoice_state": complement.state,
                    "amount": round(complement.amount_total, 2),
                }
                for complement in complements
            ],
        }

    # ------------------------------------------------------------------
    # Ce que l'écran a le droit de proposer
    # ------------------------------------------------------------------

    @api.model
    def _actions(self, shipment):
        """Les gestes ouverts sur ce dossier, décidés ici.

        Un écran qui déduirait lui-même la suite finirait par promettre une
        action que le serveur refuse. La liste sort du serveur, l'écran
        l'affiche — et elle ne contient que des gestes qu'un écran sait
        exécuter aujourd'hui.

        Ni la projection ni la facturation n'entrent dans cette décision : les
        conditions se relisent sur le dossier, en base, au moment de répondre.
        """
        capacites = self.env.user._dally_ops_capabilities()
        actions = []

        # Le colis tardif : réservé au dossier déjà facturé, dont la pièce est
        # comptabilisée. Tant qu'elle est brouillon, le bon geste reste de la
        # réinitialiser, et Freight le refuserait de toute façon.
        # La consolidation doit aussi être ouverte : `add_late_line` l'exige, et
        # annoncer l'action sans elle promettrait un geste que l'API refuse
        # aussitôt par `consolidation_not_open`. Le prédicat est celui du
        # service de ligne, pas une copie.
        if (
            shipment.billing_locked
            and shipment.sudo().invoice_id
            and shipment.sudo().invoice_id.state == "posted"
            and capacites.get("intake_create")
            and self.env["dally.ops.intake.line.service"].consolidation_est_ouverte(
                shipment)
        ):
            actions.append("add_late_package")

        # Deux gestes attendus ne sont pas publiés, et pour la même raison.
        #
        # `prepare_supplement` : aucun écran ne sait encore l'exécuter.
        # `resync_sheet` : aucune route ne l'expose — la relance d'une
        # projection est une mutation, et la surface mutante de l'API Ops
        # attend d'abord sa protection inter-origine.
        #
        # Annoncer une action que l'opérateur ne peut pas déclencher est pire
        # que ne rien annoncer : l'écran promettrait un bouton qui échoue, ou
        # pire, n'existe pas. Les deux reviendront avec ce qui les exécute.

        return actions
