# -*- coding: utf-8 -*-
"""Freeze commercial inputs once native invoice documents exist."""

from odoo import api, models, _
from odoo.exceptions import UserError


#: Le seul contexte qui ouvre la creation d'une ligne sur un dossier verrouille.
#:
#: Nomme explicitement plutot que generique : un lecteur qui le croise dans une
#: pile d'appels doit comprendre du premier coup ce qui est autorise, et le
#: nom interdit de le reutiliser pour autre chose.
SUPPLEMENT_CREATE_CONTEXT = "dally_allow_posted_invoice_supplement_create"

#: Le contexte qui autorise la tarification d'UN colis complementaire precis.
#:
#: Il ne porte pas un booleen mais l'`id` du package concerne : un contexte
#: booleen s'appliquerait a tout ce que la pile touche ensuite, alors qu'ici il
#: ne designe qu'un enregistrement. Toutes les preconditions sont malgre tout
#: relues en base au moment de l'ecriture — le contexte dit qui appelle, jamais
#: si c'est legitime.
SUPPLEMENT_PRICING_CONTEXT = "dally_allow_posted_invoice_supplement_pricing"

#: Les seules colonnes verrouillees que la tarification a le droit d'ecrire.
#:
#: Ce sont exactement celles qu'`action_apply_freight_tariff` pose, et rien
#: d'autre. Le poids, les dimensions, la nature de la marchandise, la cle
#: article et le rattachement au dossier restent hors d'atteinte.
SUPPLEMENT_PRICING_FIELDS = frozenset({
    "applied_unit_price_eur",
    "pricing_type_snapshot",
    "pricing_reason",
    "volumetric_ratio_kg_cbm",
})

LOCKED_SHIPMENT_FIELDS = frozenset({
    "partner_id",
    "external_reference",
    "transport_mode",
    "direction",
    "goods_received_on",
    "customer_segment_snapshot",
    "dossier_fee_eur",
    "other_fees_eur",
})

LOCKED_PACKAGE_FIELDS = frozenset({
    "shipment_id",
    # L'identite de la ligne source. Elle porte l'idempotence du Freight sync :
    # c'est par elle qu'un rejeu retrouve son colis, qu'un colis NOUVEAU se
    # distingue d'une correction, et que `covered_line_keys` designe au classeur
    # les lignes a mettre a jour. La changer sur un colis facture ferait
    # reapparaitre la marchandise comme neuve au rejeu suivant, et le
    # complement la refacturerait.
    "external_line_key",
    "quantity",
    "unit_weight_kg",
    "length_cm",
    "width_cm",
    "height_cm",
    "unit_volume_cbm",
    "billing_method",
    "tariff_family_id",
    "volumetric_ratio_kg_cbm",
    "manual_unit_price_eur",
    "applied_unit_price_eur",
    "pricing_type_snapshot",
    "pricing_reason",
    "customs_value_xof",
})


def _normalised_current_value(record, field_name):
    value = record[field_name]
    if hasattr(value, "id"):
        return value.id or False
    return value


def _same_value(record, field_name, new_value):
    current = _normalised_current_value(record, field_name)
    if current in (None, ""):
        current = False
    if new_value in (None, ""):
        new_value = False
    return current == new_value


def _actual_changes(record, vals, protected):
    return {
        field_name
        for field_name in protected
        if not _same_value(record, field_name, vals[field_name])
    }


class DallyShipment(models.Model):
    _inherit = "dally.shipment"

    def write(self, vals):
        protected = LOCKED_SHIPMENT_FIELDS.intersection(vals)
        if protected:
            offenders = []
            changed_fields = set()
            for shipment in self.filtered("billing_locked"):
                changes = _actual_changes(shipment, vals, protected)
                if changes:
                    offenders.append(shipment.display_name)
                    changed_fields.update(changes)
            if offenders:
                raise UserError(
                    _(
                        "Freight billing is locked for %(references)s. Reset the "
                        "draft billing documents before changing: %(fields)s."
                    )
                    % {
                        "references": ", ".join(offenders),
                        "fields": ", ".join(sorted(changed_fields)),
                    }
                )
        return super().write(vals)


