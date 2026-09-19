# -*- coding: utf-8 -*-
"""Verdict comptable lisible d'un encaissement Ops.

L'encaissement et sa comptabilisation sont deux faits différents : le client
peut avoir payé alors que la pièce comptable n'est pas encore prête, qu'un
canal manque, ou qu'une facture historique est déjà soldée. Ce module garde
cette distinction côté serveur et n'expose jamais le message technique brut au
téléphone.
"""

CHANNEL_MARKERS = (
    "no payment channel is configured",
    "aucun canal de paiement n'est configuré",
    "aucun canal de paiement n’est configuré",
)

ALREADY_PAID_MARKERS = (
    "nothing left to pay",
    "plus rien à payer",
)


def accounting_status(collection):
    """Retourne le statut métier de comptabilisation d'une collecte."""
    if collection.state == "registered":
        return "registered"

    invoice = collection.target_invoice_id or collection.invoice_id
    message = (collection.error_message or "").casefold()

    # Une facture déjà soldée est la cause la plus structurante : même en
    # configurant ensuite un canal manquant, on ne doit pas créer un second
    # paiement natif sur une pièce dont le résiduel est déjà nul.
    if _invoice_is_paid(invoice) or any(
        marker in message for marker in ALREADY_PAID_MARKERS
    ):
        return "invoice_already_paid_review"

    if any(marker in message for marker in CHANNEL_MARKERS):
        return "channel_setup_required"

    # Une vraie erreur comptable inconnue reste une erreur, même si la facture
    # n'existe pas encore. La reclasser en simple attente masquerait le blocage.
    if collection.state == "error":
        return "needs_review"

    # Pas de facture ou pièce encore brouillon : l'argent est enregistré, mais
    # la comptabilité native doit attendre que la facture existe et soit postée.
    if not invoice or invoice.state != "posted":
        return "awaiting_invoice"

    # Cas comptable non classé : on conserve un verdict explicite de revue au
    # lieu de faire croire que l'encaissement est seulement en attente.
    return "needs_review"


def _invoice_is_paid(invoice):
    if not invoice or invoice.state != "posted":
        return False
    if invoice.payment_state == "paid":
        return True
    currency = invoice.currency_id
    return bool(currency and currency.is_zero(invoice.amount_residual))
