# -*- coding: utf-8 -*-
"""Les encaissements Wave du comptoir, rattachés au dossier qui les justifie.

## Ce que cette étape ajoute, et ce qu'elle réutilise

Le moteur d'encaissement existe depuis l'étape 9 : `dally.freight.collection`
porte le dossier, et en tire le client, la facture et la société par des
relations **stockées et en lecture seule**. Rattacher le paiement d'Aissatou à
Fatou n'est donc pas interdit par une règle — c'est structurellement
impossible, puisque le client n'est jamais saisi.

Ce service n'ajoute qu'une chose : un contrat où le terrain **ne choisit ni le
moyen ni le bénéficiaire**. L'étape 9 laissait l'opérateur désigner un canal
et créditait sa propre caisse ; ici les transferts Wave arrivent tous sur le
même compte, et le serveur l'impose.

## Pourquoi le bénéficiaire n'est pas l'opérateur

Un encaissement Wave n'entre pas dans la poche de qui le saisit. Il atterrit
sur le compte Wave de la caisse Dakar, quel que soit le logisticien qui
constate la réception. Créditer l'opérateur — ce que fait, à juste titre, le
comptoir en espèces — fabriquerait ici une position de caisse fausse pour deux
personnes à la fois.

## Ce que ce service ne fait pas

Aucune intégration Wave. Il n'appelle aucune API, n'écoute aucun webhook, ne
conserve ni code, ni identifiant de connexion. L'opérateur constate un
transfert reçu sur son téléphone et l'enregistre ; le serveur ne prétend rien
vérifier auprès de Wave.

Aucune comptabilité inventée non plus. Le moteur tente l'écriture native et
dépose son verdict sur l'enregistrement ; ce service le traduit en trois mots.
Une facture existante n'est ni créée, ni postée, ni modifiée.
"""

import hashlib
import json
import re

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError

from .ops_errors import DallyOpsConflict, DallyOpsError, DallyOpsInternal, DallyOpsNotFound

#: Les seules clés acceptées dans une demande d'encaissement Wave.
CHAMPS = frozenset({
    "request_uuid", "amount", "currency", "wave_reference", "paid_at", "note",
})

#: Ce que le serveur décide seul — nommé pour que le refus soit lisible.
#:
#: `payment_method` et `beneficiary` y figurent bien qu'ils portent les bonnes
#: valeurs dans l'exemple du contrat : une donnée que le serveur impose ne doit
#: pas pouvoir être *aussi* fournie, sans quoi un client finirait par croire
#: qu'il la choisit.
CHAMPS_INTERDITS = frozenset({
    "method", "payment_method", "source_method", "beneficiary",
    "beneficiary_user_id", "collected_by", "collected_by_id",
    "collected_by_name", "collector", "actor", "partner_id", "customer_id",
    "user_id", "shipment_id", "invoice_id", "collection_id",
    "account_payment_id", "payment_id", "journal_id", "currency_id",
    "company_id", "source", "external_payment_key", "state",
})

#: Le moyen de paiement de cette étape. Une constante de service, pas une
#: donnée reçue : le canal correspondant doit exister dans la société.
MOYEN = "wave"

#: L'état de la comptabilisation, tel que le comptoir a besoin de le lire.
STATUT_COMPTABLE = {
    "registered": "registered",
    "pending": "pending",
    "error": "needs_review",
}

#: Ce qu'une référence Wave peut contenir.
#:
#: Volontairement large — Wave n'a pas publié de format stable et le refuser à
#: tort bloquerait un encaissement réel. Assez étroit tout de même pour qu'un
#: identifiant ne devienne pas un champ de texte libre.
REFERENCE_WAVE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")

LONGUEUR_NOTE = 500


