# -*- coding: utf-8 -*-
"""Consigner ce qui arrive à un dossier, depuis le terrain.

## Deux journaux, et pourquoi ils ne se confondent pas

`dally.ops.audit.event` répond « quel opérateur a fait quoi dans Dally Ops ».
`dally.shipment.event` répond « qu'est-il arrivé au dossier ». Un même geste
alimente les deux, et c'est voulu : le premier est une preuve d'action, le
second un fait métier que le backoffice et — un jour, sur décision — le client
peuvent lire.

Les fusionner reviendrait à publier un journal applicatif au client, ou à
priver le backoffice de l'histoire du colis.

## Ce que le terrain n'écrit jamais

`description` est publiée verbatim dès qu'un événement devient visible. Elle
est donc composée **par le serveur**, depuis le libellé de la nature choisie.
Ce que l'opérateur tape va dans `internal_note`, que rien ne publie jamais,
quelle que soit la valeur de `visible_to_customer`.

C'est la seule disposition qui rend sûr un texte libre saisi sur un téléphone :
il n'existe aucun chemin, même futur, par lequel il atteindrait un client sans
qu'on l'ait décidé.

## Ce qu'un événement ne fait pas

Il ne change pas l'état du dossier. La dépendance existante va dans l'autre
sens — une transition engendre un événement — et l'inverser créerait un second
chemin de transition à côté de celui de l'étape 2, avec ses propres portes ou
sans aucune.

Il ne notifie pas non plus : `is_automatic=False` suffit, car
`dally_freight_notifications` ne met en file que les événements automatiques.
La garantie est structurelle, pas une vigilance à tenir.

Il ne projette rien vers le tableur : l'outbox n'est appelée que par les
services qui changent la donnée du classeur, et un événement n'en change
aucune.
"""

import hashlib
import unicodedata
import uuid as uuid_module

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .ops_errors import DallyOpsConflict, DallyOpsError, DallyOpsNotFound
from .ops_event import OPS_EVENT_KINDS

#: Les natures valides, tirées du modèle : deux listes divergeraient.
KINDS_VALIDES = frozenset(code for code, _libelle in OPS_EVENT_KINDS)

#: Le libellé serveur de chaque nature. C'est lui qui devient `description`.
LIBELLES_KIND = dict(OPS_EVENT_KINDS)

#: Les natures qui n'ont aucun sens sans un mot d'explication.
#:
#: « Anomalie constatée » sans un mot, c'est une ligne que personne ne saura
#: relire dans trois semaines. « Client contacté », en revanche, se suffit.
KINDS_NOTE_REQUISE = frozenset({"anomaly", "damage_noted", "other"})

#: Les états où un dossier accepte encore d'être documenté depuis le comptoir.
#:
#: Même frontière que les photos : au-delà du départ, le dossier ne relève plus
#: du terrain, et une note ajoutée après coup brouillerait la chronologie.
ETATS_AJOUT = ("goods_received", "preparing", "ready")

LONGUEUR_NOTE = 1000
LONGUEUR_NOTE_MINIMALE = 3

#: L'action journalisée. Elle fait partie de la clé d'idempotence de l'audit.
ACTION_AUDIT = "event_recorded"

#: Exactement ce qu'un corps de demande contient. Ni plus, ni moins.
CHAMPS_DEMANDE = frozenset({"request_uuid", "kind", "note"})

#: Ce que la liste rend au plus.
LIMITE_LISTE = 50


