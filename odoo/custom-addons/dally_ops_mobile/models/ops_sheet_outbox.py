# -*- coding: utf-8 -*-
"""La projection du CRM vers le classeur Freight, en attente de transport.

## Pourquoi une boîte d'envoi, et pas un appel direct

Une réception saisie au comptoir ne doit jamais échouer parce que Google est
indisponible. Appeler le transport au milieu de la transaction métier
lierait le sort du colis à celui d'un service tiers : une panne de Google
annulerait une réception qui a bel et bien eu lieu.

La transaction métier écrit donc l'objet **et** l'intention de projection, puis
valide. Le transport vient plus tard, et son échec ne défait rien.

C'est exactement la forme retenue par `dally.shipment.notification` pour les
courriels : ce fichier en reprend le principe pour un autre destinataire.

## Pourquoi une identité, et pas un instantané

La boîte d'envoi ne conserve **que l'identité** de l'objet à projeter. Le
payload est reconstruit au moment de l'envoi, depuis l'état courant d'Odoo.

Un instantané figé au moment de la saisie serait périmé dès qu'une facture
serait émise ou qu'un article serait corrigé : le classeur recevrait un état
qui n'a jamais existé. En relisant, on projette toujours ce qu'Odoo affirme
aujourd'hui — et l'ordre de traitement des événements cesse d'importer.

## Pourquoi une seule ligne par objet

La clé métier est unique par société et par type. Un rejeu de la même mutation
Ops ne crée donc pas une seconde intention : il replace la même ligne en
attente. Une projection est idempotente par construction — elle décrit un
état, pas un delta.
"""

from odoo import _, api, fields, models

#: Ce que le classeur sait recevoir, et rien d'autre.
#:
#: Les encaissements n'y figurent pas comme type propre : le classeur Freight
#: n'a pas d'onglet d'encaissements. Un paiement vit dans les colonnes de
#: paiement de la ligne de son dossier, et se projette donc **avec** lui —
#: c'est la convention d'identité existante, et en inventer une seconde
#: reviendrait à tenir deux comptabilités de lignes.
TYPES_PROJECTION = [
    ("freight_dossier", "Dossier de fret"),
    ("cash_expense", "Dépense de caisse"),
    ("cash_transfer", "Transfert de caisse"),
]

ETATS = [
    ("pending", "À projeter"),
    ("processing", "En cours de transport"),
    ("delivered", "Projetée"),
    ("retry", "À reprendre"),
    ("failed", "En échec"),
]

#: Les paliers de reprise, en minutes. Une erreur de transport se répète
#: rarement à la seconde près ; marteler n'aide personne.
PALIERS_MINUTES = (0, 2, 10, 30, 120, 360)

#: Combien de lignes un lot peut porter. Assez pour rattraper une journée,
#: assez peu pour qu'un passage d'Apps Script tienne dans son quota.
LOT_MAXIMAL = 50


