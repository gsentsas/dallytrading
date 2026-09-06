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
            "allowed_actions": self._actions(shipment, projection, facturation),
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
        lignes = self.env["dally.ops.sheet.outbox"].sudo().search([
            ("resource_reference", "=", shipment.external_reference),
        ])
        if not lignes:
            return {
                "state": "absent",
                "operator_message": MESSAGE_PROJECTION["absent"](),
                "pending_count": 0,
                "failed_count": 0,
                "last_synced_at": None,
            }

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

        montant_attente = sum(
            colis.billable_weight_kg * colis.applied_unit_price_eur
            for colis in en_attente
        )
        devise = (principale.currency_id.name if principale else None) or "EUR"

        return {
            "currency": devise,
            "invoice_number": principale.name if principale else None,
            "invoice_state": principale.state if principale else "none",
            "invoice_amount": round(principale.amount_total, 2) if principale else 0.0,
            "paid_amount": round(
                principale.amount_total - principale.amount_residual, 2
            ) if principale else 0.0,
            "remaining_amount": round(
                principale.amount_residual, 2) if principale else 0.0,
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
    def _actions(self, shipment, projection, facturation):
        """Les gestes ouverts sur ce dossier, décidés ici.

        Un écran qui déduirait lui-même la suite finirait par promettre une
        action que le serveur refuse. La liste sort du serveur, l'écran
        l'affiche.
        """
        capacites = self.env.user._dally_ops_capabilities()
        actions = []

        # Le colis tardif : réservé au dossier déjà facturé, dont la pièce est
        # comptabilisée. Tant qu'elle est brouillon, le bon geste reste de la
        # réinitialiser, et Freight le refuserait de toute façon.
        if (
            shipment.billing_locked
            and shipment.sudo().invoice_id
            and shipment.sudo().invoice_id.state == "posted"
            and capacites.get("intake_create")
        ):
            actions.append("add_late_package")

        # Émettre le complément : seulement s'il y a quelque chose à facturer.
        if facturation["unbilled_lines_count"] and capacites.get("supervise"):
            actions.append("prepare_supplement")

        # Relancer la projection : un geste de responsable, et seulement quand
        # la projection est effectivement en peine.
        if projection["state"] in ("failed", "retry") and capacites.get("supervise"):
            actions.append("resync_sheet")

        return actions
