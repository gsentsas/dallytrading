# -*- coding: utf-8 -*-
"""Consulter un dossier, y ajouter un article, en corriger un.

## Ce que ce service ajoute à l'étape 7

Un dossier n'a plus une ligne mais plusieurs, et elles se corrigent. Trois
difficultés en découlent, et chacune a sa réponse ici.

**Deux téléphones sur le même dossier.** Chaque article porte une `revision`
opaque — l'empreinte de ses valeurs actuelles. Une correction annonce celle
qu'elle a lue ; si elle ne correspond plus, on refuse plutôt que d'écraser le
travail de l'autre.

**La projection dans la consolidation.** `dally.freight.consolidation.line`
stocke des *instantanés* : quantité, poids et volume chargés au moment du
rattachement. Corriger le colis sans reconstruire cette projection laisserait
la consolidation croire qu'elle transporte 4 cartons de 80 kg alors qu'il y en
a 3 de 63. On détache donc, on corrige, on rattache — dans une seule
transaction.

**La facturation.** Dès qu'un dossier est engagé, Dally Ops refuse toute
mutation, y compris celles que le moteur Freight tolérerait encore. Un
libellé corrigé après émission d'une facture est une divergence entre le papier
et la base.

## L'ordre qui compte

Le rejeu est vérifié **avant** le verrou de facturation. Une correction peut
avoir réussi, la facture être créée ensuite, et le téléphone rejouer sa demande
après une coupure : il doit relire son résultat, pas se heurter à un verrou
apparu depuis. L'inverse transformerait une réussite en échec pour cause de
mauvais réseau.
"""

import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .ops_errors import DallyOpsConflict, DallyOpsError, DallyOpsInternal, DallyOpsNotFound

#: Les états d'un dossier où le terrain peut encore corriger.
ETATS_MODIFIABLES = frozenset({"goods_received", "preparing"})

#: Les champs dont la modification change ce que la consolidation transporte.
CHAMPS_PHYSIQUES = ("quantity", "exact_weight_kg", "length_cm", "width_cm", "height_cm")

#: Les clés acceptées à la racine d'une demande d'ajout.
CHAMPS_AJOUT = frozenset({"request_uuid", "line"})

#: Idem pour une correction, qui annonce en plus la version qu'elle a lue.
CHAMPS_CORRECTION = frozenset({"request_uuid", "expected_revision", "line"})

# Les valeurs qu'une correction métier doit conserver. Les champs calculés de
# tarification et les identités techniques sont volontairement exclus : le
# journal raconte ce que l'opérateur a corrigé, pas les effets internes du
# moteur.
CHAMPS_AUDIT_CORRECTION = (
    "description", "goods_category", "package_type", "quantity",
    "announced_weight_kg", "exact_weight_kg", "length_cm", "width_cm",
    "height_cm", "billing_method", "tariff_family_code", "customs_value_xof",
)


