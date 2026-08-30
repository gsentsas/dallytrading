# -*- coding: utf-8 -*-
"""Encaisser au comptoir, sans jamais perdre l'argent reçu.

## La propriété qui commande tout le reste

Le client a payé. À partir de cet instant, l'encaissement existe — que la
facture soit émise ou non, que le canal soit correctement paramétré ou non.
Le moteur `dally.freight.collection` tient déjà cette règle : une défaillance
de configuration n'annule pas la collecte, elle se dépose sur
l'enregistrement. Ce service ne la réécrit pas, il s'appuie dessus et traduit
son verdict en trois mots que le terrain comprend.

## Pourquoi Ops n'appelle pas la route Freight

`POST /api/v1/freight/payment` sert le connecteur tableur : clé d'API, portée
`freight:payment`, groupe technique, et des identifiants Odoo dans sa réponse.
La brancher ici remettrait un secret dans l'application terrain et exposerait
au navigateur ce que six étapes ont consisté à lui cacher. On réutilise le
**moteur**, pas le point d'entrée.

## Pourquoi Ops exige un canal configuré

Le modèle accepte historiquement n'importe quel `source_method`, parce que le
tableur pouvait contenir de l'ancien. Dally Ops est une interface neuve et
contrôlée : accepter « wvae » ou « cashh » reviendrait à fabriquer
volontairement des erreurs comptables permanentes. Le couple méthode/devise
doit désigner un canal actif de la société, sans quoi la demande est refusée
avant d'atteindre le moteur.
"""

import hashlib
import json

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .ops_errors import DallyOpsConflict, DallyOpsError, DallyOpsInternal, DallyOpsNotFound

#: Les seules clés acceptées dans une demande d'encaissement.
CHAMPS_PAIEMENT = frozenset({
    "request_uuid", "amount", "payment_date", "payment_method", "currency_code",
})

#: Ce que le navigateur ne décide jamais.
CHAMPS_INTERDITS = frozenset({
    "collected_by", "collected_by_id", "collected_by_name", "collector", "actor",
    "source", "external_payment_key", "shipment_id", "partner_id", "invoice_id",
    "collection_id", "account_payment_id", "journal_id", "currency_id", "company_id",
})

#: L'état de la comptabilisation, tel que le comptoir a besoin de le lire.
STATUT_COMPTABLE = {
    "registered": "registered",
    "pending": "pending",
    "error": "needs_review",
}


