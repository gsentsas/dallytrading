# -*- coding: utf-8 -*-
"""Remettre de la caisse, et confirmer l'avoir reçue.

## Deux actes, deux personnes

Une remise saisie par celui qui donne n'est pas une réception. Gilles sait
qu'il a sorti l'argent ; seule Dalanda sait qu'il est arrivé. Le transfert
naît donc « en attente de réception », et rien ne le fait basculer sauf un
geste du destinataire lui-même.

C'est aussi pourquoi un responsable ne confirme pas à la place de son équipe
dans ce parcours. Il en aura le pouvoir un jour, par un écran de correction
assumé, tracé et distinct. Le lui donner ici transformerait la preuve en
formalité.

## Ce que le navigateur ne choisit jamais

L'expéditeur, l'état, la source et la clé métier. L'expéditeur vient de la
correspondance de caisse du compte connecté ; le laisser au navigateur
permettrait d'imputer sa propre remise à un collègue, ce qui est exactement le
problème que cette correspondance existe pour fermer.

## Ce que cette étape ne fait pas

Aucun solde. Nous n'avons défini ni solde initial, ni périmètre, ni traitement
des corrections : un « solde Gilles » calculé ici serait un chiffre faux
affiché avec autorité. Cette étape enregistre des mouvements et s'arrête là.

Aucune conversion non plus. Un transfert porte un montant et une devise ; les
totaux se lisent par devise, jamais additionnés.
"""

import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .ops_cash_actor_service import canonique
from .ops_cash_vocabulary import DEVISES_CAISSE, LIBELLES_MODE, MODES_PAIEMENT
from .ops_errors import DallyOpsConflict, DallyOpsError, DallyOpsInternal, DallyOpsNotFound

#: Les seules clés acceptées dans une demande de transfert.
CHAMPS_TRANSFERT = frozenset({
    "request_uuid", "to_actor", "transfer_date", "amount", "currency_code",
    "payment_method", "reason", "comment",
})

#: Ce que le serveur décide seul. Nommés pour que le refus soit lisible.
CHAMPS_INTERDITS = frozenset({
    "external_transfer_key", "company_id", "from_actor", "state", "source",
    "total_eur_snapshot", "total_xof_snapshot", "acknowledged_at",
    "acknowledged_by_user_id", "user_id", "recipient_user_id", "transfer_id",
    "sender", "actor", "actor_name", "last_sync_at",
})

#: Ce que l'état du modèle devient à l'écran.
#:
#: `review` et `validated` sont les mots du flux historique du tableur. Les
#: exposer obligerait l'interface à savoir qu'une remise « à revoir » est en
#: réalité une remise en attente de son destinataire.
ETATS_PUBLICS = {
    "review": "pending_receipt",
    "validated": "received",
    # Le terrain ne peut pas annuler ; le back-office, si. Une remise annulée
    # doit se lire plutôt que disparaître de l'écran sans explication.
    "cancelled": "cancelled",
}

#: Le préfixe des transferts nés dans Dally Ops.
PREFIXE = "ops:"

LONGUEUR_MOTIF = 200
LONGUEUR_COMMENTAIRE = 2000


