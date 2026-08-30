# -*- coding: utf-8 -*-
"""Les dépenses engagées sur un départ, et leurs justificatifs.

## Deux gestes, jamais un seul

La dépense d'abord, la photo ensuite. C'est délibéré : dans un entrepôt, le
réseau lâche pendant l'envoi d'une image bien plus souvent que pendant l'envoi
de trois lignes de texte. Si les deux ne faisaient qu'un, une coupure au
mauvais moment effacerait l'argent déjà sorti de la caisse. Ici, une photo qui
échoue laisse la dépense intacte et se reprend plus tard.

## Pourquoi Ops exige un départ alors que le modèle ne l'exige pas

Les dépenses venues du tableur n'ont pas de consolidation et n'en auront
jamais ; rendre le champ obligatoire dans le modèle casserait ces flux. Mais
une dépense saisie au terrain sans départ serait inexploitable — on ne saurait
pas sur quoi l'imputer. La règle appartient donc à cette interface, et c'est
ici qu'elle s'applique.

## Pourquoi une liste blanche de modes de paiement

`dally.cash.expense.payment_method` est un `Char` libre, parce que le tableur
pouvait contenir n'importe quoi. Les canaux de `dally.freight.payment.channel`
ne conviennent pas : ils portent journaux et lignes de méthode, et servent aux
encaissements clients qui produisent des `account.payment`. Une dépense n'en
produit pas. On borne donc côté Ops, avec une liste courte et explicite, pour
ne pas fabriquer « wvae » depuis une interface neuve.
"""

import hashlib
import json
import os
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .ops_cash_vocabulary import MODES_PAIEMENT
from .ops_errors import DallyOpsConflict, DallyOpsError, DallyOpsInternal, DallyOpsNotFound

#: Les seules clés acceptées dans une demande de dépense.
CHAMPS_DEPENSE = frozenset({
    "request_uuid", "consolidation_reference", "expense_date", "category",
    "description", "beneficiary", "amount", "currency_code", "payment_method",
    "comment",
})

#: Ce que le serveur décide seul.
CHAMPS_INTERDITS = frozenset({
    "external_expense_key", "company_id", "consolidation_id", "source", "state",
    "allocations", "actor", "actor_name", "paid_by", "payeur",
    "total_eur_snapshot", "total_xof_snapshot", "attachment_id",
    "receipt_attachment_id", "res_model", "res_id", "expense_id",
})

#: Les modes de paiement se partagent avec les transferts : voir
#: `ops_cash_vocabulary`. Deux listes finiraient par diverger.

#: Les états d'un départ sur lequel une dépense peut survenir.
#:
#: Plus large que la réception de colis : on paie une manutention pendant la
#: collecte, mais aussi un dédouanement après le départ et un stockage à
#: l'arrivée. `draft` est exclu — rien n'a encore commencé ; `cancelled` et
#: `closed` aussi — plus rien ne s'y impute.
ETATS_DEPART = ("collecting", "collection_closed", "ready", "departed", "arrived")

#: Ce qu'un appareil photo de terrain produit, reconnu à ses octets.
SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)

#: Dix mébioctets : une photo de ticket au téléphone en fait deux ou trois.
TAILLE_MAXIMALE = 10 * 1024 * 1024

LONGUEUR_TEXTE = 200
LONGUEUR_COMMENTAIRE = 2000