class DallyShipmentPackage(models.Model):
    _inherit = "dally.shipment.package"

    @api.model_create_multi
    def create(self, vals_list):
        shipment_ids = {
            vals.get("shipment_id")
            for vals in vals_list
            if vals.get("shipment_id")
        }
        if shipment_ids:
            locked = self.env["dally.shipment"].browse(shipment_ids).filtered("billing_locked")
            if locked:
                self._check_posted_invoice_supplement(locked, vals_list)
        return super().create(vals_list)

    @api.model
    def _check_posted_invoice_supplement(self, locked, vals_list):
        """Autorise une ligne nouvelle sur une facture principale comptabilisee.

        ## Pourquoi une exception, et pourquoi celle-la seulement

        Le verrou existe pour qu'une correction du classeur ne reecrive jamais
        une piece comptable. Il repond mal a un cas different : de la
        marchandise qui arrive *apres* la facture. Le colis est reel, il partira
        avec le depart, et le refuser laisse la base plus fausse que la facture
        ne l'etait.

        La sortie n'est donc ouverte que quand la facture principale est
        `posted`. Tant qu'elle est `draft`, le bon geste reste de la
        reinitialiser : rien n'est encore comptabilise, et un complement
        creerait une seconde piece la ou une seule suffit.

        ## Pourquoi revalider ici

        Le contexte dit qui appelle, jamais si c'est legitime. Un contexte se
        pose de l'exterieur ; ces preconditions, elles, se lisent dans la base.
        Elles sont donc verifiees ici meme, a chaque creation.
        """
        if not self.env.context.get(SUPPLEMENT_CREATE_CONTEXT):
            raise UserError(
                _("Cannot add freight lines while billing is locked. Reset the draft billing first.")
            )

        refuses = locked.filtered(
            lambda shipment: not (
                shipment.invoice_id and shipment.invoice_id.state == "posted"
            )
        )
        if refuses:
            raise UserError(_(
                "Un complement de fret exige une facture principale comptabilisee. "
                "Reinitialisez la facturation brouillon de %s.",
                ", ".join(refuses.mapped("display_name")),
            ))

        # Un complement n'ajoute que des lignes neuves. Reutiliser une cle
        # existante serait une correction deguisee d'un colis deja facture.
        cles = [
            vals.get("external_line_key")
            for vals in vals_list
            if vals.get("external_line_key")
        ]
        if cles:
            deja = self.with_context(active_test=False).search(
                [("external_line_key", "in", cles)], limit=1)
            if deja:
                raise UserError(_(
                    "La cle article %s existe deja : un complement n'ajoute que "
                    "des lignes nouvelles.", deja.external_line_key))

        # Un brouillon de complement fige un perimetre. Y ajouter de la
        # marchandise le ferait diverger de ce que Finance a sous les yeux.
        brouillon = locked.filtered(
            lambda shipment: shipment._supplement_draft_invoice())
        if brouillon:
            raise UserError(_(
                "Un complement brouillon existe deja pour %s. Postez-le ou "
                "annulez-le avant d'ajouter un nouveau colis.",
                ", ".join(brouillon.mapped("display_name")),
            ))
        return True

    def _deja_porte_par_une_commande(self):
        """Ce colis a-t-il deja produit une ligne de commande ?

        C'est le discriminant qui rend l'exception inapplicable a l'historique :
        un colis facture porte forcement une `sale.order.line`, donc il echoue
        ici quoi qu'il arrive — meme si un appelant lui presentait un contexte
        parfaitement forme.
        """
        self.ensure_one()
        return bool(self.env["sale.order.line"].sudo().search_count([
            ("dally_freight_package_id", "=", self.id),
            ("state", "!=", "cancel"),
        ]))

    def _supplement_pricing_allowed(self, protected=None):
        """La tarification de CE colis complementaire est-elle autorisee ?

        Le contexte doit nommer cet `id` exact, et chacune des preconditions se
        relit en base : dossier verrouille, facture principale existante et
        comptabilisee, cle article presente, et surtout aucune ligne de commande
        deja emise pour ce colis.

        `protected` est le sous-ensemble verrouille que l'appelant veut ecrire ;
        il doit tenir entierement dans la liste blanche de tarification. Un
        `write` qui glisserait un poids ou une dimension a cote des colonnes
        tarifaires est refuse en bloc.
        """
        self.ensure_one()
        if self.env.context.get(SUPPLEMENT_PRICING_CONTEXT) != self.id:
            return False
        if protected is not None and not protected <= SUPPLEMENT_PRICING_FIELDS:
            return False
        shipment = self.shipment_id
        if not shipment.billing_locked:
            return False
        if not (shipment.invoice_id and shipment.invoice_id.state == "posted"):
            return False
        if not self.external_line_key:
            return False
        return not self._deja_porte_par_une_commande()

    def write(self, vals):
        protected = LOCKED_PACKAGE_FIELDS.intersection(vals)
        if protected:
            for line in self.filtered(lambda item: item.shipment_id.billing_locked):
                if not _actual_changes(line, vals, protected):
                    continue
                # La seule sortie : poser le tarif d'un colis complementaire qui
                # vient d'etre cree et qu'aucune commande ne porte encore.
                if line._supplement_pricing_allowed(protected):
                    continue
                raise UserError(
                    _(
                        "Cannot change invoiced freight article data while billing "
                        "is locked. Reset the draft billing first."
                    )
                )
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda line: line.shipment_id.billing_locked):
            raise UserError(
                _("Cannot delete freight lines while billing is locked. Reset the draft billing first.")
            )
        return super().unlink()
