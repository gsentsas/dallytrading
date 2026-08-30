# -*- coding: utf-8 -*-
"""Qui a fait quoi, et quand.

## Pourquoi ce journal est nécessaire

Les écritures Ops passent par un privilège serveur. `create_uid` porte donc le
superutilisateur, et la trace native d'Odoo répond « le système » à la question
« qui a créé cette fiche ? ». Ce n'est pas une réponse.

Ce journal conserve l'opérateur réel, celui dont la session a été présentée.

## Pourquoi il ne contient aucune donnée personnelle

Un audit sert à retrouver un geste, pas à reconstituer un fichier clients.
Recopier ici le nom, le numéro et l'adresse créerait une seconde base de
données personnelles — avec les mêmes obligations et une surveillance moindre.
On garde le modèle et l'identifiant technique de l'objet touché : de quoi
remonter à la fiche quand c'est légitime, rien de plus.
"""

import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class DallyOpsAuditEvent(models.Model):
    _name = "dally.ops.audit.event"
    _description = "Dally Ops — journal des gestes opérateur"
    _order = "created_at desc, id desc"
    _rec_name = "action"

    event_uuid = fields.Char(
        required=True, index=True, readonly=True, copy=False,
        default=lambda self: str(uuid.uuid4()))
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    operator_user_id = fields.Many2one("res.users", required=True, index=True, readonly=True)
    action = fields.Char(required=True, index=True, readonly=True)
    entity_model = fields.Char(readonly=True)
    entity_res_id = fields.Integer(readonly=True)
    request_uuid = fields.Char(index=True, readonly=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    shipment_id = fields.Many2one(
        "dally.shipment", index=True, readonly=True, ondelete="set null",
        help="Ancre dossier interne. Elle n'est jamais exposée dans le DTO public.")
    changes_json = fields.Json(
        readonly=True, default=list,
        help="Valeurs métier avant/après d'une correction, sans identifiant interne.")

    _event_uuid_unique = models.Constraint(
        "UNIQUE(event_uuid)", "Un événement d'audit ne peut être enregistré deux fois.")

    #: Le rejeu d'une même action, garanti par la base et pas seulement par le
    #: code. La lecture avant écriture de ``create`` suffit tant que les deux
    #: appels se suivent ; deux transactions concurrentes peuvent toutes deux
    #: ne rien trouver avant d'insérer. PostgreSQL laisse coexister autant de
    #: ``NULL`` qu'il le faut : les événements sans ``request_uuid`` — ceux
    #: qu'aucun geste terrain n'a demandés — ne sont pas gênés.
    #:
    #: L'action fait partie de la clé : un même envoi produit légitimement
    #: plusieurs actions distinctes, et deux opérateurs qui travaillent en même
    #: temps portent deux ``request_uuid`` différents. Une unicité plus large,
    #: du type ``UNIQUE(shipment_id, action)``, effacerait de vraies opérations.
    _replay_unique = models.Constraint(
        "UNIQUE(company_id, action, request_uuid)",
        "Cette action a déjà été journalisée pour cette demande.")

    @api.model_create_multi
    def create(self, vals_list):
        """Crée une trace une seule fois et rattache son dossier si possible.

        Les services Ops sérialisent déjà chaque ``request_uuid`` avant leur
        geste métier. Ce dernier contrôle central évite qu'un futur appelant
        journalise deux fois exactement la même action lors d'un rejeu, sans
        confondre deux opérations concurrentes portant deux UUID distincts.
        """
        resultat = self.browse()
        for valeurs_source in vals_list:
            valeurs = dict(valeurs_source)
            request_uuid = valeurs.get("request_uuid")
            action = valeurs.get("action")
            company_id = valeurs.get("company_id")
            if request_uuid and action and company_id:
                existant = self.sudo().search([
                    ("company_id", "=", company_id),
                    ("action", "=", action),
                    ("request_uuid", "=", request_uuid),
                ], limit=1)
                if existant:
                    resultat |= existant
                    continue
            if not valeurs.get("shipment_id"):
                valeurs["shipment_id"] = self._shipment_from_entity(valeurs)
            resultat |= super().create(valeurs)
        return resultat

    @api.model
    def _shipment_from_entity(self, valeurs):
        model = valeurs.get("entity_model")
        res_id = int(valeurs.get("entity_res_id") or 0)
        if not model or not res_id:
            return False
        if model == "dally.shipment":
            return res_id
        if model not in ("dally.shipment.package", "dally.freight.collection"):
            return False
        record = self.env[model].sudo().browse(res_id).exists()
        return record.shipment_id.id if record else False

    @api.constrains("company_id", "operator_user_id", "shipment_id")
    def _check_company_links(self):
        """Une ancre ou un acteur étranger ne doit jamais traverser le DTO."""
        for event in self:
            if event.company_id not in event.operator_user_id.company_ids:
                raise ValidationError("L'acteur du journal appartient à une autre société.")
            if event.shipment_id and event.shipment_id.company_id != event.company_id:
                raise ValidationError("Le dossier du journal appartient à une autre société.")

    def write(self, vals):
        """L'historique se corrige par un nouvel événement, jamais en place."""
        raise AccessError("Un événement du journal opérationnel est immuable.")

    def unlink(self):
        """Aucune purge utilisateur du journal métier n'est autorisée."""
        raise AccessError("Un événement du journal opérationnel ne peut pas être supprimé.")
