# -*- coding: utf-8 -*-
"""Projections portail — ce qu'un client voit de chacun de ses dossiers.

## Une deuxième barrière, pas la seule

Ces listes blanches ne remplacent ni les ACL ni les ``groups=`` posés sur les champs
sensibles. Elles s'y ajoutent. La différence compte : un champ protégé par
``groups=`` n'est **pas chargé** par l'ORM pour un utilisateur portail, même s'il le
demande explicitement par ``read()``. Une liste blanche, elle, ne protège que ce qui
passe par elle — un futur contrôleur qui sérialiserait un record autrement la
contournerait sans s'en apercevoir.

L'ordre de défense est donc : ACL → record rule → ``groups=`` sur les champs →
projection. Ce fichier est la dernière couche, la plus visible et la moins
essentielle.

## Pourquoi des listes explicites plutôt qu'une exclusion

Une liste d'exclusion protège les champs qu'on a pensé à exclure. Un champ ajouté
demain à ``dally.trade.opportunity`` serait exposé par défaut. Une liste blanche fait
l'inverse : il est absent tant que quelqu'un ne l'ajoute pas sciemment.
"""

from odoo import models


class DallyQuoteRequestPortal(models.Model):
    _inherit = "dally.quote.request"

    PORTAL_PAYLOAD_KEYS = (
        "reference", "service", "status", "createdOn",
        "origin", "destination", "goodsDescription", "quantity",
    )

    def _dally_portal_payload(self):
        """Ce que le client voit de sa demande de devis.

        Absents volontairement : `internal_notes` et `user_id` (protégés par
        ``groups=``), `lead_id`, `sale_order_ids` et les champs UTM. La provenance
        marketing d'une demande est une information sur nous, pas sur le client.
        """
        self.ensure_one()
        payload = {
            "reference": self.reference,
            "service": self.service_code or None,
            "status": self.state,
            "createdOn": (
                self.create_date.date().isoformat() if self.create_date else None
            ),
            "origin": ", ".join(filter(None, [
                self.origin_city, self.origin_country_id.name])) or None,
            "destination": ", ".join(filter(None, [
                self.destination_city, self.destination_country_id.name])) or None,
            "goodsDescription": self.goods_description or None,
            "quantity": self.quantity or None,
        }
        return {key: payload[key] for key in self.PORTAL_PAYLOAD_KEYS}


class DallySourcingRequestPortal(models.Model):
    _inherit = "dally.sourcing.request"

    PORTAL_PAYLOAD_KEYS = (
        "reference", "status", "productName", "productReference",
        "quantity", "unit", "createdOn",
    )

    def _dally_portal_payload(self):
        """Ce que le client voit de sa demande de sourcing.

        Rien de la mise en concurrence : ni fournisseurs consultés, ni offres, ni
        scores, ni coûts rendus. Ces champs sont déjà inaccessibles par ``groups=``
        et par l'absence d'ACL sur ``dally.sourcing.offer`` et
        ``dally.sourcing.supplier`` ; leur absence ici est la troisième expression
        de la même règle.
        """
        self.ensure_one()
        payload = {
            "reference": self.reference,
            "status": self.state,
            "productName": self.product_name or None,
            "productReference": self.product_reference or None,
            "quantity": self.quantity,
            "unit": self.uom_id.name or None,
            "createdOn": (
                self.create_date.date().isoformat() if self.create_date else None
            ),
        }
        return {key: payload[key] for key in self.PORTAL_PAYLOAD_KEYS}


class DallySourcingProposalPortal(models.Model):
    _inherit = "dally.sourcing.proposal"

    PORTAL_PAYLOAD_KEYS = (
        "reference", "status", "productName", "quantity", "unit",
        "unitPrice", "total", "currency", "validUntil", "estimatedDelivery",
        "commercialTerms",
    )

    def _dally_portal_payload(self):
        """Ce que le client voit d'une proposition qui lui est faite.

        Le prix de vente et le total y figurent : c'est ce qu'on lui demande
        d'accepter. `cost_basis` et `margin` non — ils portent ``groups=`` et
        décrivent notre position, pas la sienne.
        """
        self.ensure_one()
        payload = {
            "reference": self.reference,
            "status": self.state,
            "productName": self.product_name or None,
            "quantity": self.quantity,
            "unit": self.uom_id.name or None,
            "unitPrice": self.selling_unit_price,
            "total": self.total_amount,
            "currency": self.currency_id.name or None,
            "validUntil": (
                self.validity_date.isoformat() if self.validity_date else None
            ),
            "estimatedDelivery": (
                self.estimated_delivery.isoformat()
                if self.estimated_delivery else None
            ),
            "commercialTerms": self.commercial_terms or None,
        }
        return {key: payload[key] for key in self.PORTAL_PAYLOAD_KEYS}


class DallyTradeOpportunityPortal(models.Model):
    _inherit = "dally.trade.opportunity"

    PORTAL_PAYLOAD_KEYS = (
        "reference", "subject", "operationType", "operationTypeLabel",
        "status", "saleTotal", "currency", "origin", "destination",
        "expectedClose", "createdOn",
    )

    def _dally_portal_payload(self):
        """Projection **client** d'une opération, pas le modèle interne.

        Un dossier de trading a deux contreparties. Le client n'en est qu'une : il
        voit le volet qui le concerne — l'objet, le type, l'état, le montant de
        vente — et rien du volet achat. `supplier_id`, `purchase_subtotal`, les
        coûts, les commissions et les marges portent tous ``groups=`` et ne sont
        pas chargés pour lui.
        """
        self.ensure_one()
        from odoo.addons.dally_trade.models.dally_trade_rules import OPERATION_TYPES
        labels = dict(OPERATION_TYPES)
        payload = {
            "reference": self.reference,
            "subject": self.name,
            "operationType": self.operation_type,
            "operationTypeLabel": labels.get(
                self.operation_type, self.operation_type),
            "status": self.state,
            "saleTotal": self.sale_subtotal,
            "currency": self.sale_currency_id.name or None,
            "origin": self.origin_country_id.name or None,
            "destination": self.destination_country_id.name or None,
            "expectedClose": (
                self.expected_close_date.isoformat()
                if self.expected_close_date else None
            ),
            "createdOn": (
                self.create_date.date().isoformat() if self.create_date else None
            ),
        }
        return {key: payload[key] for key in self.PORTAL_PAYLOAD_KEYS}


class DallyShipmentPortal(models.Model):
    _inherit = "dally.shipment"

    def _dally_portal_payload(self):
        """Réutilise la projection publique du suivi, déjà éprouvée.

        `dally_tracking` expose déjà une vue publique de l'expédition, avec sa
        propre liste blanche et sa timeline filtrée sur `visible_to_customer`. La
        redéfinir ici créerait une seconde définition de « ce qu'un client voit
        d'une expédition », et les deux divergeraient — c'est toujours la moins
        relue qui finit par exposer quelque chose.

        La différence tient au chemin d'accès, pas au contenu : le suivi public
        exige référence + token, le portail s'appuie sur l'identité authentifiée.
        """
        self.ensure_one()
        return self._dally_public_payload()
