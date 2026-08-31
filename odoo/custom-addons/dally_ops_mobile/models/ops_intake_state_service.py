# -*- coding: utf-8 -*-
"""Faire avancer un dossier depuis le terrain, sans réécrire la machine à états.

## Où vit l'autorité

Dans `dally_freight` : `ALLOWED_STATE_TRANSITIONS` dit quelles transitions
existent, `_check_state_transition` les impose à chaque écriture,
`_check_ready_requirements` refuse un dossier incomplet, et
`_apply_state_side_effects` remplit les dates et inscrit l'événement de suivi.

Ce service n'en tient aucune copie. Il fait trois choses, et rien d'autre :

1. il **restreint** l'offre à ce qu'un comptoir a le droit de demander ;
2. il **vérifie** que l'écran n'agit pas sur un état périmé ;
3. il **appelle** `action_set_state`, qui reste la dernière autorité.

Une seconde matrice ici divergerait au premier changement, et le terrain se
verrait proposer une action que le serveur refuserait.

## Ce que le terrain n'a pas le droit de faire

`departed` appartient à la consolidation : le départ est collectif, atomique, et
sa porte financière — facture comptabilisée et réglée — ne se satisfait pas
depuis un téléphone. `cancelled` n'est pas un geste de comptoir. Ni l'un ni
l'autre n'entre dans `OPS_STATE_TARGETS`, donc ni l'un ni l'autre n'apparaît
jamais dans ce que l'écran reçoit.

## Ce que le privilège recouvre

Un logisticien Ops n'a pas `dally_core.group_dally_logistics`, et ne doit pas
l'obtenir : ce groupe implique `group_dally_readonly` et ouvrirait vingt-et-un
modèles à un téléphone d'entrepôt. Le privilège vit donc ici, appliqué **après**
le rôle Ops, la société, le domaine Ops, l'identifiant de demande, le verrou de
ligne et l'état attendu — dans cet ordre, et pas un autre.

## Ce qu'un rejeu ne refait pas

Le réseau d'un entrepôt coupe au mauvais moment. Le même geste renvoyé relit
l'événement d'audit déjà écrit et rend l'état courant : aucune seconde
transition, aucun second audit, aucune seconde projection. Le même identifiant
portant une **autre** intention est refusé — lui rendre en silence le résultat
du premier ferait croire à l'opérateur qu'il a enregistré ce qu'il vient de
taper.
"""

import uuid as uuid_module

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dally_freight.models.dally_shipment import (
    ALLOWED_STATE_TRANSITIONS,
    SHIPMENT_STATES,
)

from .ops_errors import DallyOpsConflict, DallyOpsError

#: Les seuls états qu'un opérateur de terrain peut demander.
#:
#: Ce n'est pas une matrice : c'est un filtre posé sur celle de Freight. Le
#: départ reste à la consolidation, l'annulation au back-office.
OPS_STATE_TARGETS = ("preparing", "ready")

#: L'action journalisée. Elle fait partie de la clé d'idempotence.
ACTION_AUDIT = "intake_state_advanced"

#: Exactement ce qu'un corps de demande contient. Ni plus, ni moins.
CHAMPS_DEMANDE = frozenset({"request_uuid", "expected_state", "target_state"})


