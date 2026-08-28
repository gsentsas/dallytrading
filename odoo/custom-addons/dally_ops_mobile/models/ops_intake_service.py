# -*- coding: utf-8 -*-
"""Adaptateur étroit entre Dally Ops et le moteur Freight existant."""

import hashlib
import json
import math
import uuid as uuid_module

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .ops_errors import DallyOpsConflict, DallyOpsError, DallyOpsInternal, DallyOpsNotFound


CHAMPS_INTAKE = frozenset({
    "request_uuid", "consolidation_reference", "customer_reference",
    "received_on", "line",
})
CHAMPS_LIGNE = frozenset({
    "line_uuid", "package_type", "goods_category", "description", "quantity",
    "announced_weight_kg", "exact_weight_kg", "length_cm", "width_cm",
    "height_cm", "billing_method", "tariff_family_code", "customs_value_xof",
})
CHAMPS_INTERDITS = frozenset({
    "partner_id", "shipment_id", "package_id", "consolidation_id",
    "external_reference", "external_line_key", "sync_source_key",
    "collection_sequence", "collection_local_ref", "transport_mode", "direction",
    "origin", "destination", "manual_unit_price_eur", "pricing_reason",
    "pricing_type", "state",
})
TYPES_COLIS_OPS = frozenset({"parcel", "pallet", "crate", "bag", "drum", "other"})
METHODES_FACTURATION = frozenset({"real", "volumetric", "quote"})
STATUTS_PRICING_VALIDES = frozenset({"automatic", "manual_required", "quote"})