class DallyOpsSheetOutbox(models.Model):
    _name = "dally.ops.sheet.outbox"
    _description = "Dally Ops — projections en attente vers le classeur Freight"
    _order = "create_date asc, id asc"
    _rec_name = "business_key"

    company_id = fields.Many2one(
        "res.company", required=True, index=True, readonly=True, ondelete="cascade")
    projection_type = fields.Selection(
        TYPES_PROJECTION, required=True, index=True, readonly=True)
    #: L'identité métier de l'objet — jamais un numéro de ligne du classeur,
    #: qui change dès qu'on trie ou qu'on insère.
    business_key = fields.Char(required=True, index=True, readonly=True)
    resource_model = fields.Char(required=True, readonly=True)
    resource_id = fields.Integer(required=True, index=True, readonly=True)
    #: La référence lisible, pour diagnostiquer sans ouvrir l'objet.
    resource_reference = fields.Char(readonly=True)

    state = fields.Selection(ETATS, required=True, default="pending", index=True)
    attempt_count = fields.Integer(default=0, readonly=True)
    next_attempt_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True, readonly=True)
    last_attempt_at = fields.Datetime(readonly=True)
    #: Le motif du dernier refus, sans donnée personnelle ni secret.
    last_error = fields.Char(readonly=True)
    delivered_at = fields.Datetime(readonly=True)

    _projection_unique = models.Constraint(
        "UNIQUE(company_id, projection_type, business_key)",
        "Cette projection est déjà inscrite pour cette société.")

    # ------------------------------------------------------------------
    # Écriture de l'intention
    # ------------------------------------------------------------------

    @api.model
    def enqueue(self, projection_type, business_key, record, reference=None):
        """Inscrit — ou réveille — l'intention de projeter cet objet.

        Appelée **dans** la transaction métier, sans aucun accès réseau. Si
        Google est en panne, cette ligne reste ; la réception, elle, est
        acquise.

        Un rejeu de la même mutation replace simplement la ligne en attente :
        une projection décrit un état, et projeter deux fois le même état est
        sans effet.
        """
        cle = (business_key or "").strip()
        if not cle or not record:
            return self.browse()
        societe = record.company_id or self.env.company
        Boite = self.sudo()
        existante = Boite.search([
            ("company_id", "=", societe.id),
            ("projection_type", "=", projection_type),
            ("business_key", "=", cle),
        ], limit=1)
        valeurs = {
            "state": "pending",
            "next_attempt_at": fields.Datetime.now(),
            "last_error": False,
            "resource_reference": reference or "",
        }
        if existante:
            # `attempt_count` n'est pas remis à zéro : l'historique des échecs
            # de transport reste lisible d'un état métier au suivant.
            existante.write(valeurs)
            return existante
        return Boite.create({
            "company_id": societe.id,
            "projection_type": projection_type,
            "business_key": cle,
            "resource_model": record._name,
            "resource_id": record.id,
            **valeurs,
        })

    @api.model
    def enqueue_dossier(self, shipment):
        """Inscrit un dossier de fret — création, article, encaissement.

        Un seul point d'entrée pour six appelants : la clé métier et la
        référence lisible s'y décident une fois. La clé est `sync_source_key`,
        premier critère de regroupement du connecteur ; la référence globale ne
        sert de repli que pour les dossiers antérieurs à cette convention.
        """
        if not shipment:
            return self.browse()
        cle = (shipment.sync_source_key or shipment.external_reference or "").strip()
        if not cle:
            return self.browse()
        return self.enqueue(
            "freight_dossier", cle, shipment,
            reference=shipment.external_reference or shipment.collection_local_ref or "")

    # ------------------------------------------------------------------
    # Lecture par le transport
    # ------------------------------------------------------------------

    @api.model
    def claim_batch(self, company, limite=LOT_MAXIMAL):
        """Réserve un lot d'intentions et rend leurs projections.

        `FOR UPDATE SKIP LOCKED` : deux transports concurrents se partagent le
        travail au lieu de se le disputer. Celui qui arrive second passe aux
        lignes suivantes plutôt que d'attendre — ou pire, de projeter deux fois
        la même.
        """
        limite = max(1, min(int(limite or LOT_MAXIMAL), LOT_MAXIMAL))
        maintenant = fields.Datetime.now()
        # La réservation passe par du SQL brut, qui ne voit pas ce que l'ORM
        # n'a pas encore écrit. Mesuré : sans ce vidage ciblé, une ligne
        # repassée en `retry` juste avant — ou dont la reprise vient d'être
        # repoussée — est resservie ou ignorée à tort.
        self.env["dally.ops.sheet.outbox"].flush_model(
            ["state", "next_attempt_at", "last_attempt_at", "company_id"])
        self.env.cr.execute(
            """
            SELECT id FROM dally_ops_sheet_outbox
             WHERE company_id = %s
               AND state IN ('pending', 'retry')
               AND next_attempt_at <= %s
             ORDER BY create_date ASC, id ASC
             LIMIT %s
               FOR UPDATE SKIP LOCKED
            """,
            [company.id, maintenant, limite],
        )
        identifiants = [ligne[0] for ligne in self.env.cr.fetchall()]
        if not identifiants:
            return []

        lignes = self.sudo().browse(identifiants)
        lignes.write({"state": "processing", "last_attempt_at": maintenant})
        projections = []
        for ligne in lignes:
            # Le compteur mesure les tentatives de **transport**, et sert à
            # espacer les reprises. Le remettre à zéro ici ferait repartir le
            # palier au minimum à chaque passage.
            ligne.attempt_count = ligne.attempt_count + 1
            projection = ligne._projection()
            if projection is None:
                # L'objet a disparu : rien à projeter, et rien à réessayer.
                ligne.write({
                    "state": "delivered",
                    "delivered_at": maintenant,
                    "last_error": "resource_missing",
                })
                continue
            projections.append(dict(projection, outbox_id=ligne.id))
        return projections

    @api.model
    def acknowledge(self, company, resultats):
        """Enregistre le verdict du transport pour chaque intention.

        Un accusé perdu se rejoue sans dommage : une ligne déjà `delivered`
        reste `delivered`, et le transport aura de toute façon refait un
        UPSERT sur la même ligne du classeur.
        """
        if not isinstance(resultats, list):
            return {"delivered": 0, "retried": 0, "failed": 0, "unknown": 0}
        compte = {"delivered": 0, "retried": 0, "failed": 0, "unknown": 0}
        maintenant = fields.Datetime.now()
        for resultat in resultats:
            if not isinstance(resultat, dict):
                compte["unknown"] += 1
                continue
            ligne = self.sudo().search([
                ("id", "=", int(resultat.get("outbox_id") or 0)),
                ("company_id", "=", company.id),
            ], limit=1)
            if not ligne:
                compte["unknown"] += 1
                continue
            if resultat.get("ok"):
                ligne.write({
                    "state": "delivered",
                    "delivered_at": maintenant,
                    "last_error": False,
                })
                compte["delivered"] += 1
                continue
            message = str(resultat.get("error") or "")[:200]
            permanent = bool(resultat.get("permanent"))
            if permanent:
                # Une projection invalide reste visible et cesse d'occuper le
                # transport ; elle n'empêche jamais les autres d'avancer.
                ligne.write({"state": "failed", "last_error": message})
                compte["failed"] += 1
                continue
            ligne.write({
                "state": "retry",
                "last_error": message,
                "next_attempt_at": self._prochaine_tentative(ligne.attempt_count),
            })
            compte["retried"] += 1
        return compte

    @api.model
    def _prochaine_tentative(self, tentatives):
        minutes = PALIERS_MINUTES[min(tentatives, len(PALIERS_MINUTES) - 1)]
        return fields.Datetime.add(fields.Datetime.now(), minutes=minutes)

    @api.model
    def release_stale(self, minutes=15):
        """Rend à la file les lignes qu'un transport a laissées en plan.

        Un Apps Script qui dépasse son quota meurt sans accuser réception. Sans
        cette reprise, sa ligne resterait `processing` pour toujours.
        """
        limite = fields.Datetime.subtract(fields.Datetime.now(), minutes=minutes)
        bloquees = self.sudo().search([
            ("state", "=", "processing"), ("last_attempt_at", "<", limite),
        ])
        bloquees.write({"state": "retry", "last_error": "transport_timeout"})
        return len(bloquees)

    # ------------------------------------------------------------------
    # La projection elle-même
    # ------------------------------------------------------------------

    def _projection(self):
        """L'état autoritaire à écrire dans le classeur, lu maintenant."""
        self.ensure_one()
        enregistrement = self.env[self.resource_model].sudo().browse(self.resource_id)
        if not enregistrement.exists():
            return None
        if self.projection_type == "freight_dossier":
            return self._projection_dossier(enregistrement)
        if self.projection_type == "cash_expense":
            return self._projection_depense(enregistrement)
        if self.projection_type == "cash_transfer":
            return self._projection_transfert(enregistrement)
        return None

    @api.model
    def _onglet(self, mode):
        """L'onglet du classeur, choisi par le mode de transport.

        Un dossier aérien ne doit jamais atterrir dans la saisie maritime : les
        deux onglets portent des tarifs différents et un rapprochement les
        additionnerait.
        """
        return {"air": "Saisie aérien", "sea": "Saisie maritime"}.get(mode or "")

    def _projection_dossier(self, shipment):
        onglet = self._onglet(shipment.transport_mode)
        if not onglet:
            return None
        return {
            "projection_type": "freight_dossier",
            "business_key": self.business_key,
            "sheet": onglet,
            # Les colonnes techniques déjà en place. Aucune n'est inventée.
            "identity": {
                "sync_source_key": shipment.sync_source_key or "",
                "global_external_reference": shipment.external_reference or "",
                "intake_consolidation_ref": (
                    shipment.intake_consolidation_id.name or ""),
                "collection_local_ref": shipment.collection_local_ref or "",
                "shipment_id": shipment.id,
                "partner_id": shipment.partner_id.id,
                "sale_order_id": shipment.sale_order_id.id or 0,
                "invoice_id": shipment.invoice_id.id or 0,
                "invoice_number": self._numero_facture(shipment),
            },
            "dossier": {
                "planned_consolidation": (
                    shipment.intake_consolidation_id.name
                    or shipment.consolidation_id.name or ""),
                "reference": shipment.collection_local_ref or "",
                "deposit_date": self._date(shipment.request_date),
                "state": shipment.state or "",
                "customer": {
                    "name": shipment.partner_id.name or "",
                    "phone": shipment.partner_id.phone or "",
                    "email": shipment.partner_id.email or "",
                    # `contact_address` : le champ calculé d'Odoo, une seule
                    # ligne pour le classeur.
                    "address": " ".join(
                        (shipment.partner_id.contact_address or "").split()),
                },
            },
            "articles": [self._article(colis) for colis in shipment.package_ids],
            "payments": self._paiements(shipment),
        }

    @staticmethod
    def _numero_facture(shipment):
        """Le numéro tel qu'il doit se lire, brouillon compris.

        Une facture non comptabilisée n'a pas de numéro définitif ; annoncer un
        vide laisserait croire qu'aucune facture n'existe.
        """
        facture = shipment.invoice_id
        if not facture:
            return ""
        if facture.state == "posted" and facture.name and facture.name != "/":
            return facture.name
        return "Brouillon"

    def _article(self, colis):
        return {
            "article_key": colis.external_line_key or "",
            "goods_category": colis.goods_category or "",
            "description": colis.description or "",
            "quantity": colis.quantity or 0,
            "length_cm": colis.length_cm or 0,
            "width_cm": colis.width_cm or 0,
            "height_cm": colis.height_cm or 0,
            "unit_volume_cbm": colis.unit_volume_cbm or 0,
            "total_volume_cbm": colis.total_volume_cbm or 0,
            "announced_weight_kg": colis.announced_weight_kg or 0,
            "exact_weight_kg": colis.total_weight_kg or 0,
            "billable_weight_kg": colis.billable_weight_kg or 0,
            "billing_method": colis.billing_method or "",
            "applied_unit_price_eur": colis.applied_unit_price_eur or 0,
            "transport_amount_eur": colis.transport_amount_eur or 0,
            # Le code de famille, jamais son libellé : c'est le connecteur qui
            # sait quel libellé le classeur affiche, et lui seul.
            "tariff_family_code": colis.tariff_family_id.code or "",
            "customs_value_xof": colis.customs_value_xof or 0,
        }

    def _paiements(self, shipment):
        """Les encaissements du dossier, portés par ses propres colonnes.

        Le classeur Freight n'a pas d'onglet d'encaissements : un paiement vit
        dans les colonnes de paiement de la ligne de son dossier, identifié par
        la clé `…|P|n` déjà en usage. Deux paiements partiels restent donc deux
        lignes distinctes, et ne se fondent jamais en une.
        """
        collections = self.env["dally.freight.collection"].sudo().search([
            ("shipment_id", "=", shipment.id),
            ("state", "!=", "cancelled"),
        ], order="payment_date asc, id asc")
        lignes = []
        for rang, collection in enumerate(collections, start=1):
            devise = collection.currency_id.name
            lignes.append({
                "payment_key": self._cle_paiement(shipment, collection, rang),
                "amount_eur": collection.amount if devise == "EUR" else 0,
                "amount_xof": collection.amount if devise == "XOF" else 0,
                "currency_code": devise,
                "payment_method": collection.source_method or "",
                "collected_by": collection.collected_by_name or "",
                "wave_reference": collection.wave_reference or "",
                "payment_date": self._date(collection.payment_date),
            })
        return lignes

    @staticmethod
    def _cle_paiement(shipment, collection, rang):
        """La clé de paiement, dans la convention du classeur.

        `<référence globale>|P|<n>` — la même que celle que le connecteur pose
        lui-même en colonne BF. Un paiement rejoué retrouve donc sa ligne au
        lieu d'en créer une seconde.
        """
        base = shipment.external_reference or shipment.sync_source_key or ""
        return "%s|P|%s" % (base, rang)

    def _projection_depense(self, depense):
        return {
            "projection_type": "cash_expense",
            "business_key": self.business_key,
            "sheet": "Dépenses",
            "expense": {
                "external_expense_key": depense.external_expense_key or "",
                "date": self._date(depense.expense_date),
                "category": depense.category or "",
                "description": depense.description or "",
                "beneficiary": depense.beneficiary or "",
                "allocations": [
                    {"actor": ligne.actor_name or "", "amount": ligne.amount or 0}
                    for ligne in depense.allocation_ids
                ],
                "total_amount": depense.total_amount or 0,
                "currency_code": depense.currency_id.name or "",
                "payment_method": depense.payment_method or "",
                "reference": depense.reference or "",
                "state": depense.state or "",
                "comment": depense.comment or "",
                # Facultatif de bout en bout : les lignes historiques du
                # tableur n'ont pas de départ, et n'en auront jamais.
                "consolidation_reference": (
                    depense.consolidation_id.name if depense.consolidation_id else ""),
                "odoo_id": depense.id,
            },
        }

    def _projection_transfert(self, transfert):
        return {
            "projection_type": "cash_transfer",
            "business_key": self.business_key,
            "sheet": "Transferts caisse",
            "transfer": {
                "external_transfer_key": transfert.external_transfer_key or "",
                "date": self._date(transfert.transfer_date),
                "from_actor": transfert.from_actor or "",
                "to_actor": transfert.to_actor or "",
                "amount": transfert.amount or 0,
                "currency_code": transfert.currency_id.name or "",
                "reason": transfert.reason or "",
                "payment_method": transfert.payment_method or "",
                "state": transfert.state or "",
                "comment": transfert.comment or "",
                "odoo_id": transfert.id,
            },
        }

    @staticmethod
    def _date(valeur):
        return valeur.isoformat() if valeur else ""
