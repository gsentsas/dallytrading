# -*- coding: utf-8 -*-
"""Helpers de test partagés pour les modules fret DallyTrading.

Depuis §20 le modèle `dally.shipment` applique une garde de transition
serveur : impossible de sauter d'un état à l'autre, même via un `write()`
direct. Cette règle protège la production (une erreur d'opérateur ou un
appel RPC hors chemin sont rejetés), mais les tests unitaires qui posent
un contexte (« un dossier en `arrived`, que se passe-t-il si … ») n'ont
pas à rejouer les huit étapes intermédiaires.

Ces helpers fournissent une bascule d'état de setup, en passant le token
in-process privé du modèle (`_STATE_BYPASS_TOKEN`, non forgeable via RPC).
Ils ne sont utilisables que par du code qui peut les importer, c'est-à-dire
les tests et les scripts de migration exécutés dans le même processus.
"""

from odoo.addons.dally_freight.models.dally_shipment import _STATE_BYPASS_TOKEN


def set_shipment_state(shipment, state):
    """Écrit l'état d'un dossier en contournant la garde de transition.

    Réservé au setup de test ou aux imports historiques. Ne pas utiliser
    dans une action utilisateur : elle doit passer par `action_set_state`,
    `action_next_state` ou l'action métier appropriée.
    """
    return shipment.with_context(
        _dally_state_bypass=_STATE_BYPASS_TOKEN
    ).write({"state": state})


def create_shipment(env, values):
    """Crée un dossier en contournant la garde d'état initial du `create`.

    `create` refuse un état de départ hors `draft` / `request_received` ;
    les fixtures qui veulent instancier directement en `arrived` (par
    exemple pour tester le calcul de retard) passent par cet helper.
    """
    return env["dally.shipment"].with_context(
        _dally_state_bypass=_STATE_BYPASS_TOKEN
    ).create(values)