class DallyOpsIntakeService(models.AbstractModel):
    _name = "dally.ops.intake.service"
    _description = "Dally Ops — création d'une réception Freight"

    @api.model
    def create_intake(self, payload):
        """Crée ou rejoue une réception dans un point de sauvegarde atomique."""
        self._exiger_role_ops()
        donnees = self._valider(payload)

        with self.env.cr.savepoint():
            self._verrouiller_demande(donnees["request_uuid"])
            registre = self._registre(donnees["request_uuid"])
            if registre:
                if registre.payload_hash != self._empreinte(donnees):
                    raise DallyOpsConflict(
                        _("Cette demande a déjà été traitée avec des informations différentes."),
                        code="idempotency_conflict",
                    )
                dto = self._dto(
                    registre.shipment_id, registre.package_id, registre.line_uuid,
                    status="replayed",
                )
                self._journaliser(
                    "intake_request_replayed", registre.shipment_id,
                    donnees["request_uuid"],
                )
                return dto

            partenaire = self._resoudre_client(donnees["customer_reference"])
            consolidation = self._resoudre_consolidation(
                donnees["consolidation_reference"], verrouiller=True,
            )
            famille = self._resoudre_famille(
                donnees["line"]["tariff_family_code"],
            )
            charge_freight = self._charge_freight(
                donnees, partenaire, consolidation, famille,
            )
            FreightSync = (
                self.env["dally.freight.sync.service"]
                .sudo()
                .with_company(self.env.company)
                .with_context(default_user_id=False)
            )
            try:
                resultat, shipment = FreightSync.upsert(charge_freight)
            except UserError as erreur:
                consolidation.invalidate_recordset(
                    ["active", "state", "transport_mode"],
                )
                if (
                    not consolidation.active
                    or consolidation.state != "collecting"
                    or consolidation.transport_mode not in ("air", "sea")
                ):
                    raise DallyOpsConflict(
                        _("Cette consolidation n'est plus ouverte à la réception."),
                        code="consolidation_not_open",
                    ) from erreur
                raise DallyOpsInternal(
                    _("La réception n'a pas pu être créée."),
                ) from erreur

            package = self._verifier_resultat(
                resultat, shipment, consolidation,
            )
            pricing_status = resultat["lines"][0]["pricing_status"]
            if pricing_status not in STATUTS_PRICING_VALIDES:
                raise DallyOpsInternal(
                    _("Résultat de tarification incohérent."),
                    code="pricing_inconsistency",
                )

            self.env["dally.ops.intake.request"].sudo().create({
                "request_uuid": donnees["request_uuid"],
                "company_id": self.env.company.id,
                "payload_hash": self._empreinte(donnees),
                "state": "created",
                "shipment_id": shipment.id,
                "package_id": package.id,
                "line_uuid": donnees["line"]["line_uuid"],
                "operator_user_id": self.env.uid,
            })
            self._journaliser(
                "intake_created", shipment, donnees["request_uuid"],
            )
            return self._dto(
                shipment, package, donnees["line"]["line_uuid"],
                status="created", pricing_status=pricing_status,
            )

    @api.model
    def list_tariff_families(self):
        self._exiger_role_ops()
        familles = self.env["dally.freight.tariff.family"].sudo().search(
            [("active", "=", True)], order="sequence, name, id",
        )
        return [
            {"code": famille.code, "name": famille.name}
            for famille in familles
        ]

    @api.model
    def _exiger_role_ops(self):
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))

    @api.model
    def _valider(self, payload):
        if not isinstance(payload, dict):
            raise DallyOpsError(_("Demande de réception invalide."))
        inconnus = set(payload) - CHAMPS_INTAKE
        if inconnus:
            if inconnus & CHAMPS_INTERDITS:
                raise DallyOpsError(_("Champ réservé au serveur."))
            raise DallyOpsError(_("Champ non pris en charge dans la demande."))
        if set(payload) != CHAMPS_INTAKE:
            raise DallyOpsError(_("Un champ obligatoire est manquant."))

        request_uuid = self._uuid(payload.get("request_uuid"), "request_uuid")
        customer_reference = self._uuid(
            payload.get("customer_reference"), "customer_reference",
        )
        consolidation_reference = self._texte(
            payload.get("consolidation_reference"),
            "consolidation_reference", 120,
        )
        try:
            received_on = fields.Date.to_date(payload.get("received_on"))
        except (TypeError, ValueError):
            received_on = False
        if (
            not received_on
            or not isinstance(payload.get("received_on"), str)
            or received_on.isoformat() != payload["received_on"]
        ):
            raise DallyOpsError(_("Date de réception invalide."))

        line = payload.get("line")
        if not isinstance(line, dict):
            raise DallyOpsError(_("Ligne de colis invalide."))
        inconnus_ligne = set(line) - CHAMPS_LIGNE
        if inconnus_ligne:
            if inconnus_ligne & CHAMPS_INTERDITS:
                raise DallyOpsError(_("Champ réservé au serveur."))
            raise DallyOpsError(_("Champ de ligne non pris en charge."))
        if set(line) != CHAMPS_LIGNE:
            raise DallyOpsError(_("Un champ de ligne obligatoire est manquant."))

        package_type = self._choix(
            line.get("package_type"), TYPES_COLIS_OPS,
            _("Type de colis invalide."),
        )
        billing_method = self._choix(
            line.get("billing_method"), METHODES_FACTURATION,
            _("Méthode de facturation invalide."),
        )
        quantity = line.get("quantity")
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise DallyOpsError(
                _("La quantité doit être un entier supérieur à zéro."),
            )

        announced = self._nombre(
            line.get("announced_weight_kg"),
            "announced_weight_kg", requis=False, strict=False,
        )
        exact = self._nombre(
            line.get("exact_weight_kg"), "exact_weight_kg",
        )
        customs = self._nombre(
            line.get("customs_value_xof"), "customs_value_xof",
        )
        dimensions = {
            cle: self._nombre(
                line.get(cle), cle, requis=False, strict=True,
            )
            for cle in ("length_cm", "width_cm", "height_cm")
        }
        presentes = [valeur is not None for valeur in dimensions.values()]
        if any(presentes) and not all(presentes):
            raise DallyOpsError(
                _("Les trois dimensions doivent être renseignées ensemble."),
            )
        if billing_method == "volumetric" and not all(presentes):
            raise DallyOpsError(
                _("Les dimensions sont obligatoires en facturation volumétrique."),
            )

        return {
            "request_uuid": request_uuid,
            "consolidation_reference": consolidation_reference,
            "customer_reference": customer_reference,
            "received_on": received_on.isoformat(),
            "line": {
                "line_uuid": self._uuid(
                    line.get("line_uuid"), "line_uuid",
                ),
                "package_type": package_type,
                "goods_category": self._texte(
                    line.get("goods_category"), "goods_category", 200,
                ),
                "description": self._texte(
                    line.get("description"), "description", 500,
                ),
                "quantity": quantity,
                "announced_weight_kg": announced,
                "exact_weight_kg": exact,
                **dimensions,
                "billing_method": billing_method,
                "tariff_family_code": self._texte(
                    line.get("tariff_family_code"),
                    "tariff_family_code", 80,
                ).lower(),
                "customs_value_xof": customs,
            },
        }

    @staticmethod
    def _uuid(value, field_name):
        if not isinstance(value, str):
            raise DallyOpsError(
                _("Identifiant invalide : %s.", field_name),
            )
        try:
            return str(uuid_module.UUID(value.strip()))
        except (ValueError, AttributeError):
            raise DallyOpsError(
                _("Identifiant invalide : %s.", field_name),
            )

    @staticmethod
    def _texte(value, field_name, limit):
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > limit
        ):
            raise DallyOpsError(_("Champ invalide : %s.", field_name))
        return value.strip()

    @staticmethod
    def _choix(value, allowed, message):
        if not isinstance(value, str) or value.strip() not in allowed:
            raise DallyOpsError(message)
        return value.strip()

    @staticmethod
    def _nombre(value, field_name, *, requis=True, strict=True):
        if value is None:
            if requis:
                raise DallyOpsError(
                    _("Champ obligatoire manquant : %s.", field_name),
                )
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DallyOpsError(
                _("Valeur numérique invalide : %s.", field_name),
            )
        nombre = float(value)
        if (
            not math.isfinite(nombre)
            or (nombre <= 0 if strict else nombre < 0)
        ):
            raise DallyOpsError(
                _("Valeur numérique invalide : %s.", field_name),
            )
        return nombre

    @staticmethod
    def _empreinte(donnees):
        canonique = json.dumps(
            donnees, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonique.encode("utf-8")).hexdigest()

    @api.model
    def _verrouiller_demande(self, request_uuid):
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [
                "ops-intake-request:%s:%s"
                % (self.env.company.id, request_uuid)
            ],
        )

    @api.model
    def _registre(self, request_uuid):
        return self.env["dally.ops.intake.request"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("request_uuid", "=", request_uuid),
        ], limit=1)

    @api.model
    def _resoudre_client(self, token):
        handle = self.env["dally.ops.customer.handle"].sudo().search([
            ("token", "=", token),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        partenaire = (
            handle.partner_id
            if handle
            else self.env["res.partner"].sudo().browse()
        )
        if (
            not partenaire
            or not partenaire.active
            or (
                partenaire.company_id
                and partenaire.company_id != self.env.company
            )
        ):
            raise DallyOpsNotFound(
                _("Client introuvable."), code="customer_not_found",
            )
        return partenaire

    @api.model
    def _resoudre_consolidation(self, reference, *, verrouiller=False):
        Consolidation = self.env[
            "dally.freight.consolidation"
        ].sudo()
        if verrouiller:
            self.env.cr.execute(
                """
                SELECT id FROM dally_freight_consolidation
                 WHERE company_id = %s AND name = %s
                 FOR UPDATE
                """,
                [self.env.company.id, reference],
            )
        consolidation = Consolidation.search([
            ("company_id", "=", self.env.company.id),
            ("name", "=", reference),
            ("active", "=", True),
            ("state", "=", "collecting"),
            ("transport_mode", "in", ["air", "sea"]),
        ], limit=1)
        if not consolidation:
            raise DallyOpsConflict(
                _("Cette consolidation n'est pas ouverte à la réception."),
                code="consolidation_not_open",
            )
        return consolidation

    @api.model
    def _resoudre_famille(self, code):
        famille = self.env[
            "dally.freight.tariff.family"
        ].sudo().search([
            ("code", "=", code),
            ("active", "=", True),
        ], limit=1)
        if not famille:
            raise DallyOpsError(_("Famille tarifaire inconnue."))
        return famille

    @staticmethod
    def _route(consolidation, prefix):
        pays = getattr(consolidation, "%s_country_id" % prefix)
        return {
            "country_code": pays.code or "",
            "city": getattr(
                consolidation, "%s_city" % prefix,
            ) or "",
            "location": getattr(
                consolidation, "%s_location" % prefix,
            ) or "",
        }

    @api.model
    def _charge_freight(
        self, donnees, partenaire, consolidation, famille,
    ):
        line = donnees["line"]
        return {
            "sync_source_key": "ops:%s" % donnees["request_uuid"],
            "planned_consolidation_ref": consolidation.name,
            "transport_mode": consolidation.transport_mode,
            "direction": consolidation.direction,
            "source": "backoffice",
            "partner_id": partenaire.id,
            "customer_segment": (
                "business" if partenaire.is_company else "individual"
            ),
            "goods_received_on": donnees["received_on"],
            "state": "goods_received",
            "origin": self._route(consolidation, "origin"),
            "destination": self._route(consolidation, "destination"),
            "lines": [{
                "external_line_key": (
                    "ops:%s:line:%s"
                    % (
                        donnees["request_uuid"],
                        line["line_uuid"],
                    )
                ),
                "package_type": line["package_type"],
                "goods_category": line["goods_category"],
                "description": line["description"],
                "quantity": line["quantity"],
                "announced_weight_kg": (
                    line["announced_weight_kg"]
                ),
                "exact_weight_kg": line["exact_weight_kg"],
                "length_cm": line["length_cm"],
                "width_cm": line["width_cm"],
                "height_cm": line["height_cm"],
                "billing_method": line["billing_method"],
                "tariff_family_code": famille.code,
                "customs_value_xof": line["customs_value_xof"],
            }],
        }

    @api.model
    def _verifier_resultat(
        self, resultat, shipment, consolidation,
    ):
        lignes = resultat.get("lines") or []
        if len(lignes) != 1:
            raise DallyOpsInternal(_("Résultat Freight incomplet."))
        package = self.env[
            "dally.shipment.package"
        ].sudo().browse(lignes[0].get("line_id") or []).exists()
        correct = (
            package
            and package.shipment_id == shipment
            and shipment.state == "goods_received"
            and shipment.intake_consolidation_id == consolidation
            and shipment.planned_consolidation_id == consolidation
            and not resultat.get("requires_replan")
            and resultat.get("attached_to_consolidation") is True
            and shipment.consolidation_id == consolidation
            and not shipment.user_id
        )
        if not correct:
            raise DallyOpsInternal(_("Résultat Freight incohérent."))
        return package

    @staticmethod
    def _pricing_snapshot(package):
        if package.billing_method == "quote":
            return "quote"
        if package.manual_unit_price_eur:
            return "manual"
        if package.tariff_rule_id and package.tariff_applied_on:
            return "automatic"
        return "manual_required"

    @api.model
    def _dto(
        self, shipment, package, line_uuid, *,
        status, pricing_status=None,
    ):
        pricing_status = (
            pricing_status or self._pricing_snapshot(package)
        )
        tarif_defini = pricing_status == "automatic"
        montant = (
            package.transport_amount_eur if tarif_defini else None
        )
        return {
            "status": status,
            "intake": {
                "reference": shipment.external_reference,
                "local_reference": shipment.collection_local_ref,
                "consolidation_reference": (
                    shipment.intake_consolidation_id.name
                ),
                "state": shipment.state,
                "received_on": (
                    shipment.goods_received_on.isoformat()
                ),
                "line": {
                    "reference": line_uuid,
                    "description": package.description or "",
                    "goods_category": (
                        package.goods_category or ""
                    ),
                    "quantity": package.quantity,
                    "exact_weight_kg": package.total_weight_kg,
                    "volume_cbm": package.total_volume_cbm,
                    "billing_method": package.billing_method,
                    "tariff_family_code": (
                        package.tariff_family_id.code
                    ),
                    "customs_value_xof": (
                        package.customs_value_xof
                    ),
                    "pricing_status": pricing_status,
                    "billable_weight_kg": (
                        package.billable_weight_kg
                    ),
                    "applied_unit_price_eur": (
                        package.applied_unit_price_eur
                        if tarif_defini else None
                    ),
                    "transport_amount_eur": montant,
                },
                "totals": {
                    "weight_kg": package.total_weight_kg,
                    "volume_cbm": package.total_volume_cbm,
                    "transport_amount_eur": montant,
                },
            },
        }

    @api.model
    def _journaliser(
        self, action, shipment, request_uuid,
    ):
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": action,
            "entity_model": "dally.shipment",
            "entity_res_id": shipment.id,
            "request_uuid": request_uuid,
            "created_at": fields.Datetime.now(),
        })