class DallyOpsCashTransferService(models.AbstractModel):
    _name = "dally.ops.cash.transfer.service"
    _description = "Dally Ops — transferts de caisse entre acteurs"

    # ------------------------------------------------------------------
    # Ce que l'écran a besoin de savoir avant de saisir
    # ------------------------------------------------------------------

    @api.model
    def list_options(self):
        """L'expéditeur, les destinataires, les devises et les modes."""
        self._exiger_role_ops()
        Acteurs = self.env["dally.ops.cash.actor.service"]
        return {
            "from_actor": Acteurs.current_actor(),
            # Un nom, rien d'autre : ni identifiant, ni identifiant de
            # connexion, ni adresse. Le destinataire est une identité de
            # caisse, pas une fiche d'utilisateur.
            "recipients": [{"actor": acteur} for acteur in Acteurs.available_recipients()],
            "currencies": self._devises_offertes(),
            "payment_methods": [
                {"code": code, "name": LIBELLES_MODE[code]} for code in MODES_PAIEMENT
            ],
        }

    @api.model
    def _devises_offertes(self):
        """Les devises de caisse, recoupées avec ce que la base a d'actif.

        La liste écrite dans `ops_cash_vocabulary` dit ce que la caisse
        détient ; la base dit ce qui existe. Proposer une devise désactivée
        ferait échouer la saisie après coup.
        """
        devises = self.env["res.currency"].sudo().search([
            ("name", "in", list(DEVISES_CAISSE)), ("active", "=", True),
        ])
        par_code = {devise.name: devise for devise in devises}
        return [
            {"code": code,
             "name": (par_code[code].full_name
                      or par_code[code].currency_unit_label or code)}
            for code in DEVISES_CAISSE if code in par_code
        ]

    # ------------------------------------------------------------------
    # La remise
    # ------------------------------------------------------------------

    @api.model
    def record_transfer(self, payload):
        """Enregistre une remise de caisse — en attente de son destinataire."""
        self._exiger_role_ops()
        donnees = self._valider(payload)

        Acteurs = self.env["dally.ops.cash.actor.service"]
        expediteur = Acteurs.current_actor()
        empreinte = self._empreinte(dict(donnees, from_actor=expediteur))

        with self.env.cr.savepoint():
            self._verrouiller("ops-cash-transfer-request:%s" % donnees["request_uuid"])
            rejeu = self._rejeu(donnees["request_uuid"], empreinte)
            if rejeu is not None:
                return rejeu

            destinataire = Acteurs.resolve_recipient(donnees["to_actor"])
            if canonique(destinataire) == canonique(expediteur):
                raise DallyOpsError(
                    _("On ne peut pas se remettre de la caisse à soi-même."),
                    code="same_actor", status=422)

            devise = self._resoudre_devise(donnees["currency_code"])
            transfert = self._appeler_le_moteur(
                donnees, expediteur, destinataire, devise)

            dto = {
                "status": "created",
                "transfer": self._en_dto(transfert, donnees["request_uuid"], expediteur),
            }
            self._inscrire(
                "dally.ops.cash.transfer.request",
                donnees["request_uuid"], empreinte, transfert, dto)
            self._journaliser(
                "cash_transfer_recorded", transfert, donnees["request_uuid"])
            return dto

    @api.model
    def _appeler_le_moteur(self, donnees, expediteur, destinataire, devise):
        """La charge est construite ici ; rien du corps reçu ne la traverse.

        Les instantanés `total_eur_snapshot` et `total_xof_snapshot` restent
        vides : ils appartiennent au flux historique du tableur, et les
        inventer fabriquerait une conversion que personne n'a calculée.
        """
        valeurs = {
            "external_transfer_key": "%s%s" % (PREFIXE, donnees["request_uuid"]),
            "transfer_date": donnees["transfer_date"],
            "from_actor": expediteur,
            "to_actor": destinataire,
            "amount": donnees["amount"],
            "currency_id": devise.id,
            "reason": donnees["reason"],
            "payment_method": donnees["payment_method"],
            # Jamais `validated` à la création, même si les deux acteurs sont
            # configurés : l'accusé est un acte séparé, et c'est tout l'objet
            # de cette étape.
            "state": "review",
            "source": "backoffice",
            "comment": donnees["comment"] or False,
        }
        Moteur = (self.env["dally.cash.transfer"]
                  .sudo()
                  .with_company(self.env.company))
        try:
            transfert, _cree = Moteur.upsert_from_sync(valeurs)
        except DallyOpsError:
            raise
        except Exception as erreur:
            raise DallyOpsInternal(
                _("La remise n'a pas pu être enregistrée.")) from erreur
        return transfert

    # ------------------------------------------------------------------
    # La liste
    # ------------------------------------------------------------------

    @api.model
    def list_transfers(self):
        """Les remises qui concernent l'utilisateur connecté, et elles seules.

        Restreinte aux transferts nés dans Dally Ops. Les lignes venues du
        tableur portent une référence de document (« TRF-20260822-0001 »)
        qu'aucun mécanisme ne rend sûre à exposer ni à résoudre depuis un
        téléphone ; les afficher demanderait d'inventer une identité opaque
        pour une poignée de lignes historiques. L'écran le dit plutôt que de
        laisser croire à un journal complet.
        """
        self._exiger_role_ops()
        acteur = self.env["dally.ops.cash.actor.service"].current_actor()
        transferts = self.env["dally.cash.transfer"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("external_transfer_key", "=like", "%s%%" % PREFIXE),
            "|",
            ("from_actor", "=ilike", acteur),
            ("to_actor", "=ilike", acteur),
        ], order="transfer_date desc, id desc")
        # `=ilike` compare sans casse mais pas sans espaces : on refiltre sur
        # la forme canonique, seule autorité sur « qui est qui ».
        cle = canonique(acteur)
        retenus = transferts.filtered(
            lambda t: cle in (canonique(t.from_actor), canonique(t.to_actor)))

        lignes = [self._en_dto(transfert, acteur_courant=acteur) for transfert in retenus]
        return {
            "actor": acteur,
            "transfers": lignes,
            # Un total par devise et par sens. Additionner des euros et des
            # francs demanderait un taux, et un taux choisi ici serait faux.
            "summary": self._resume(lignes),
        }

    @staticmethod
    def _resume(lignes):
        totaux = {}
        for ligne in lignes:
            if ligne["state"] == "cancelled":
                continue
            cle = (ligne["direction"], ligne["currency_code"])
            totaux[cle] = totaux.get(cle, 0.0) + ligne["amount"]
        return [
            {"direction": direction, "currency_code": devise, "amount": montant}
            for (direction, devise), montant in sorted(totaux.items())
        ]

    # ------------------------------------------------------------------
    # L'accusé de réception
    # ------------------------------------------------------------------

    @api.model
    def acknowledge(self, reference, request_uuid):
        """Le destinataire confirme avoir reçu les fonds.

        ## L'ordre compte

        Le rejeu est examiné **avant** l'état. Le scénario qui l'impose est
        banal : Dalanda confirme, le serveur écrit, la réponse se perd sur le
        réseau, le téléphone renvoie la même demande. Si l'état était vérifié
        d'abord, cette seconde tentative verrait « déjà reçu » et répondrait un
        conflit — pour une confirmation qui a parfaitement réussi.
        """
        self._exiger_role_ops()
        Intake = self.env["dally.ops.intake.service"]
        request_uuid = Intake._uuid(request_uuid, "request_uuid")
        acteur = self.env["dally.ops.cash.actor.service"].current_actor()

        with self.env.cr.savepoint():
            self._verrouiller("ops-cash-transfer-ack:%s" % request_uuid)
            transfert = self._resoudre_transfert(reference)
            empreinte = self._empreinte({
                "reference": reference, "recipient": canonique(acteur)})

            rejeu = self._rejeu(request_uuid, empreinte, ack=True)
            if rejeu is not None:
                return rejeu

            # Le verrou du transfert lui-même : deux confirmations simultanées
            # portant des identifiants différents se croiseraient sinon, et
            # produiraient deux transitions et deux traces d'audit.
            self._verrouiller(
                "ops-cash-transfer:%s:%s" % (self.env.company.id, transfert.id))
            transfert.invalidate_recordset(["state", "acknowledged_at"])

            if canonique(transfert.to_actor) != canonique(acteur):
                # 403 et non 404 : le transfert existe, c'est l'autorisation
                # qui manque. Un responsable qui n'est pas le destinataire est
                # refusé comme les autres.
                raise DallyOpsError(
                    _("Seul le destinataire peut confirmer avoir reçu les fonds."),
                    code="not_transfer_recipient", status=403)
            if transfert.state == "cancelled":
                raise DallyOpsConflict(
                    _("Cette remise a été annulée."), code="transfer_cancelled")
            if transfert.state != "review":
                raise DallyOpsConflict(
                    _("Cette remise a déjà été confirmée reçue."),
                    code="transfer_already_received")

            self._marquer_recu(transfert)
            dto = {
                "status": "acknowledged",
                "transfer": self._en_dto(transfert, acteur_courant=acteur),
            }
            self._inscrire(
                "dally.ops.cash.transfer.ack.request",
                request_uuid, empreinte, transfert, dto)
            self._journaliser("cash_transfer_received", transfert, request_uuid)
            return dto

    @api.model
    def _marquer_recu(self, transfert):
        """Le fait, et rien que le fait.

        Ni le montant, ni la devise, ni les acteurs, ni la date ne bougent :
        confirmer une réception ne corrige pas une remise. Une erreur de
        montant appellera un geste de responsable, assumé et tracé.
        """
        transfert.sudo().write({
            "state": "validated",
            "acknowledged_at": fields.Datetime.now(),
            "acknowledged_by_user_id": self.env.uid,
        })

    # ------------------------------------------------------------------
    # Résolution
    # ------------------------------------------------------------------

    @api.model
    def _resoudre_transfert(self, reference):
        """Le transfert désigné par sa référence publique.

        On passe par le registre des demandes : c'est ce qui garantit que la
        remise vient bien de Dally Ops, de cette société, et qu'aucune
        référence forgée ne désigne une ligne du tableur.
        """
        if not isinstance(reference, str) or not reference.strip():
            raise DallyOpsNotFound(_("Remise introuvable."), code="transfer_not_found")
        ligne = self.env["dally.ops.cash.transfer.request"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("request_uuid", "=", reference.strip()),
        ], limit=1)
        if not ligne or not ligne.transfer_id:
            raise DallyOpsNotFound(_("Remise introuvable."), code="transfer_not_found")
        return ligne.transfer_id

    @api.model
    def _resoudre_devise(self, code):
        if code not in DEVISES_CAISSE:
            raise DallyOpsError(
                _("Cette devise n'est pas disponible."),
                code="currency_not_available", status=422)
        devise = self.env["res.currency"].sudo().search(
            [("name", "=", code), ("active", "=", True)], limit=1)
        if not devise:
            raise DallyOpsError(
                _("Cette devise n'est pas disponible."),
                code="currency_not_available", status=422)
        return devise

    @api.model
    def _exiger_role_ops(self):
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))

    @api.model
    def _verrouiller(self, cle):
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [cle])

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @api.model
    def _valider(self, payload):
        if not isinstance(payload, dict):
            raise DallyOpsError(_("Demande de transfert invalide."))
        inconnus = set(payload) - CHAMPS_TRANSFERT
        if inconnus:
            if inconnus & CHAMPS_INTERDITS:
                raise DallyOpsError(_("Champ réservé au serveur."))
            raise DallyOpsError(_("Champ non pris en charge dans la demande."))
        if set(payload) != CHAMPS_TRANSFERT:
            raise DallyOpsError(_("Un champ obligatoire est manquant."))

        Intake = self.env["dally.ops.intake.service"]
        montant = payload.get("amount")
        if (
            isinstance(montant, bool)
            or not isinstance(montant, (int, float))
            or montant <= 0
        ):
            raise DallyOpsError(_("Le montant doit être strictement positif."))

        mode = payload.get("payment_method")
        if mode not in MODES_PAIEMENT:
            raise DallyOpsError(
                _("Mode de remise non pris en charge."),
                code="payment_method_not_allowed", status=422)

        commentaire = payload.get("comment")
        if commentaire is not None and not isinstance(commentaire, str):
            raise DallyOpsError(_("Champ invalide : comment."))

        destinataire = payload.get("to_actor")
        if not isinstance(destinataire, str) or not destinataire.strip():
            raise DallyOpsError(
                _("Ce destinataire n'est pas disponible."),
                code="cash_recipient_not_available", status=422)

        return {
            "request_uuid": Intake._uuid(payload.get("request_uuid"), "request_uuid"),
            "to_actor": destinataire.strip(),
            "transfer_date": self._date_de_remise(payload.get("transfer_date")),
            "amount": float(montant),
            "currency_code": Intake._texte(
                payload.get("currency_code"), "currency_code", 8),
            "payment_method": mode,
            # Un motif est exigé : une remise de caisse sans raison énoncée ne
            # se rapproche pas six semaines plus tard.
            "reason": Intake._texte(payload.get("reason"), "reason", LONGUEUR_MOTIF),
            "comment": (commentaire or "").strip()[:LONGUEUR_COMMENTAIRE],
        }

    @api.model
    def _date_de_remise(self, valeur):
        """Le jour où l'argent a changé de mains, pas celui de la saisie."""
        if not isinstance(valeur, str) or not valeur.strip():
            raise DallyOpsError(
                _("Date de remise invalide."), code="invalid_transfer_date", status=422)
        try:
            date = fields.Date.to_date(valeur.strip())
        except (TypeError, ValueError):
            date = False
        if not date or date.isoformat() != valeur.strip():
            raise DallyOpsError(
                _("Date de remise invalide."), code="invalid_transfer_date", status=422)
        if date > fields.Date.context_today(self):
            raise DallyOpsError(
                _("La date de remise ne peut pas être dans le futur."),
                code="invalid_transfer_date", status=422)
        return date.isoformat()

    # ------------------------------------------------------------------
    # Idempotence
    # ------------------------------------------------------------------

    @staticmethod
    def _empreinte(donnees):
        return hashlib.sha256(
            json.dumps(donnees, sort_keys=True, ensure_ascii=False, default=str)
            .encode("utf-8"),
        ).hexdigest()

    @api.model
    def _rejeu(self, request_uuid, empreinte, ack=False):
        modele = ("dally.ops.cash.transfer.ack.request" if ack
                  else "dally.ops.cash.transfer.request")
        ligne = self.env[modele].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("request_uuid", "=", request_uuid),
        ], limit=1)
        if not ligne:
            return None
        if ligne.payload_hash != empreinte:
            raise DallyOpsConflict(
                _("Cette demande a déjà été traitée avec des informations différentes."),
                code="idempotency_conflict")
        self._journaliser(
            "cash_transfer_receive_replayed" if ack else "cash_transfer_create_replayed",
            ligne.transfer_id, request_uuid)
        dto = json.loads(ligne.result_snapshot)
        dto["status"] = "replayed"
        # L'état a pu changer depuis : on relit plutôt que de resservir une
        # photographie périmée.
        dto["transfer"]["state"] = ETATS_PUBLICS.get(
            ligne.transfer_id.state, ligne.transfer_id.state)
        dto["transfer"]["acknowledged_at"] = (
            ligne.transfer_id.acknowledged_at.isoformat()
            if ligne.transfer_id.acknowledged_at else None)
        return dto

    @api.model
    def _inscrire(self, modele, request_uuid, empreinte, transfert, dto):
        self.env[modele].sudo().create({
            "request_uuid": request_uuid,
            "company_id": self.env.company.id,
            "payload_hash": empreinte,
            "transfer_id": transfert.id,
            "result_snapshot": json.dumps(dto, ensure_ascii=False),
            "operator_user_id": self.env.uid,
        })

    @api.model
    def _journaliser(self, action, transfert, request_uuid):
        """Le geste et son auteur. Le montant vit déjà dans le transfert."""
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": action,
            "entity_model": "dally.cash.transfer",
            "entity_res_id": transfert.id if transfert else False,
            "request_uuid": request_uuid,
            "created_at": fields.Datetime.now(),
        })

    # ------------------------------------------------------------------
    # Mise en forme
    # ------------------------------------------------------------------

    @api.model
    def _en_dto(self, transfert, reference=None, acteur_courant=None):
        sens = None
        if acteur_courant is not None:
            sens = ("outgoing" if canonique(transfert.from_actor) == canonique(acteur_courant)
                    else "incoming")
        dto = {
            "reference": reference or self._reference_publique(transfert),
            "transfer_date": transfert.transfer_date.isoformat(),
            "from_actor": transfert.from_actor or "",
            "to_actor": transfert.to_actor or "",
            "amount": transfert.amount,
            "currency_code": transfert.currency_id.name,
            "payment_method": transfert.payment_method or "",
            "reason": transfert.reason or "",
            "state": ETATS_PUBLICS.get(transfert.state, transfert.state),
            "acknowledged_at": (transfert.acknowledged_at.isoformat()
                                if transfert.acknowledged_at else None),
        }
        if sens is not None:
            dto["direction"] = sens
        return dto

    @staticmethod
    def _reference_publique(transfert):
        cle = transfert.external_transfer_key or ""
        return cle[len(PREFIXE):] if cle.startswith(PREFIXE) else cle