class DallyOpsPaymentService(models.AbstractModel):
    _name = "dally.ops.payment.service"
    _description = "Dally Ops — encaissements client"

    # ------------------------------------------------------------------
    # Canaux
    # ------------------------------------------------------------------

    @api.model
    def list_payment_channels(self):
        """Les canaux réellement configurés, réduits à ce qui se choisit.

        Ni journal, ni ligne de méthode de paiement, ni compte : la
        configuration comptable de DallyTrading n'a rien à faire sur un
        téléphone d'entrepôt, et elle intéresserait un concurrent autant qu'un
        curieux.
        """
        self._exiger_role_ops()
        canaux = self.env["dally.freight.payment.channel"].sudo().search([
            ("active", "=", True),
            ("company_id", "=", self.env.company.id),
        ], order="name, id")
        return [{
            "code": canal.code,
            "name": canal.name,
            "currency_code": canal.currency_id.name,
        } for canal in canaux]

    # ------------------------------------------------------------------
    # Encaissement
    # ------------------------------------------------------------------

    @api.model
    def record_payment(self, reference, payload):
        """Enregistre un encaissement, et dit ce que la comptabilité en a fait.

        La réponse est un succès dès lors que l'argent est enregistré. Ce que
        la comptabilité a pu ou non faire ensuite se lit dans
        `accounting_status` — jamais dans un code d'erreur HTTP, qui ferait
        croire au logisticien qu'il doit recommencer.
        """
        self._exiger_role_ops()
        donnees = self._valider(payload)
        shipment = self._resoudre_dossier(reference)

        if shipment.state == "cancelled":
            raise DallyOpsConflict(
                _("Ce dossier est annulé."), code="intake_cancelled")

        empreinte = self._empreinte({
            "intake": shipment.external_reference,
            "amount": donnees["amount"],
            "payment_date": donnees["payment_date"],
            "payment_method": donnees["payment_method"],
            "currency_code": donnees["currency_code"],
        })

        with self.env.cr.savepoint():
            self._verrouiller("ops-payment-request:%s" % donnees["request_uuid"])
            rejeu = self._rejeu(donnees["request_uuid"], empreinte)
            if rejeu is not None:
                return rejeu

            canal = self._resoudre_canal(
                donnees["payment_method"], donnees["currency_code"])
            acteur = self._acteur_de_caisse()

            collection = self._appeler_le_moteur(shipment, canal, acteur, donnees)
            dto = {
                "status": "created",
                "payment": self._en_dto(collection, donnees["request_uuid"]),
            }
            self._inscrire(donnees["request_uuid"], empreinte, shipment, collection, dto)
            self._journaliser("payment_recorded", collection, donnees["request_uuid"])
            # Un encaissement vit dans les colonnes de paiement de la ligne de
            # son dossier : c'est donc le dossier qu'on reprojette.
            self.env["dally.ops.sheet.outbox"].enqueue_dossier(shipment)
            return dto

    # ------------------------------------------------------------------
    # Lecture pour le dossier
    # ------------------------------------------------------------------

    @api.model
    def payments_for(self, shipment):
        """Les encaissements du dossier, pour éviter de payer deux fois.

        Les collectes annulées sont écartées : elles ne racontent plus rien
        d'utile au comptoir. Celles venues du tableur sont incluses — le
        logisticien doit voir ce qui a déjà été encaissé, quelle qu'en soit
        l'origine — mais avec le même DTO minimal que les autres.
        """
        collections = self.env["dally.freight.collection"].sudo().search([
            ("shipment_id", "=", shipment.id),
            ("state", "!=", "cancelled"),
        ], order="payment_date desc, id desc")
        return [self._en_dto(collection) for collection in collections]

    @api.model
    def payment_summary(self, paiements):
        """Un total par devise, et rien de plus.

        Additionner des euros et des francs demanderait un taux, et un taux
        choisi ici serait faux la moitié du temps. Tant que la facturation
        n'aura pas dit ce qui est dû, Ops se contente de compter ce qui est
        entré, devise par devise.
        """
        totaux = {}
        for paiement in paiements:
            devise = paiement["currency_code"]
            totaux[devise] = totaux.get(devise, 0.0) + paiement["amount"]
        return [
            {"currency_code": devise, "amount": montant}
            for devise, montant in sorted(totaux.items())
        ]

    # ------------------------------------------------------------------
    # Autorisation et résolution
    # ------------------------------------------------------------------

    @api.model
    def _exiger_role_ops(self):
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))

    @api.model
    def _verrouiller(self, cle):
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [cle])

    @api.model
    def _resoudre_dossier(self, reference):
        """Le même domaine imposé qu'aux étapes 7 et 8."""
        if not isinstance(reference, str) or not reference.strip():
            raise DallyOpsNotFound(_("Dossier introuvable."), code="intake_not_found")
        shipment = self.env["dally.shipment"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("external_reference", "=", reference.strip()),
            ("sync_source", "=", "backoffice"),
            ("sync_source_key", "=like", "ops:%"),
            ("intake_consolidation_id", "!=", False),
        ], limit=1)
        if not shipment:
            raise DallyOpsNotFound(_("Dossier introuvable."), code="intake_not_found")
        return shipment

    @api.model
    def _resoudre_canal(self, methode, devise):
        """Le canal désigné par le couple méthode/devise, ou un refus.

        Refuser ici plutôt que de laisser passer évite de transformer une
        faute de frappe en écriture comptable définitive.
        """
        canal = self.env["dally.freight.payment.channel"].sudo().search([
            ("active", "=", True),
            ("company_id", "=", self.env.company.id),
            ("code", "=", methode),
            ("currency_id.name", "=", devise),
        ], limit=1)
        if not canal:
            raise DallyOpsError(
                _("Ce mode de paiement n'est pas disponible dans cette devise."),
                code="payment_channel_not_available", status=422,
            )
        return canal

    @api.model
    def _acteur_de_caisse(self):
        """L'acteur de caisse de l'opérateur, jamais son nom d'affichage.

        Le rapprochement par `display_name` a été écarté dès l'étape 2 : un
        utilisateur renommé, un homonyme, un accent, et la caisse d'un collègue
        se retrouve créditée. La correspondance est explicite, configurée une
        fois, et son absence arrête l'opération.
        """
        try:
            return self.env.user._dally_ops_actor()
        except UserError:
            raise DallyOpsConflict(
                _("Votre compte n'est pas encore configuré pour les encaissements."),
                code="cash_actor_not_configured",
            )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @api.model
    def _valider(self, payload):
        if not isinstance(payload, dict):
            raise DallyOpsError(_("Demande d'encaissement invalide."))
        inconnus = set(payload) - CHAMPS_PAIEMENT
        if inconnus:
            if inconnus & CHAMPS_INTERDITS:
                raise DallyOpsError(_("Champ réservé au serveur."))
            raise DallyOpsError(_("Champ non pris en charge dans la demande."))
        if set(payload) != CHAMPS_PAIEMENT:
            raise DallyOpsError(_("Un champ obligatoire est manquant."))

        request_uuid = self.env["dally.ops.intake.service"]._uuid(
            payload.get("request_uuid"), "request_uuid")

        montant = payload.get("amount")
        if (
            isinstance(montant, bool)
            or not isinstance(montant, (int, float))
            or montant <= 0
        ):
            raise DallyOpsError(_("Le montant doit être strictement positif."))

        methode = payload.get("payment_method")
        devise = payload.get("currency_code")
        for valeur, nom in ((methode, "payment_method"), (devise, "currency_code")):
            if not isinstance(valeur, str) or not valeur.strip():
                raise DallyOpsError(_("Champ obligatoire manquant : %s.", nom))

        return {
            "request_uuid": request_uuid,
            "amount": float(montant),
            "payment_date": self._date_de_paiement(payload.get("payment_date")),
            "payment_method": methode.strip(),
            "currency_code": devise.strip().upper(),
        }

    @api.model
    def _date_de_paiement(self, valeur):
        """La date où l'argent a changé de mains.

        Une date passée est légitime — la file d'attente hors ligne enverra un
        jour des encaissements saisis plusieurs heures plus tôt. Une date
        future ne l'est pas : l'argent n'est pas encore là.
        """
        if not isinstance(valeur, str) or not valeur.strip():
            raise DallyOpsError(
                _("Date de paiement invalide."), code="invalid_payment_date", status=422)
        try:
            date = fields.Date.to_date(valeur.strip())
        except (TypeError, ValueError):
            date = False
        if not date or date.isoformat() != valeur.strip():
            raise DallyOpsError(
                _("Date de paiement invalide."), code="invalid_payment_date", status=422)
        if date > fields.Date.context_today(self):
            raise DallyOpsError(
                _("La date de paiement ne peut pas être dans le futur."),
                code="invalid_payment_date", status=422,
            )
        return date.isoformat()

    # ------------------------------------------------------------------
    # Le moteur
    # ------------------------------------------------------------------

    @api.model
    def _appeler_le_moteur(self, shipment, canal, acteur, donnees):
        """La charge est construite ici ; le navigateur n'en fournit rien.

        `collected_by_id` reste vide : il exige un utilisateur interne, et le
        compte Ops ne l'est pas. L'acteur métier stable passe par
        `collected_by_name`, qui est précisément le contrat retenu depuis
        l'étape 2.
        """
        valeurs = {
            "external_payment_key": "ops:%s" % donnees["request_uuid"],
            "shipment_id": shipment.id,
            "amount": donnees["amount"],
            "currency_id": canal.currency_id.id,
            "payment_date": donnees["payment_date"],
            "source_method": canal.code,
            "source": "backoffice",
            "collected_by_name": acteur,
        }
        # Un environnement superutilisateur **explicite**, et non `.sudo()`.
        #
        # Mesuré : avec `.sudo()`, qui garde l'identité de l'opérateur et se
        # contente de lever les contrôles, l'assistant d'enregistrement de
        # paiement d'Odoo finit par refuser l'écriture sur `account.payment`.
        # L'encaissement était conservé — la propriété tient — mais il
        # s'arrêtait en « à vérifier » alors que tout était correctement
        # configuré. Le moteur a été écrit pour être appelé par une identité
        # technique ; on lui en donne une.
        Moteur = (self.env(user=SUPERUSER_ID, su=True)["dally.freight.collection"]
                  .with_company(self.env.company))
        try:
            collection, _cree = Moteur.upsert_from_sync(valeurs)
        except DallyOpsError:
            raise
        except Exception as erreur:
            raise DallyOpsInternal(
                _("L'encaissement n'a pas pu être enregistré.")) from erreur
        if not collection:
            raise DallyOpsInternal(_("L'encaissement n'a pas pu être enregistré."))
        return collection

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
    def _rejeu(self, request_uuid, empreinte):
        """Le résultat déjà obtenu, sans repasser par la comptabilité."""
        ligne = self.env["dally.ops.payment.request"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("request_uuid", "=", request_uuid),
        ], limit=1)
        if not ligne:
            return None
        if ligne.payload_hash != empreinte:
            raise DallyOpsConflict(
                _("Cette demande a déjà été traitée avec des informations différentes."),
                code="idempotency_conflict",
            )
        self._journaliser(
            "payment_request_replayed", ligne.collection_id, request_uuid)
        dto = json.loads(ligne.result_snapshot)
        dto["status"] = "replayed"
        return dto

    @api.model
    def _inscrire(self, request_uuid, empreinte, shipment, collection, dto):
        self.env["dally.ops.payment.request"].sudo().create({
            "request_uuid": request_uuid,
            "company_id": self.env.company.id,
            "payload_hash": empreinte,
            "shipment_id": shipment.id,
            "collection_id": collection.id,
            "result_snapshot": json.dumps(dto, ensure_ascii=False),
            "operator_user_id": self.env.uid,
        })

    @api.model
    def _journaliser(self, action, collection, request_uuid):
        """Le geste et son auteur. Le montant vit déjà dans la collecte."""
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": action,
            "entity_model": "dally.freight.collection",
            "entity_res_id": collection.id if collection else False,
            "request_uuid": request_uuid,
            "created_at": fields.Datetime.now(),
        })

    # ------------------------------------------------------------------
    # Mise en forme
    # ------------------------------------------------------------------

    @api.model
    def _en_dto(self, collection, reference=None):
        """Ce que le comptoir lit d'un encaissement.

        `error_message` n'y figure pas : il décrit une configuration comptable,
        parle de journaux et de comptes, et ne dit rien d'actionnable à un
        logisticien. Le statut suffit à savoir s'il faut appeler un
        responsable.
        """
        canal = self.env["dally.freight.payment.channel"].sudo().search([
            ("company_id", "=", collection.company_id.id),
            ("code", "=", collection.source_method),
            ("currency_id", "=", collection.currency_id.id),
        ], limit=1)
        return {
            "reference": reference or self._reference_publique(collection),
            "amount": collection.amount,
            "currency_code": collection.currency_id.name,
            "payment_date": collection.payment_date.isoformat(),
            "payment_method": {
                "code": collection.source_method,
                "name": canal.name or collection.source_method,
            },
            "collector": collection.collected_by_name or "",
            "accounting_status": STATUT_COMPTABLE.get(collection.state, "needs_review"),
        }

    @staticmethod
    def _reference_publique(collection):
        """Une référence opaque, sans le préfixe interne.

        `ops:` est un détail d'implémentation du namespace des clés métier ;
        le rendre au navigateur inviterait à le composer soi-même.
        """
        cle = collection.external_payment_key or ""
        return cle[len("ops:"):] if cle.startswith("ops:") else cle