class DallyOpsIntakeStateService(models.AbstractModel):
    _name = "dally.ops.intake.state.service"
    _description = "Dally Ops — avancement d'état d'un dossier"

    # ------------------------------------------------------------------
    # Ce que le serveur propose
    # ------------------------------------------------------------------

    @api.model
    def allowed_transitions(self, shipment):
        """Les cibles Ops réellement accessibles depuis l'état courant.

        L'intersection, dans cet ordre : ce que Freight autorise depuis cet
        état, restreint à ce qu'un comptoir peut demander. Un état sans suite
        rend une liste vide — et l'écran n'affiche alors aucun bouton.
        """
        if not shipment:
            return []
        depuis = ALLOWED_STATE_TRANSITIONS.get(shipment.state, set())
        return [cible for cible in OPS_STATE_TARGETS if cible in depuis]

    # ------------------------------------------------------------------
    # La mutation
    # ------------------------------------------------------------------

    @api.model
    def advance_state(self, reference, payload):
        """Fait avancer le dossier, ou dit précisément pourquoi il ne bouge pas."""
        self._exiger_role_ops()
        donnees = self._valider(payload)
        shipment = self._resoudre_dossier(reference)

        with self.env.cr.savepoint():
            # Le même geste renvoyé deux fois ne doit pas se croiser lui-même.
            self._verrouiller("ops-intake-state:%s:%s" % (
                self.env.company.id, donnees["request_uuid"]))

            rejeu = self._rejeu(donnees, shipment)
            if rejeu is not None:
                return rejeu

            # Deux opérateurs peuvent avoir lu le même écran. La ligne du
            # dossier est verrouillée **avant** de relire son état : sans cela,
            # les deux passeraient le contrôle et écriraient chacun leur audit.
            self._verrouiller_dossier(shipment)
            shipment.invalidate_recordset(["state"])

            if shipment.state != donnees["expected_state"]:
                raise DallyOpsConflict(
                    _("Ce dossier a changé depuis son affichage."),
                    code="state_changed",
                )

            if donnees["target_state"] not in self.allowed_transitions(shipment):
                raise DallyOpsConflict(
                    _("Cette étape n'est pas accessible depuis l'état actuel du "
                      "dossier."),
                    code="state_transition_not_allowed",
                )

            ancien = shipment.state
            try:
                # La dernière autorité : matrice, gates, dates et événement de
                # suivi sont appliqués par Freight, pas ici.
                #
                # L'entrée privée de Freight ouvre la seule barrière que le
                # terrain ne peut pas franchir — l'appartenance à
                # `group_dally_logistics`. Ce service n'a pas connaissance du
                # jeton qui la porte : il reste enfermé dans `dally_freight`.
                shipment._action_set_state_from_ops(donnees["target_state"])
            except DallyOpsError:
                raise
            except UserError as refus:
                # La gate métier a parlé : on rend son message, jamais sa pile.
                raise DallyOpsConflict(
                    self._message_lisible(refus), code="state_transition_blocked")

            self._journaliser(shipment, donnees, ancien)
            # Le classeur montre l'état du dossier : une transition doit y
            # descendre. Aucune écriture d'état ne l'inscrit toute seule.
            self.env["dally.ops.sheet.outbox"].enqueue_dossier(shipment)
            return self._en_dto("updated", shipment)

    # ------------------------------------------------------------------
    # Portée
    # ------------------------------------------------------------------

    @api.model
    def _exiger_role_ops(self):
        """Le service décide lui-même pour qui il travaille.

        Le contrôleur vérifie déjà le rôle pour choisir le code HTTP ; cette
        seconde vérification garantit que le privilège reste hors d'atteinte
        quel que soit l'appelant — un autre contrôleur, une action serveur.
        """
        if not self.env["res.users"]._dally_ops_role():
            raise DallyOpsError(
                _("Accès refusé."), code="ops_forbidden", status=403)

    @api.model
    def _resoudre_dossier(self, reference):
        """Le dossier désigné, et seulement s'il relève de Dally Ops.

        Le domaine est celui de la fiche, appelé et non recopié : un dossier
        repris du classeur se cherche et s'identifie, mais ne se mute pas.
        """
        return self.env["dally.ops.intake.line.service"]._resoudre_dossier(reference)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @api.model
    def _valider(self, payload):
        if not isinstance(payload, dict) or set(payload) != CHAMPS_DEMANDE:
            raise DallyOpsError(_("Demande de transition invalide."))

        request_uuid = self._identifiant(payload.get("request_uuid"))
        etats = dict(SHIPMENT_STATES)

        cible = payload.get("target_state")
        if cible not in OPS_STATE_TARGETS:
            raise DallyOpsConflict(
                _("Cette étape ne peut pas être demandée depuis Dally Ops."),
                code="state_target_not_allowed",
            )

        attendu = payload.get("expected_state")
        if not isinstance(attendu, str) or attendu not in etats:
            raise DallyOpsError(_("État attendu invalide."))

        return {
            "request_uuid": request_uuid,
            "expected_state": attendu,
            "target_state": cible,
        }

    @staticmethod
    def _identifiant(valeur):
        if not isinstance(valeur, str):
            raise DallyOpsError(_("Identifiant de demande invalide."))
        try:
            return str(uuid_module.UUID(valeur.strip()))
        except (ValueError, AttributeError):
            raise DallyOpsError(_("Identifiant de demande invalide."))

    # ------------------------------------------------------------------
    # Verrous
    # ------------------------------------------------------------------

    @api.model
    def _verrouiller(self, cle):
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [cle])

    @api.model
    def _verrouiller_dossier(self, shipment):
        """Sérialise les gestes concurrents sur **ce** dossier.

        Le verrou par identifiant de demande ne protège que d'un rejeu ; deux
        opérateurs portent deux identifiants différents. C'est la ligne du
        dossier qui doit être prise, et avant d'en relire l'état.
        """
        self.env.cr.execute(
            "SELECT id FROM dally_shipment WHERE id = %s FOR UPDATE",
            [shipment.id])

    # ------------------------------------------------------------------
    # Rejeu
    # ------------------------------------------------------------------

    @api.model
    def _rejeu(self, donnees, shipment):
        """Le geste déjà enregistré, ou `None`.

        L'intention est comparée en entier : même dossier, même état de départ,
        même cible. Un identifiant recyclé sur une autre intention est un
        conflit, pas un rejeu.
        """
        evenement = self.env["dally.ops.audit.event"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("action", "=", ACTION_AUDIT),
            ("request_uuid", "=", donnees["request_uuid"]),
        ], limit=1)
        if not evenement:
            return None

        attendue = self._changements(
            donnees["expected_state"], donnees["target_state"])
        if evenement.shipment_id.id != shipment.id or (
                evenement.changes_json or []) != attendue:
            raise DallyOpsConflict(
                _("Cette demande a déjà été traitée pour une autre transition."),
                code="idempotency_conflict",
            )
        return self._en_dto("replayed", shipment)

    # ------------------------------------------------------------------
    # Traces
    # ------------------------------------------------------------------

    @api.model
    def _journaliser(self, shipment, donnees, ancien):
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": ACTION_AUDIT,
            "entity_model": "dally.shipment",
            "entity_res_id": shipment.id,
            "shipment_id": shipment.id,
            "request_uuid": donnees["request_uuid"],
            "changes_json": self._changements(ancien, donnees["target_state"]),
            "created_at": fields.Datetime.now(),
        })

    @staticmethod
    def _changements(ancien, nouveau):
        return [{"field": "state", "old_value": ancien, "new_value": nouveau}]

    @staticmethod
    def _message_lisible(refus):
        """Le message métier d'un refus, sans pile ni détail technique."""
        message = getattr(refus, "args", None)
        texte = str(message[0]) if message else str(refus)
        return texte.strip() or _("Cette étape n'est pas possible pour l'instant.")

    # ------------------------------------------------------------------
    # Sortie
    # ------------------------------------------------------------------

    @api.model
    def _en_dto(self, statut, shipment):
        """Ce que l'écran a besoin de savoir, et rien d'autre."""
        return {
            "status": statut,
            "reference": shipment.external_reference or "",
            "state": shipment.state or "",
            "allowed_transitions": self.allowed_transitions(shipment),
        }