class DallyOpsWavePaymentService(models.AbstractModel):
    _name = "dally.ops.wave.payment.service"
    _description = "Dally Ops — encaissements clients Wave"

    # ------------------------------------------------------------------
    # Ce que l'écran a besoin de savoir avant de saisir
    # ------------------------------------------------------------------

    @api.model
    def payment_context(self, reference):
        """Le dossier, son client et le bénéficiaire imposé.

        L'écran affiche le bénéficiaire ; il ne le propose pas. Le lui faire
        lire depuis le serveur évite qu'une interface annonce « Gilles » alors
        que le serveur crédite quelqu'un d'autre.
        """
        self._exiger_role_ops()
        shipment = self._resoudre_dossier(reference)
        beneficiaire, _compte = self._beneficiaire()
        return {
            "intake_reference": shipment.external_reference,
            "customer_name": shipment.partner_id.name or "",
            "payment_method": MOYEN,
            "beneficiary": beneficiaire,
            "currencies": self._devises_offertes(),
            "payments": self.payments_for(shipment),
        }

    @api.model
    def _devises_offertes(self):
        """Les devises dans lesquelles un canal Wave est réellement configuré.

        Proposer une devise sans canal ferait échouer la saisie après coup, au
        comptoir, devant le client.
        """
        canaux = self.env["dally.freight.payment.channel"].sudo().search([
            ("active", "=", True),
            ("company_id", "=", self.env.company.id),
            ("code", "=", MOYEN),
        ], order="id")
        return sorted({canal.currency_id.name for canal in canaux})

    # ------------------------------------------------------------------
    # L'encaissement
    # ------------------------------------------------------------------

    @api.model
    def record_wave_payment(self, reference, payload):
        """Enregistre un encaissement Wave sur un dossier existant.

        La réponse est un succès dès que l'argent est enregistré. Ce que la
        comptabilité en a fait se lit dans `accounting_status`, jamais dans un
        code d'erreur HTTP — qui ferait croire au comptoir qu'il doit
        recommencer une opération déjà réussie.
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
            "currency": donnees["currency"],
            "paid_at": donnees["paid_at"],
            "wave_reference": donnees["wave_reference"] or "",
            "note": donnees["note"],
            # Le moyen et le bénéficiaire entrent dans l'empreinte bien qu'ils
            # viennent du serveur : si la configuration change entre deux
            # tentatives, le rejeu doit être refusé plutôt que de resservir un
            # résultat qui ne correspond plus.
            "payment_method": MOYEN,
        })

        with self.env.cr.savepoint():
            self._verrouiller("ops-payment-request:%s" % donnees["request_uuid"])
            rejeu = self._rejeu(donnees["request_uuid"], empreinte)
            if rejeu is not None:
                return rejeu

            canal = self._resoudre_canal(donnees["currency"])
            beneficiaire, _compte = self._beneficiaire()
            self._verifier_reference_libre(donnees["wave_reference"])

            collection = self._appeler_le_moteur(
                shipment, canal, beneficiaire, donnees)
            dto = {
                "status": "created",
                "payment": self._en_dto(collection, donnees["request_uuid"]),
            }
            self._inscrire(
                donnees["request_uuid"], empreinte, shipment, collection, dto)
            self._journaliser(
                "wave_payment_recorded", collection, donnees["request_uuid"])
            self.env["dally.ops.sheet.outbox"].enqueue_dossier(shipment)
            return dto

    @api.model
    def _appeler_le_moteur(self, shipment, canal, beneficiaire, donnees):
        """La charge est construite ici ; le navigateur n'en fournit rien.

        `collected_by_id` reste vide : il exige un compte interne, et les
        comptes Ops ne le sont pas. Le bénéficiaire passe par
        `collected_by_name`, l'identité métier stable employée depuis
        l'étape 2.

        L'environnement superutilisateur explicite reprend le choix **mesuré**
        de l'étape 9 : avec un simple `.sudo()`, l'assistant d'enregistrement
        de paiement d'Odoo finit par refuser l'écriture sur `account.payment`,
        et l'encaissement — conservé, mais bloqué en « à vérifier » — donnait
        un faux signal au comptoir.
        """
        valeurs = {
            "external_payment_key": "ops:%s" % donnees["request_uuid"],
            "shipment_id": shipment.id,
            "amount": donnees["amount"],
            "currency_id": canal.currency_id.id,
            "payment_date": donnees["paid_at"],
            "source_method": canal.code,
            "source": "backoffice",
            "collected_by_name": beneficiaire,
            "wave_reference": donnees["wave_reference"] or False,
            "ops_note": donnees["note"] or False,
        }
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
    # Lecture
    # ------------------------------------------------------------------

    @api.model
    def payments_for(self, shipment):
        """Les encaissements du dossier, quelle qu'en soit l'origine.

        Ceux venus du tableur y figurent : le comptoir doit voir ce qui a déjà
        été payé avant de réclamer un solde. Les collectes annulées sont
        écartées — elles ne racontent plus rien d'utile.
        """
        collections = self.env["dally.freight.collection"].sudo().search([
            ("shipment_id", "=", shipment.id),
            ("state", "!=", "cancelled"),
        ], order="payment_date desc, id desc")
        lignes = [self._en_dto(collection) for collection in collections]
        return {
            "items": lignes,
            # Un total par devise. Additionner des euros et des francs
            # demanderait un taux, et un taux choisi ici serait faux.
            "summary": self._resume(lignes),
        }

    @staticmethod
    def _resume(lignes):
        totaux = {}
        for ligne in lignes:
            totaux[ligne["currency_code"]] = (
                totaux.get(ligne["currency_code"], 0.0) + ligne["amount"])
        return [
            {"currency_code": devise, "amount": montant}
            for devise, montant in sorted(totaux.items())
        ]

    @api.model
    def list_payments(self, reference):
        """Les encaissements d'un dossier désigné par son Axxx."""
        self._exiger_role_ops()
        shipment = self._resoudre_dossier(reference)
        resultat = self.payments_for(shipment)
        resultat["intake_reference"] = shipment.external_reference
        return resultat

    # ------------------------------------------------------------------
    # Résolution
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
        """Le dossier désigné par sa référence publique — son Axxx.

        Le même domaine imposé qu'aux étapes 7 à 9 : la société courante, une
        origine Dally Ops, et un dossier réellement rattaché à un départ. Une
        référence forgée ne désigne rien.
        """
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
    def _resoudre_canal(self, devise):
        """Le canal Wave de la société dans cette devise, ou un refus."""
        canal = self.env["dally.freight.payment.channel"].sudo().search([
            ("active", "=", True),
            ("company_id", "=", self.env.company.id),
            ("code", "=", MOYEN),
            ("currency_id.name", "=", devise),
        ], limit=1)
        if not canal:
            raise DallyOpsError(
                _("Wave n'est pas disponible dans cette devise."),
                code="payment_channel_not_available", status=422)
        return canal

    @api.model
    def _beneficiaire(self):
        """Le bénéficiaire opérationnel, résolu par configuration.

        Trois refus distincts, parce qu'ils appellent trois gestes différents :
        rien de configuré, une configuration ambiguë, ou un compte qui n'a rien
        d'une personne. Aucun identifiant numérique n'apparaît ici — le champ
        porte un nom d'acteur, et le service des acteurs le résout.
        """
        # `.sudo()` pour lire la configuration : `res.company` fait partie des
        # modèles fermés au compte Ops, et c'est bien ainsi — un logisticien
        # n'a pas à lire la fiche de sa société. Il n'en reste pas moins que le
        # serveur doit savoir qui il crédite.
        configure = (
            self.env.company.sudo().dally_ops_wave_beneficiary or "").strip()
        if not configure:
            raise DallyOpsConflict(
                _("Le bénéficiaire des encaissements Wave n'est pas configuré."),
                code="wave_beneficiary_not_configured")
        nom, compte = (self.env["dally.ops.cash.actor.service"]
                       .resolve_actor_user(configure))
        # Le superutilisateur n'est pas une personne : le créditer rendrait la
        # caisse inexploitable et masquerait une erreur de configuration.
        if compte.id == SUPERUSER_ID or not compte.active:
            raise DallyOpsConflict(
                _("Le bénéficiaire des encaissements Wave est mal configuré."),
                code="wave_beneficiary_not_configured")
        return nom, compte

    @api.model
    def _verifier_reference_libre(self, reference):
        """Un même transfert Wave ne paie pas deux dossiers.

        La base porte la contrainte ; ce contrôle existe pour rendre le refus
        lisible au comptoir plutôt que de laisser remonter une violation
        d'unicité en erreur serveur.
        """
        if not reference:
            return
        existante = self.env["dally.freight.collection"].sudo().search_count([
            ("company_id", "=", self.env.company.id),
            ("wave_reference", "=", reference),
        ])
        if existante:
            raise DallyOpsConflict(
                _("Cette référence Wave a déjà été enregistrée."),
                code="wave_reference_already_used")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @api.model
    def _valider(self, payload):
        if not isinstance(payload, dict):
            raise DallyOpsError(_("Demande d'encaissement invalide."))
        inconnus = set(payload) - CHAMPS
        if inconnus:
            if inconnus & CHAMPS_INTERDITS:
                raise DallyOpsError(_("Champ réservé au serveur."))
            raise DallyOpsError(_("Champ non pris en charge dans la demande."))
        if set(payload) != CHAMPS:
            raise DallyOpsError(_("Un champ obligatoire est manquant."))

        Intake = self.env["dally.ops.intake.service"]
        montant = payload.get("amount")
        if (
            isinstance(montant, bool)
            or not isinstance(montant, (int, float))
            or montant <= 0
        ):
            raise DallyOpsError(_("Le montant doit être strictement positif."))

        note = payload.get("note")
        if note is not None and not isinstance(note, str):
            raise DallyOpsError(_("Champ invalide : note."))

        return {
            "request_uuid": Intake._uuid(payload.get("request_uuid"), "request_uuid"),
            "amount": float(montant),
            "currency": Intake._texte(payload.get("currency"), "currency", 8).upper(),
            "wave_reference": self._reference_wave(payload.get("wave_reference")),
            "paid_at": self._date_encaissement(payload.get("paid_at")),
            "note": (note or "").strip()[:LONGUEUR_NOTE],
        }

    @staticmethod
    def _reference_wave(valeur):
        """La référence Wave, normalisée, ou rien.

        Vide et absente sont traitées pareil : l'encaissement a eu lieu, le
        numéro suivra peut-être. Une valeur mal formée, en revanche, est
        refusée — la recopier telle quelle rendrait l'unicité inopérante.
        """
        if valeur in (None, False, ""):
            return None
        if not isinstance(valeur, str):
            raise DallyOpsError(
                _("Référence Wave invalide."), code="invalid_wave_reference", status=422)
        nettoye = valeur.strip().replace(" ", "")
        if not nettoye:
            return None
        if not REFERENCE_WAVE.match(nettoye):
            raise DallyOpsError(
                _("Référence Wave invalide."), code="invalid_wave_reference", status=422)
        return nettoye.upper()

    @api.model
    def _date_encaissement(self, valeur):
        """Le jour où l'argent est arrivé.

        Une date, et non un horodatage : `dally.freight.collection` stocke une
        date, et prétendre conserver une heure que le modèle jette serait
        mentir sur la précision de la trace.

        Une date passée est légitime — le terrain saisit parfois plusieurs
        heures après. Une date future ne l'est pas : l'argent n'est pas là.
        """
        if not isinstance(valeur, str) or not valeur.strip():
            raise DallyOpsError(
                _("Date d'encaissement invalide."), code="invalid_paid_at", status=422)
        try:
            date = fields.Date.to_date(valeur.strip())
        except (TypeError, ValueError):
            date = False
        if not date or date.isoformat() != valeur.strip():
            raise DallyOpsError(
                _("Date d'encaissement invalide."), code="invalid_paid_at", status=422)
        if date > fields.Date.context_today(self):
            raise DallyOpsError(
                _("La date d'encaissement ne peut pas être dans le futur."),
                code="invalid_paid_at", status=422)
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
    def _rejeu(self, request_uuid, empreinte):
        """Le résultat déjà obtenu, sans repasser par la comptabilité.

        Le registre est celui de l'étape 9 : un encaissement reste un
        encaissement, quel que soit l'écran qui l'a saisi, et deux registres
        parallèles laisseraient un même identifiant produire deux lignes.
        """
        ligne = self.env["dally.ops.payment.request"].sudo().search([
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
            "wave_payment_request_replayed", ligne.collection_id, request_uuid)
        dto = json.loads(ligne.result_snapshot)
        dto["status"] = "replayed"
        # Le verdict comptable a pu évoluer depuis : on relit plutôt que de
        # resservir une photographie périmée.
        dto["payment"]["accounting_status"] = STATUT_COMPTABLE.get(
            ligne.collection_id.state, "needs_review")
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

        `error_message` n'y figure pas : il décrit une configuration
        comptable, parle de journaux et de comptes, et ne dit rien
        d'actionnable à un logisticien.
        """
        return {
            "reference": reference or self._reference_publique(collection),
            "amount": collection.amount,
            "currency_code": collection.currency_id.name,
            "paid_at": collection.payment_date.isoformat(),
            "payment_method": collection.source_method or "",
            "beneficiary": collection.collected_by_name or "",
            "wave_reference": collection.wave_reference or "",
            "note": collection.ops_note or "",
            "accounting_status": STATUT_COMPTABLE.get(collection.state, "needs_review"),
        }

    @staticmethod
    def _reference_publique(collection):
        cle = collection.external_payment_key or ""
        return cle[len("ops:"):] if cle.startswith("ops:") else cle