class DallyOpsIntakeLineService(models.AbstractModel):
    _name = "dally.ops.intake.line.service"
    _description = "Dally Ops — articles d'une réception"

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    @api.model
    def get_intake(self, reference):
        """Le dossier et ses articles, tels que le comptoir en a besoin."""
        self._exiger_role_ops()
        shipment = self._resoudre_dossier(reference)
        return {"intake": self._detail(shipment)}

    # ------------------------------------------------------------------
    # Ajout
    # ------------------------------------------------------------------

    @api.model
    def add_line(self, reference, payload):
        """Ajoute un article au dossier, sans jamais en créer un second.

        La clé source du dossier et sa consolidation prévue sont réutilisées
        telles quelles : le moteur Freight retrouve le dossier existant et lui
        attache un colis de plus. Aucune séquence n'est consommée, `A001` reste
        `A001`.
        """
        self._exiger_role_ops()
        if not isinstance(payload, dict) or set(payload) != CHAMPS_AJOUT:
            raise DallyOpsError(_("Demande d'ajout invalide."))

        request_uuid = self._service_intake()._uuid(
            payload.get("request_uuid"), "request_uuid")
        ligne = self._service_intake().valider_ligne(payload.get("line") or {})

        shipment = self._resoudre_dossier(reference)
        empreinte = self._empreinte({
            "operation": "add", "intake": reference, "line": ligne,
        })

        with self.env.cr.savepoint():
            self._verrouiller("ops-intake-line-request:%s" % request_uuid)
            rejeu = self._rejeu(request_uuid, empreinte)
            if rejeu is not None:
                return rejeu

            self._exiger_mutable(shipment)
            consolidation = self._consolidation_ouverte(shipment)

            # Une même référence de ligne ne peut désigner deux articles.
            if self._colis_par_uuid(shipment, ligne["line_uuid"]):
                raise DallyOpsConflict(
                    _("Cet article existe déjà dans ce dossier."),
                    code="line_reference_conflict",
                )

            resultat, _dossier = self._appeler_freight(shipment, consolidation, [ligne])
            colis = self._colis_par_uuid(shipment, ligne["line_uuid"])
            if not colis:
                raise DallyOpsInternal(_("L'article n'a pas été enregistré."))
            self._verifier_pricing(resultat)
            self._verifier_projection(colis, consolidation)

            dto = {"status": "added", "intake": self._detail(shipment),
                   "line": self._ligne(colis, ligne["line_uuid"])}
            self._inscrire(request_uuid, "add", empreinte, shipment, colis,
                           ligne["line_uuid"], dto)
            self._journaliser("intake_line_added", colis, request_uuid)
            self.env["dally.ops.sheet.outbox"].enqueue_dossier(colis.shipment_id)
            return dto

    # ------------------------------------------------------------------
    # Correction
    # ------------------------------------------------------------------

    @api.model
    def update_line(self, reference, line_uuid, payload):
        """Corrige un article, et remet la consolidation d'accord avec lui."""
        self._exiger_role_ops()
        if not isinstance(payload, dict) or set(payload) != CHAMPS_CORRECTION:
            raise DallyOpsError(_("Demande de correction invalide."))

        Intake = self._service_intake()
        request_uuid = Intake._uuid(payload.get("request_uuid"), "request_uuid")
        line_uuid = Intake._uuid(line_uuid, "line_uuid")
        revision_attendue = payload.get("expected_revision")
        if not isinstance(revision_attendue, str) or not revision_attendue:
            raise DallyOpsError(_("Version d'article manquante."))
        ligne = Intake.valider_ligne(payload.get("line") or {})
        if ligne["line_uuid"] != line_uuid:
            # La référence vient du chemin ; le corps ne peut pas la contredire.
            raise DallyOpsError(_("Référence d'article incohérente."))

        shipment = self._resoudre_dossier(reference)
        empreinte = self._empreinte({
            "operation": "update", "intake": reference, "line": ligne,
            "expected_revision": revision_attendue,
        })

        with self.env.cr.savepoint():
            self._verrouiller("ops-intake-line-request:%s" % request_uuid)
            rejeu = self._rejeu(request_uuid, empreinte)
            if rejeu is not None:
                return rejeu

            self._exiger_mutable(shipment)
            consolidation = self._consolidation_ouverte(shipment)

            colis = self._colis_par_uuid(shipment, line_uuid)
            if not colis:
                raise DallyOpsNotFound(
                    _("Article introuvable dans ce dossier."), code="line_not_found")

            # Le verrou du moteur Freight, et non un mécanisme parallèle : deux
            # corrections du même colis se sérialisent comme le reste.
            self.env["dally.freight.consolidation.line"]._lock_package(
                self.env.cr, colis.id)
            colis.invalidate_recordset()

            actuelle = self._revision(colis)
            if actuelle != revision_attendue:
                raise DallyOpsConflict(
                    _("Cet article a été modifié depuis son affichage. "
                      "Rechargez le dossier avant de poursuivre."),
                    code="stale_line",
                )

            avant = self._ligne(colis, line_uuid)

            physique = self._change_le_physique(colis, ligne)
            projection = self.env["dally.freight.consolidation.line"].sudo().search([
                ("consolidation_id", "=", consolidation.id),
                ("package_id", "=", colis.id),
            ])
            if physique and projection:
                # Écrire la nouvelle quantité pendant que l'ancienne est encore
                # déclarée chargée serait refusé par la garde du modèle. On
                # détache, on corrige, on rattache — dans cette transaction.
                projection.unlink()

            resultat, _dossier = self._appeler_freight(shipment, consolidation, [ligne])
            colis.invalidate_recordset()
            self._verifier_pricing(resultat)

            if physique:
                shipment.sudo()._add_available_packages_to_consolidation(consolidation)
            self._verifier_projection(colis, consolidation)

            apres = self._ligne(colis, line_uuid)
            dto = {"status": "updated", "intake": self._detail(shipment),
                   "line": apres}
            self._inscrire(request_uuid, "update", empreinte, shipment, colis,
                           line_uuid, dto)
            self._journaliser(
                "intake_line_updated", colis, request_uuid,
                changes=self._changements(avant, apres))
            self.env["dally.ops.sheet.outbox"].enqueue_dossier(colis.shipment_id)
            return dto

    # ------------------------------------------------------------------
    # Autorisation et résolution
    # ------------------------------------------------------------------

    @api.model
    def _exiger_role_ops(self):
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))

    @api.model
    def _service_intake(self):
        return self.env["dally.ops.intake.service"]

    @api.model
    def _verrouiller(self, cle):
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [cle])

    @api.model
    def _resoudre_dossier(self, reference):
        """Le dossier désigné par sa référence métier, et lui seul.

        Le domaine est imposé ici : société de l'opérateur, dossier né de Dally
        Ops, rattaché à une consolidation d'entrée. Un dossier d'une autre
        société ou d'une autre origine répond comme un dossier inexistant.
        """
        if not isinstance(reference, str) or not reference.strip():
            raise DallyOpsNotFound(_("Dossier introuvable."), code="intake_not_found")
        shipment = self.env["dally.shipment"].sudo().search(
            self._domaine_dossier_ops() + [
                ("external_reference", "=", reference.strip()),
            ], limit=1)
        if not shipment:
            raise DallyOpsNotFound(_("Dossier introuvable."), code="intake_not_found")
        return shipment

    @api.model
    def _domaine_dossier_ops(self):
        """Ce qui rend un dossier lisible par la fiche Ops, et rien d'autre.

        Extrait de `_resoudre_dossier` pour que la recherche puisse annoncer si
        un dossier trouvé s'ouvrira — sans recopier la règle. Deux formulations
        de la même condition divergeraient au premier changement, et la
        recherche promettrait alors une fiche que la fiche refuserait.

        La référence n'y figure pas : c'est le critère d'identification, pas le
        critère d'appartenance.
        """
        return [
            ("company_id", "=", self.env.company.id),
            ("sync_source", "=", "backoffice"),
            ("sync_source_key", "=like", "ops:%"),
            ("intake_consolidation_id", "!=", False),
        ]

    @api.model
    def _consolidation_ouverte(self, shipment):
        consolidation = shipment.intake_consolidation_id
        if (
            not consolidation
            or consolidation.company_id != self.env.company
            or not consolidation.active
            or consolidation.state != "collecting"
            or consolidation.transport_mode not in ("air", "sea")
        ):
            raise DallyOpsConflict(
                _("Cette consolidation n'est plus ouverte à la réception."),
                code="consolidation_not_open",
            )
        return consolidation

    @api.model
    def _exiger_mutable(self, shipment):
        """Les trois raisons de refuser une mutation, dans l'ordre du métier."""
        motif = self._motif_de_blocage(shipment)
        if motif == "billing_locked":
            raise DallyOpsConflict(
                _("Ce dossier est déjà engagé dans la facturation. "
                  "Les articles ne peuvent plus être modifiés."),
                code="billing_locked",
            )
        if motif == "intake_not_editable":
            raise DallyOpsConflict(
                _("Ce dossier n'est plus modifiable."), code="intake_not_editable")
        if motif == "consolidation_not_open":
            raise DallyOpsConflict(
                _("Cette consolidation n'est plus ouverte à la réception."),
                code="consolidation_not_open",
            )

    @api.model
    def _motif_de_blocage(self, shipment):
        """Pourquoi ce dossier n'est pas modifiable, ou `None`.

        Le frontend lit ce motif ; il ne réinvente pas la règle.
        """
        if shipment.billing_locked:
            return "billing_locked"
        if shipment.state not in ETATS_MODIFIABLES:
            return "intake_not_editable"
        consolidation = shipment.intake_consolidation_id
        if (
            not consolidation
            or consolidation.company_id != self.env.company
            or not consolidation.active
            or consolidation.state != "collecting"
            or consolidation.transport_mode not in ("air", "sea")
        ):
            return "consolidation_not_open"
        return None

    # ------------------------------------------------------------------
    # Identité des articles
    # ------------------------------------------------------------------

    @staticmethod
    def _cle_ligne(shipment, line_uuid):
        """`ops:<uuid dossier>:line:<uuid article>`.

        Le format existe depuis l'étape 7 ; le réutiliser évite une table de
        correspondance de plus. Il enferme aussi l'article dans son dossier :
        une référence de ligne d'un autre dossier ne compose pas la même clé.
        """
        return "%s:line:%s" % (shipment.sync_source_key, line_uuid)

    @api.model
    def _colis_par_uuid(self, shipment, line_uuid):
        cle = self._cle_ligne(shipment, line_uuid)
        colis = shipment.sudo().package_ids.filtered(
            lambda paquet: paquet.external_line_key == cle)
        return colis[:1]

    # ------------------------------------------------------------------
    # Version opaque
    # ------------------------------------------------------------------

    @api.model
    def _revision(self, colis):
        """L'empreinte des valeurs qui font l'article.

        Calculée, non stockée : une colonne de plus se désynchroniserait le
        jour où un champ serait modifié ailleurs. Tout ce qui change
        fonctionnellement l'article entre dans l'empreinte, y compris le
        résultat de tarification — corriger une famille sans que la version
        bouge laisserait passer une écriture aveugle.
        """
        instantane = {
            "description": colis.description or "",
            "goods_category": colis.goods_category or "",
            "package_type": colis.package_type or "",
            "quantity": colis.quantity,
            "unit_weight_kg": round(colis.unit_weight_kg or 0.0, 6),
            "unit_volume_cbm": round(colis.unit_volume_cbm or 0.0, 6),
            "length_cm": round(colis.length_cm or 0.0, 4),
            "width_cm": round(colis.width_cm or 0.0, 4),
            "height_cm": round(colis.height_cm or 0.0, 4),
            "announced_weight_kg": round(colis.announced_weight_kg or 0.0, 4),
            "billing_method": colis.billing_method or "",
            "tariff_family": colis.tariff_family_id.code or "",
            "customs_value_xof": round(colis.customs_value_xof or 0.0, 4),
            "applied_unit_price_eur": round(colis.applied_unit_price_eur or 0.0, 6),
        }
        return hashlib.sha256(
            json.dumps(instantane, sort_keys=True, ensure_ascii=False).encode("utf-8"),
        ).hexdigest()

    @api.model
    def _change_le_physique(self, colis, ligne):
        """Cette correction change-t-elle ce que la consolidation transporte ?

        Seuls la quantité, le poids et les dimensions déplacent des kilos et
        des mètres cubes. Corriger un libellé ne justifie pas de détacher puis
        rattacher une projection.
        """
        actuel = {
            "quantity": colis.quantity,
            "exact_weight_kg": round(colis.total_weight_kg or 0.0, 6),
            "length_cm": colis.length_cm or None,
            "width_cm": colis.width_cm or None,
            "height_cm": colis.height_cm or None,
        }
        demande = {
            "quantity": ligne["quantity"],
            "exact_weight_kg": round(ligne["exact_weight_kg"] or 0.0, 6),
            "length_cm": ligne["length_cm"],
            "width_cm": ligne["width_cm"],
            "height_cm": ligne["height_cm"],
        }
        for champ in CHAMPS_PHYSIQUES:
            gauche, droite = actuel[champ], demande[champ]
            if gauche is None and droite is None:
                continue
            if gauche is None or droite is None:
                return True
            if isinstance(gauche, float) or isinstance(droite, float):
                if abs(float(gauche) - float(droite)) > 1e-6:
                    return True
            elif gauche != droite:
                return True
        return False

    # ------------------------------------------------------------------
    # Le moteur Freight
    # ------------------------------------------------------------------

    @api.model
    def _appeler_freight(self, shipment, consolidation, lignes):
        """La charge est construite ici, à partir du dossier existant.

        La clé source et la consolidation prévue sont celles du dossier : le
        moteur le retrouve au lieu d'en créer un. Aucun bloc client, aucune
        route venue d'ailleurs, aucun prix manuel.
        """
        Intake = self._service_intake()
        charge = {
            "sync_source_key": shipment.sync_source_key,
            "planned_consolidation_ref": consolidation.name,
            "transport_mode": consolidation.transport_mode,
            "direction": consolidation.direction,
            "source": "backoffice",
            "partner_id": shipment.partner_id.id,
            "origin": Intake._route(consolidation, "origin"),
            "destination": Intake._route(consolidation, "destination"),
            "lines": [{
                "external_line_key": self._cle_ligne(shipment, ligne["line_uuid"]),
                "package_type": ligne["package_type"],
                "goods_category": ligne["goods_category"],
                "description": ligne["description"],
                "quantity": ligne["quantity"],
                "announced_weight_kg": ligne["announced_weight_kg"],
                "exact_weight_kg": ligne["exact_weight_kg"],
                "length_cm": ligne["length_cm"],
                "width_cm": ligne["width_cm"],
                "height_cm": ligne["height_cm"],
                "billing_method": ligne["billing_method"],
                "tariff_family_code": ligne["tariff_family_code"],
                "customs_value_xof": ligne["customs_value_xof"],
            } for ligne in lignes],
        }
        Moteur = (self.env["dally.freight.sync.service"]
                  .sudo()
                  .with_company(self.env.company)
                  .with_context(default_user_id=False))
        try:
            return Moteur.upsert(charge)
        except DallyOpsError:
            raise
        except Exception as erreur:
            raise DallyOpsInternal(_("L'article n'a pas pu être enregistré.")) from erreur

    @api.model
    def _verifier_pricing(self, resultat):
        for ligne in resultat.get("lines") or []:
            statut = ligne.get("pricing_status")
            if statut not in ("automatic", "manual_required", "quote"):
                raise DallyOpsInternal(
                    _("Résultat de tarification incohérent."),
                    code="pricing_inconsistency",
                )

    @api.model
    def _verifier_projection(self, colis, consolidation):
        """La consolidation dit-elle la même chose que le colis ?

        C'est le contrôle qui donne son sens au détachement : sans lui, une
        correction pourrait laisser un instantané périmé et personne ne le
        saurait avant le chargement.
        """
        colis.invalidate_recordset()
        projection = self.env["dally.freight.consolidation.line"].sudo().search([
            ("consolidation_id", "=", consolidation.id),
            ("package_id", "=", colis.id),
        ])
        if len(projection) != 1:
            raise DallyOpsInternal(_("Projection de consolidation incohérente."))
        ecarts = (
            projection.quantity_loaded != colis.quantity
            or abs(projection.weight_loaded - colis.total_weight_kg) > 1e-6
            or abs(projection.volume_loaded - colis.total_volume_cbm) > 1e-6
            or colis.available_quantity != 0
        )
        if ecarts:
            raise DallyOpsInternal(_("Projection de consolidation incohérente."))

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
        ligne = self.env["dally.ops.intake.line.request"].sudo().search([
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
        self._journaliser("intake_line_request_replayed", ligne.package_id, request_uuid)
        dto = json.loads(ligne.result_snapshot)
        dto["intake"]["customer"] = {
            "name": ligne.shipment_id.sudo().partner_id.name or "",
        }
        return dto

    @api.model
    def _inscrire(self, request_uuid, operation, empreinte, shipment, colis, line_uuid, dto):
        self.env["dally.ops.intake.line.request"].sudo().create({
            "request_uuid": request_uuid,
            "company_id": self.env.company.id,
            "operation": operation,
            "payload_hash": empreinte,
            "shipment_id": shipment.id,
            "package_id": colis.id,
            "line_uuid": line_uuid,
            # Le nom du client a sa place dans la réponse, pas dans une
            # table de plus : on le retire de l'instantané et on le remet au
            # moment de rejouer.
            "result_snapshot": json.dumps(
                self._sans_client(dto), ensure_ascii=False),
            "operator_user_id": self.env.uid,
        })

    @staticmethod
    def _sans_client(dto):
        """Le même résultat, moins le nom du client."""
        allege = json.loads(json.dumps(dto, ensure_ascii=False))
        allege.get("intake", {}).pop("customer", None)
        return allege

    @api.model
    def _journaliser(self, action, colis, request_uuid, changes=None):
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": action,
            "entity_model": "dally.shipment.package",
            "entity_res_id": colis.id if colis else False,
            "request_uuid": request_uuid,
            "changes_json": changes or [],
            "created_at": fields.Datetime.now(),
        })

    @staticmethod
    def _changements(avant, apres):
        """Les anciennes et nouvelles valeurs réellement modifiées."""
        return [
            {"field": champ, "old_value": avant.get(champ),
             "new_value": apres.get(champ)}
            for champ in CHAMPS_AUDIT_CORRECTION
            if avant.get(champ) != apres.get(champ)
        ]

    # ------------------------------------------------------------------
    # Mise en forme
    # ------------------------------------------------------------------

    @api.model
    def _statut_pricing(self, colis):
        """L'issue de la tarification, lue sur l'article.

        On ne conclut pas sur « le prix est positif » : une règle peut
        légitimement valoir zéro, et un article gratuit n'est pas un article
        non tarifé.
        """
        if colis.billing_method == "quote":
            return "quote"
        if colis.manual_unit_price_eur:
            return "manual"
        regle = colis.tariff_rule_id
        # Le moteur laisse la règle précédente en place quand il n'en trouve
        # aucune : s'y fier ferait passer pour tarifé un article dont la
        # famille vient de changer. On exige que la règle corresponde encore.
        if (
            regle
            and regle.family_id == colis.tariff_family_id
            and regle.transport_mode == colis.shipment_id.transport_mode
        ):
            return "automatic"
        return "manual_required"

    @api.model
    def _ligne(self, colis, line_uuid):
        statut = self._statut_pricing(colis)
        tarife = statut == "automatic"
        return {
            "reference": line_uuid,
            "revision": self._revision(colis),
            "description": colis.description or "",
            "goods_category": colis.goods_category or "",
            "package_type": colis.package_type or "",
            "quantity": colis.quantity,
            "announced_weight_kg": colis.announced_weight_kg or None,
            "exact_weight_kg": colis.total_weight_kg,
            "length_cm": colis.length_cm or None,
            "width_cm": colis.width_cm or None,
            "height_cm": colis.height_cm or None,
            "volume_cbm": colis.total_volume_cbm,
            "billing_method": colis.billing_method,
            "tariff_family_code": colis.tariff_family_id.code or "",
            "customs_value_xof": colis.customs_value_xof,
            "pricing_status": statut,
            "billable_weight_kg": colis.billable_weight_kg,
            "applied_unit_price_eur": colis.applied_unit_price_eur if tarife else None,
            "transport_amount_eur": colis.transport_amount_eur if tarife else None,
        }

    @api.model
    def _detail(self, shipment):
        """Le dossier entier, articles compris.

        Le client n'y figure que par son nom : le comptoir doit reconnaître le
        dossier, il n'a pas besoin du téléphone ni de l'adresse. Cette
        projection minimale passe par un privilège ciblé et n'ouvre aucune
        lecture de `res.partner` à l'opérateur.
        """
        prefixe = "%s:line:" % shipment.sync_source_key
        colis_ops = [
            paquet for paquet in shipment.sudo().package_ids
            if (paquet.external_line_key or "").startswith(prefixe)
        ]
        lignes = [
            self._ligne(paquet, (paquet.external_line_key or "").split(":line:")[-1])
            for paquet in colis_ops
        ]

        complet = all(
            ligne["pricing_status"] == "automatic" for ligne in lignes
        ) and bool(lignes)
        motif = self._motif_de_blocage(shipment)
        # Les encaissements du dossier : le comptoir doit les voir pour ne pas
        # encaisser deux fois.
        paiements = self.env["dally.ops.payment.service"].payments_for(shipment)
        return {
            "reference": shipment.external_reference,
            "local_reference": shipment.collection_local_ref,
            "consolidation_reference": shipment.intake_consolidation_id.name,
            "state": shipment.state,
            "received_on": (
                shipment.goods_received_on.isoformat()
                if shipment.goods_received_on else None
            ),
            "customer": {"name": shipment.sudo().partner_id.name or ""},
            "editable": motif is None,
            "edit_block_reason": motif,
            # Ce que l'écran a le droit de proposer, décidé ici. Une interface
            # qui déduirait la suite elle-même promettrait un jour une action
            # que le serveur refuserait.
            "allowed_transitions": self.env[
                "dally.ops.intake.state.service"].allowed_transitions(shipment),
            "lines": lignes,
            "totals": {
                "lines_count": len(lignes),
                "weight_kg": sum(ligne["exact_weight_kg"] for ligne in lignes),
                "volume_cbm": sum(ligne["volume_cbm"] for ligne in lignes),
                # Un total partiel affiché comme un total ferait croire à un
                # prix ; tant qu'une ligne n'est pas tarifée, il n'y en a pas.
                "transport_amount_eur": (
                    sum(ligne["transport_amount_eur"] or 0.0 for ligne in lignes)
                    if complet else None
                ),
                "pricing_complete": complet,
            },
            "payments": paiements,
            # Un total par devise, jamais une conversion : additionner des
            # euros et des francs demanderait un taux, et un taux choisi ici
            # serait faux la moitié du temps.
            "payment_summary": self.env[
                "dally.ops.payment.service"].payment_summary(paiements),
        }