class DallyOpsEventService(models.AbstractModel):
    _name = "dally.ops.event.service"
    _description = "Dally Ops — événements opérationnels d'un dossier"

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    @api.model
    def list_events(self, reference):
        """Les événements **saisis** du dossier, terrain et backoffice.

        Les événements automatiques sont écartés : ils redisent une transition
        que la carte d'état montre déjà, et les mêler aux notes saisies ferait
        d'une frise volontaire un journal de machine.
        """
        self._exiger_role_ops()
        shipment = self._resoudre_dossier(reference)
        evenements = self.env["dally.shipment.event"].sudo().search([
            ("shipment_id", "=", shipment.id),
            ("is_automatic", "=", False),
        ], order="event_date desc, id desc", limit=LIMITE_LISTE)
        return {
            "events": [self._en_dto(evenement) for evenement in evenements],
            "can_add": shipment.state in ETATS_AJOUT,
            "kinds": [
                {"kind": code, "label": libelle,
                 "note_required": code in KINDS_NOTE_REQUISE}
                for code, libelle in OPS_EVENT_KINDS
            ],
        }

    # ------------------------------------------------------------------
    # Écriture
    # ------------------------------------------------------------------

    @api.model
    def create_event(self, reference, payload):
        """Consigne un fait, sans jamais faire avancer le dossier."""
        self._exiger_role_ops()
        donnees = self._valider(payload)

        with self.env.cr.savepoint():
            self._verrouiller("ops-event:%s:%s" % (
                self.env.company.id, donnees["request_uuid"]))
            shipment = self._resoudre_dossier(reference)

            intention = self._intention(
                shipment, donnees["kind"], donnees["note"])
            rejeu = self._rejeu(donnees["request_uuid"], intention)
            if rejeu is not None:
                return {"event": self._en_dto(rejeu), "replayed": True}

            # La ligne du dossier est prise avant d'en relire l'état : sans
            # cela, deux gestes simultanés photographieraient deux états
            # différents du même instant.
            self._verrouiller_dossier(shipment)
            shipment.invalidate_recordset(["state"])

            if shipment.state not in ETATS_AJOUT:
                raise DallyOpsConflict(
                    _("Ce dossier n'accepte plus d'événement."),
                    code="event_state_not_allowed")

            evenement = self.env["dally.shipment.event"].sudo().create({
                "shipment_id": shipment.id,
                # L'état au moment du geste : une photographie, pas une
                # instruction. Rien ici n'écrit `shipment.state`.
                "status": shipment.state,
                "ops_event_kind": donnees["kind"],
                # Composée par le serveur : elle est publiée verbatim le jour
                # où quelqu'un décide de publier, et ce jour-là le texte de
                # l'opérateur ne doit pas s'y trouver.
                "description": LIBELLES_KIND[donnees["kind"]],
                "internal_note": donnees["note"] or False,
                "event_date": fields.Datetime.now(),
                # Fermé, et sans porte : aucun champ de l'API ne permet de
                # changer l'un ou l'autre.
                "visible_to_customer": False,
                "is_automatic": False,
                "user_id": self.env.uid,
            })

            self.env["dally.ops.event.request"].sudo().create({
                "request_uuid": donnees["request_uuid"],
                "company_id": self.env.company.id,
                "shipment_id": shipment.id,
                "shipment_event_id": evenement.id,
                "intent_hash": intention,
                "operator_user_id": self.env.uid,
            })
            self._journaliser(evenement, shipment, donnees)
            return {"event": self._en_dto(evenement), "replayed": False}

    # ------------------------------------------------------------------
    # Portée
    # ------------------------------------------------------------------

    @api.model
    def _exiger_role_ops(self):
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))

    @api.model
    def _resoudre_dossier(self, reference):
        """Le domaine Ops natif, appelé et non recopié.

        Un dossier historique ou repris du tableur se cherche et s'affiche,
        mais rien ne s'y attache : il répond comme un dossier inexistant.
        """
        return self.env["dally.ops.intake.line.service"]._resoudre_dossier(
            reference)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @api.model
    def _valider(self, payload):
        """Ce qu'un corps contient, et rien d'autre.

        `note` peut manquer pour les natures qui se suffisent ; elle est alors
        absente du corps, pas vide. Les deux sont acceptés, et normalisés vers
        la même chose.
        """
        if not isinstance(payload, dict) or not set(payload) <= CHAMPS_DEMANDE:
            raise DallyOpsError(_("Demande d'événement invalide."))

        request_uuid = self._identifiant(payload.get("request_uuid"))

        kind = payload.get("kind")
        if kind not in KINDS_VALIDES:
            raise DallyOpsError(
                _("Cette nature d'événement n'existe pas."),
                code="event_kind_invalid", status=422)

        note = self._note(payload.get("note"), kind)
        return {"request_uuid": request_uuid, "kind": kind, "note": note}

    @staticmethod
    def _note(valeur, kind):
        """Le texte de l'opérateur, normalisé et borné.

        `NFC` plutôt que brut : deux téléphones peuvent produire deux suites
        d'octets différentes pour le même mot accentué, et l'empreinte
        d'intention en dépend — un rejeu légitime deviendrait un conflit.
        """
        if valeur is None:
            texte = ""
        elif isinstance(valeur, str):
            texte = unicodedata.normalize("NFC", valeur).strip()
        else:
            raise DallyOpsError(_("Note d'événement invalide."))

        if len(texte) > LONGUEUR_NOTE:
            raise DallyOpsError(
                _("La note dépasse la longueur autorisée."),
                code="event_note_too_long", status=422)
        if kind in KINDS_NOTE_REQUISE and len(texte) < LONGUEUR_NOTE_MINIMALE:
            raise DallyOpsError(
                _("Cette nature d'événement demande une note."),
                code="event_note_required", status=422)
        return texte

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

    @staticmethod
    def _intention(shipment, kind, note):
        brut = "event|%s|%s|%s" % (shipment.id, kind, note)
        return hashlib.sha256(brut.encode("utf-8")).hexdigest()

    @api.model
    def _rejeu(self, request_uuid, intention):
        """Le geste déjà consigné, ou `None`.

        Un identifiant recyclé sur une autre intention est un conflit : lui
        rendre en silence l'événement précédent ferait croire à l'opérateur
        qu'il a enregistré ce qu'il vient d'écrire.
        """
        precedent = self.env["dally.ops.event.request"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("request_uuid", "=", request_uuid),
        ], limit=1)
        if not precedent:
            return None
        if precedent.intent_hash != intention:
            raise DallyOpsConflict(
                _("Cette demande a déjà été traitée pour un autre événement."),
                code="idempotency_conflict")
        return precedent.shipment_event_id.sudo()

    # ------------------------------------------------------------------
    # Traces
    # ------------------------------------------------------------------

    @api.model
    def _journaliser(self, evenement, shipment, donnees):
        """Un seul événement d'audit par geste.

        `changes_json` retient la nature et l'état photographié — de quoi
        relire le geste sans rouvrir l'événement. La note n'y figure pas : elle
        vit déjà dans `internal_note`, et la recopier ferait deux endroits à
        purger le jour où quelqu'un demandera son effacement.
        """
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": ACTION_AUDIT,
            "entity_model": "dally.shipment.event",
            "entity_res_id": evenement.id,
            "shipment_id": shipment.id,
            "request_uuid": donnees["request_uuid"],
            "changes_json": [{
                "field": "ops_event_kind",
                "old_value": "",
                "new_value": donnees["kind"],
            }, {
                "field": "shipment_state",
                "old_value": shipment.state,
                "new_value": shipment.state,
            }],
            "created_at": fields.Datetime.now(),
        })

    # ------------------------------------------------------------------
    # Sortie
    # ------------------------------------------------------------------

    @api.model
    def _en_dto(self, evenement):
        """Ce que l'écran a besoin de savoir, et rien d'autre.

        Aucune clé primaire, aucune société, aucun `res_model`, aucun
        identifiant d'utilisateur : l'auteur se lit par son nom, le dossier par
        la référence que l'appelant possède déjà.

        `source` se déduit de `ops_event_kind` plutôt que d'être stocké : une
        colonne de plus se désynchroniserait le jour où un backoffice
        renseignerait la nature à la main.
        """
        etats = dict(
            self.env["dally.shipment.event"]._fields["status"]
            ._description_selection(self.env))
        kind = evenement.ops_event_kind or ""
        return {
            "kind": kind,
            "kind_label": LIBELLES_KIND.get(kind, ""),
            "description": evenement.description or "",
            "note": evenement.internal_note or "",
            "status": evenement.status or "",
            "status_label": etats.get(evenement.status, evenement.status or ""),
            "event_date": self._iso_utc(evenement.event_date),
            "recorded_by": evenement.user_id.name or "",
            "source": "ops" if kind else "backoffice",
        }

    @staticmethod
    def _iso_utc(valeur):
        if not valeur:
            return ""
        return fields.Datetime.to_datetime(valeur).isoformat(
            timespec="seconds") + "Z"
