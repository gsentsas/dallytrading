# -*- coding: utf-8 -*-
"""`fields_get` ne doit pas décrire ce qu'on n'a pas le droit de lire.

## Le trou que ce fichier ferme

Odoo n'applique aucun contrôle d'accès à ``fields_get``. Un utilisateur portail
authentifié peut donc, par ``/web/dataset/call_kw``, obtenir la description
complète des champs de ``dally.sourcing.offer`` — sur lequel il n'a pourtant
**aucune** ACL. Il n'obtient aucune donnée : ni offre, ni prix, ni fournisseur.
Il obtient le schéma.

Mesuré sur l'instance : la réponse contient ``landed_unit_cost``,
``overall_score``, ``internal_notes`` — avec leurs textes d'aide, qui décrivent
notre façon de comparer des fournisseurs et de construire une proposition.

Ce n'est pas une fuite de données client, et rien ne permet d'en dériver un
montant. C'est une fuite de conception : elle apprend à un attaquant ce qui
existe et comment nous raisonnons, ce qui est précisément ce dont il a besoin
pour choisir sa prochaine tentative.

## Pourquoi une liste courte plutôt qu'une règle générale

Surcharger ``fields_get`` sur tous les modèles ferait porter un ``check_access``
à chaque construction de vue, y compris sur des modèles liés que l'interface
interne interroge légitimement sans les lire en entier. Le risque de casser
l'ergonomie interne serait réel, et le gain nul : ces modèles-là n'ont rien de
confidentiel.

La liste ci-dessous est donc celle des modèles qu'un client ne doit jamais
toucher, ni en données ni en description. Elle reprend exactement celle que le
test de contournement RPC surveille.
"""

from odoo import api, models


class DallySourcingOfferSchemaGuard(models.Model):
    _name = "dally.sourcing.offer"
    _inherit = "dally.sourcing.offer"

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        # `check_access` lève une AccessError si l'appelant n'a pas d'ACL de
        # lecture — c'est-à-dire exactement dans le cas qu'on veut refuser, et
        # jamais pour un salarié qui travaille sur ces écrans.
        self.check_access("read")
        return super().fields_get(allfields=allfields, attributes=attributes)


class DallySourcingSupplierSchemaGuard(models.Model):
    _name = "dally.sourcing.supplier"
    _inherit = "dally.sourcing.supplier"

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        self.check_access("read")
        return super().fields_get(allfields=allfields, attributes=attributes)


class DallyTradeCostSchemaGuard(models.Model):
    _name = "dally.trade.cost"
    _inherit = "dally.trade.cost"

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        self.check_access("read")
        return super().fields_get(allfields=allfields, attributes=attributes)


class DallyTradeCommissionSchemaGuard(models.Model):
    _name = "dally.trade.commission"
    _inherit = "dally.trade.commission"

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        self.check_access("read")
        return super().fields_get(allfields=allfields, attributes=attributes)