class DallyOpsExpenseService(models.AbstractModel):
    _name = "dally.ops.expense.service"
    _description = "Dally Ops — dépenses de consolidation"

    # ------------------------------------------------------------------
    # Départs éligibles
    # ------------------------------------------------------------------

    @api.model
    def list_expense_consolidations(self):
        """Les départs sur lesquels une dépense peut être imputée."""
        self._exiger_role_ops()
        departs = self.env["dally.freight.consolidation"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("active", "=", True),
            ("state", "in", list(ETATS_DEPART)),
            ("transport_mode", "in", ["air", "sea"]),
        ], order="collection_close_on desc, name")
        return [self._en_dto_depart(depart) for depart in departs]

    @staticmethod
    def _en_dto_depart(depart):
        return {
            "reference": depart.name,
            "transport_mode": depart.transport_mode,
            "state": depart.state,
            "origin": {
                "city": depart.origin_city or "",
                "location": depart.origin_location or "",
            },
            "destination": {
                "city": depart.destination_city or "",
                "location": depart.destination_location or "",
            },
        }

    # ------------------------------------------------------------------
    # Création
    # ------------------------------------------------------------------

    @api.model
    def record_expense(self, payload):
        """Enregistre une dépense de terrain sur un départ."""
        self._exiger_role_ops()
        donnees = self._valider(payload)

        empreinte = self._empreinte({
            cle: donnees[cle] for cle in (
                "consolidation_reference", "expense_date", "category", "description",
                "beneficiary", "amount", "currency_code", "payment_method", "comment")
        })

        with self.env.cr.savepoint():
            self._verrouiller("ops-expense-request:%s" % donnees["request_uuid"])
            rejeu = self._rejeu(donnees["request_uuid"], empreinte)
            if rejeu is not None:
                return rejeu

            depart = self._resoudre_depart(donnees["consolidation_reference"])
            devise = self._resoudre_devise(donnees["currency_code"])
            acteur = self._acteur_de_caisse()

            depense = self._appeler_le_moteur(donnees, depart, devise, acteur)
            dto = {
                "status": "created",
                "expense": self._en_dto(depense, donnees["request_uuid"]),
            }
            self._inscrire(donnees["request_uuid"], empreinte, depense, dto)
            self._journaliser("expense_recorded", depense, donnees["request_uuid"])
            self.env["dally.ops.sheet.outbox"].enqueue(
                "cash_expense", depense.external_expense_key, depense,
                reference=depense.description or "")
            return dto

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    @api.model
    def list_expenses(self, reference):
        """Les dépenses d'un départ, et leur total par devise."""
        self._exiger_role_ops()
        depart = self._resoudre_depart(reference, pour_lecture=True)
        depenses = self.env["dally.cash.expense"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("consolidation_id", "=", depart.id),
            ("state", "!=", "cancelled"),
        ], order="expense_date desc, id desc")

        lignes = [self._en_dto(depense) for depense in depenses]
        return {
            "consolidation_reference": depart.name,
            "expenses": lignes,
            # Un total par devise. Convertir demanderait un taux, et un taux
            # choisi ici serait faux la moitié du temps.
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

    # ------------------------------------------------------------------
    # Justificatif
    # ------------------------------------------------------------------

    @api.model
    def attach_receipt(self, expense_reference, request_uuid, filename, content):
        """Joint une preuve à une dépense déjà enregistrée.

        Séparé de la création, et sans effet sur elle : une photo refusée ou
        perdue ne remet jamais en cause l'argent sorti de la caisse.
        """
        self._exiger_role_ops()
        Intake = self.env["dally.ops.intake.service"]
        request_uuid = Intake._uuid(request_uuid, "request_uuid")

        if not isinstance(content, (bytes, bytearray)) or not content:
            raise DallyOpsError(_("Justificatif vide."), code="receipt_empty", status=422)
        if len(content) > TAILLE_MAXIMALE:
            raise DallyOpsError(
                _("Le justificatif dépasse la taille autorisée."),
                code="receipt_too_large", status=422)

        empreinte = hashlib.sha256(bytes(content)).hexdigest()

        with self.env.cr.savepoint():
            self._verrouiller("ops-expense-receipt:%s" % request_uuid)
            depense = self._resoudre_depense(expense_reference)

            precedent = self.env["dally.ops.expense.receipt.request"].sudo().search([
                ("company_id", "=", self.env.company.id),
                ("request_uuid", "=", request_uuid),
            ], limit=1)
            if precedent:
                if precedent.content_hash != empreinte:
                    raise DallyOpsConflict(
                        _("Ce justificatif a déjà été envoyé avec un autre fichier."),
                        code="idempotency_conflict")
                self._journaliser(
                    "expense_receipt_request_replayed", depense, request_uuid)
                return {"status": "replayed",
                        "expense": self._en_dto(depense, expense_reference)}

            if depense.receipt_attachment_id:
                # Remplacer une preuve en silence effacerait la précédente sans
                # que personne ne l'ait décidé.
                raise DallyOpsConflict(
                    _("Cette dépense possède déjà un justificatif."),
                    code="receipt_already_attached")

            mimetype = self._type_reel(bytes(content))
            piece = self.env["ir.attachment"].sudo().create({
                "name": self._nom_sur(filename, mimetype),
                "raw": bytes(content),
                "mimetype": mimetype,
                "res_model": "dally.cash.expense",
                "res_id": depense.id,
                "company_id": self.env.company.id,
                # Jamais servi par l'URL publique d'Odoo : une preuve de caisse
                # n'a pas à être atteignable sans session.
                "public": False,
            })
            depense.write({"receipt_attachment_id": piece.id})

            self.env["dally.ops.expense.receipt.request"].sudo().create({
                "request_uuid": request_uuid,
                "company_id": self.env.company.id,
                "expense_id": depense.id,
                "attachment_id": piece.id,
                "content_hash": empreinte,
                "operator_user_id": self.env.uid,
            })
            self._journaliser("expense_receipt_attached", depense, request_uuid)
            return {"status": "attached",
                    "expense": self._en_dto(depense, expense_reference)}

    @staticmethod
    def _type_reel(content):
        """Le type déduit des **octets**, jamais du nom de fichier.

        C'est la règle déjà retenue ailleurs dans ce dépôt : un envoyeur choisit
        son extension et son en-tête, il ne choisit pas ses premiers octets.
        WebP se reconnaît à `RIFF....WEBP`, HEIC à sa boîte `ftyp`.
        """
        for signature, mimetype in SIGNATURES:
            if content.startswith(signature):
                return mimetype
        if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "image/webp"
        if content[4:8] == b"ftyp" and content[8:12] in (
                b"heic", b"heix", b"hevc", b"mif1", b"heim", b"heis"):
            return "image/heic"
        raise DallyOpsError(
            _("Ce type de fichier n'est pas accepté comme justificatif."),
            code="receipt_type_not_allowed", status=422)

    @staticmethod
    def _nom_sur(filename, mimetype):
        """Un nom de stockage, jamais un chemin venu du client.

        On ne garde que le dernier segment, on retire tout ce qui n'est pas une
        lettre, un chiffre, un tiret ou un point, et on impose l'extension du
        type réellement détecté.
        """
        base = os.path.basename((filename or "").replace("\\", "/")).strip()
        base = re.sub(r"[^A-Za-z0-9._-]", "", base) or "justificatif"
        base = re.sub(r"\.+", ".", base).lstrip(".")[:80] or "justificatif"
        extension = {
            "image/jpeg": ".jpg", "image/png": ".png",
            "image/webp": ".webp", "image/heic": ".heic",
        }[mimetype]
        racine = base.rsplit(".", 1)[0] or "justificatif"
        return "%s%s" % (racine, extension)

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
    def _resoudre_depart(self, reference, pour_lecture=False):
        if not isinstance(reference, str) or not reference.strip():
            raise DallyOpsNotFound(_("Départ introuvable."), code="consolidation_not_found")
        domaine = [
            ("company_id", "=", self.env.company.id),
            ("name", "=", reference.strip()),
            ("active", "=", True),
            ("transport_mode", "in", ["air", "sea"]),
        ]
        if not pour_lecture:
            domaine.append(("state", "in", list(ETATS_DEPART)))
        depart = self.env["dally.freight.consolidation"].sudo().search(domaine, limit=1)
        if not depart:
            raise DallyOpsNotFound(_("Départ introuvable."), code="consolidation_not_found")
        return depart

    @api.model
    def _resoudre_depense(self, reference):
        """La dépense désignée par sa référence publique.

        La référence est l'identifiant de la demande qui l'a créée ; on la
        retrouve par le registre, ce qui garantit qu'elle vient bien de Dally
        Ops et de cette société.
        """
        if not isinstance(reference, str) or not reference.strip():
            raise DallyOpsNotFound(_("Dépense introuvable."), code="expense_not_found")
        ligne = self.env["dally.ops.expense.request"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("request_uuid", "=", reference.strip()),
        ], limit=1)
        if not ligne or not ligne.expense_id:
            raise DallyOpsNotFound(_("Dépense introuvable."), code="expense_not_found")
        return ligne.expense_id

    @api.model
    def _resoudre_devise(self, code):
        devise = self.env["res.currency"].sudo().search(
            [("name", "=", code), ("active", "=", True)], limit=1)
        if not devise:
            raise DallyOpsError(
                _("Cette devise n'est pas disponible."),
                code="currency_not_available", status=422)
        return devise

    @api.model
    def _acteur_de_caisse(self):
        """Le payeur vient de la correspondance configurée, jamais d'un nom."""
        try:
            return self.env.user._dally_ops_actor()
        except UserError:
            raise DallyOpsConflict(
                _("Votre compte n'est pas encore configuré pour les opérations de caisse."),
                code="cash_actor_not_configured")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @api.model
    def _valider(self, payload):
        if not isinstance(payload, dict):
            raise DallyOpsError(_("Demande de dépense invalide."))
        inconnus = set(payload) - CHAMPS_DEPENSE
        if inconnus:
            if inconnus & CHAMPS_INTERDITS:
                raise DallyOpsError(_("Champ réservé au serveur."))
            raise DallyOpsError(_("Champ non pris en charge dans la demande."))
        if set(payload) != CHAMPS_DEPENSE:
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
                _("Mode de paiement non pris en charge."),
                code="payment_method_not_allowed", status=422)

        beneficiaire = payload.get("beneficiary")
        commentaire = payload.get("comment")
        for valeur, nom in ((beneficiaire, "beneficiary"), (commentaire, "comment")):
            if valeur is not None and not isinstance(valeur, str):
                raise DallyOpsError(_("Champ invalide : %s.", nom))

        return {
            "request_uuid": Intake._uuid(payload.get("request_uuid"), "request_uuid"),
            "consolidation_reference": Intake._texte(
                payload.get("consolidation_reference"), "consolidation_reference", 120),
            "expense_date": self._date_de_depense(payload.get("expense_date")),
            "category": Intake._texte(payload.get("category"), "category", LONGUEUR_TEXTE),
            "description": Intake._texte(
                payload.get("description"), "description", 500),
            "beneficiary": (beneficiaire or "").strip()[:LONGUEUR_TEXTE],
            "amount": float(montant),
            "currency_code": Intake._texte(
                payload.get("currency_code"), "currency_code", 8).upper(),
            "payment_method": mode,
            "comment": (commentaire or "").strip()[:LONGUEUR_COMMENTAIRE],
        }

    @api.model
    def _date_de_depense(self, valeur):
        """La date où l'argent est sorti, pas celle de la synchronisation."""
        if not isinstance(valeur, str) or not valeur.strip():
            raise DallyOpsError(
                _("Date de dépense invalide."), code="invalid_expense_date", status=422)
        try:
            date = fields.Date.to_date(valeur.strip())
        except (TypeError, ValueError):
            date = False
        if not date or date.isoformat() != valeur.strip():
            raise DallyOpsError(
                _("Date de dépense invalide."), code="invalid_expense_date", status=422)
        if date > fields.Date.context_today(self):
            raise DallyOpsError(
                _("La date de dépense ne peut pas être dans le futur."),
                code="invalid_expense_date", status=422)
        return date.isoformat()

    # ------------------------------------------------------------------
    # Le moteur
    # ------------------------------------------------------------------

    @api.model
    def _appeler_le_moteur(self, donnees, depart, devise, acteur):
        """La charge est construite ici ; rien du corps reçu ne la traverse.

        Une seule allocation, au nom de l'acteur configuré : une dépense de
        terrain a un payeur. Le modèle partagé sait en répartir plusieurs pour
        le tableur, et cette capacité reste intacte — Ops n'en utilise qu'une.

        Les instantanés `total_eur_snapshot` et `total_xof_snapshot` ne sont pas
        renseignés : ils appartiennent au flux historique, et les inventer ici
        reviendrait à fabriquer une conversion que personne n'a calculée.
        """
        valeurs = {
            "external_expense_key": "ops:%s" % donnees["request_uuid"],
            "expense_date": donnees["expense_date"],
            "category": donnees["category"],
            "description": donnees["description"],
            "beneficiary": donnees["beneficiary"] or False,
            "currency_id": devise.id,
            "payment_method": donnees["payment_method"],
            "state": "review",
            "comment": donnees["comment"] or False,
            "source": "backoffice",
            "consolidation_id": depart.id,
        }
        allocations = [{"actor_name": acteur, "amount": donnees["amount"]}]
        Moteur = (self.env["dally.cash.expense"]
                  .sudo()
                  .with_company(self.env.company))
        try:
            depense, _cree = Moteur.upsert_from_sync(valeurs, allocations)
        except DallyOpsError:
            raise
        except Exception as erreur:
            raise DallyOpsInternal(
                _("La dépense n'a pas pu être enregistrée.")) from erreur
        return depense

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
        ligne = self.env["dally.ops.expense.request"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("request_uuid", "=", request_uuid),
        ], limit=1)
        if not ligne:
            return None
        if ligne.payload_hash != empreinte:
            raise DallyOpsConflict(
                _("Cette demande a déjà été traitée avec des informations différentes."),
                code="idempotency_conflict")
        self._journaliser("expense_request_replayed", ligne.expense_id, request_uuid)
        dto = json.loads(ligne.result_snapshot)
        dto["status"] = "replayed"
        # Le justificatif a pu être joint après coup : on relit l'état actuel.
        dto["expense"]["has_receipt"] = bool(ligne.expense_id.receipt_attachment_id)
        return dto

    @api.model
    def _inscrire(self, request_uuid, empreinte, depense, dto):
        self.env["dally.ops.expense.request"].sudo().create({
            "request_uuid": request_uuid,
            "company_id": self.env.company.id,
            "payload_hash": empreinte,
            "expense_id": depense.id,
            "result_snapshot": json.dumps(dto, ensure_ascii=False),
            "operator_user_id": self.env.uid,
        })

    @api.model
    def _journaliser(self, action, depense, request_uuid):
        """Le geste et son auteur. Le montant vit déjà dans la dépense."""
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": action,
            "entity_model": "dally.cash.expense",
            "entity_res_id": depense.id if depense else False,
            "request_uuid": request_uuid,
            "created_at": fields.Datetime.now(),
        })

    # ------------------------------------------------------------------
    # Mise en forme
    # ------------------------------------------------------------------

    @api.model
    def _en_dto(self, depense, reference=None):
        return {
            "reference": reference or self._reference_publique(depense),
            "consolidation_reference": depense.consolidation_id.name or "",
            "expense_date": depense.expense_date.isoformat(),
            "category": depense.category or "",
            "description": depense.description or "",
            "beneficiary": depense.beneficiary or "",
            "amount": depense.total_amount,
            "currency_code": depense.currency_id.name,
            "payment_method": depense.payment_method or "",
            "paid_by": ", ".join(depense.allocation_ids.mapped("actor_name")),
            "state": depense.state,
            "has_receipt": bool(depense.receipt_attachment_id),
            # Le terrain ne complète que ce que le terrain a saisi.
            #
            # Une dépense venue du tableur peut légitimement être rattachée à
            # un départ par le back-office ; elle compte alors dans le total et
            # doit s'afficher. Mais son justificatif ne se joint pas d'ici :
            # elle n'a pas de demande d'origine, donc rien à quoi rattacher
            # l'envoi. Sans ce drapeau, l'écran proposerait un bouton qui
            # échouerait.
            "can_attach_receipt": (
                not depense.receipt_attachment_id
                and (depense.external_expense_key or "").startswith("ops:")
            ),
        }

    @staticmethod
    def _reference_publique(depense):
        cle = depense.external_expense_key or ""
        return cle[len("ops:"):] if cle.startswith("ops:") else cle
