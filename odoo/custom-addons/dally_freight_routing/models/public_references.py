# -*- coding: utf-8 -*-
"""Ce que la vitrine a le droit de savoir des référentiels.

## Une seule liste blanche, ici

Chaque projection énumère ses champs. Rien n'est renvoyé « parce que le modèle
le porte » : c'est la règle du projet, et elle vaut d'autant plus pour des
modèles du fournisseur, dont une mise à jour peut ajouter un champ sans nous
prévenir. Une liste blanche ne laisse pas passer ce qui n'existait pas quand
elle a été écrite.

## Pourquoi le code et pas l'identifiant

Les projections publient `code`, pas `id`. Le navigateur renvoie donc « SNDKR »
et non « 7 » — et le serveur résout ce code, dans le référentiel, en vérifiant
qu'il correspond au mode demandé.

Trois raisons. Un identifiant séquentiel s'énumère et raconte la taille du
référentiel. Un code est vérifiable : « SNDKR » est faux ou juste, tandis que
« 7 » est toujours plausible. Et une base restaurée ou rejouée ne conserve pas
ses identifiants, alors qu'un UN/LOCODE ne change pas.

## Ce qui n'est jamais publié

Aucun transporteur, aucune compagnie maritime ou aérienne, aucun navire, aucun
itinéraire fréquent, aucun coût, aucune marge, aucune note. Ce sont des
éléments de qualification commerciale : le client décrit son besoin, il ne
choisit pas notre sous-traitant.
"""

from odoo import api, models

#: Modes publics → drapeau du référentiel des lieux. Le vocabulaire
#: extérieur reste celui du client — maritime, aérien, routier.
MODES_PUBLICS = {"sea": "ocean", "air": "air", "road": "land"}


class ResCountry(models.Model):
    _inherit = "res.country"

    @api.model
    def _dally_public_countries(self):
        """Les pays, pour une liste déroulante."""
        pays = self.sudo().search([], order="name")
        return [{"code": p.code, "name": p.name} for p in pays if p.code]


class ResCountryState(models.Model):
    _inherit = "res.country.state"

    @api.model
    def _dally_public_states(self, country_code):
        """Les subdivisions d'un pays, jamais toutes à la fois.

        Deux mille lignes envoyées pour en afficher quatorze coûtent au visiteur
        une seconde de réseau et à nous rien de gagné. Le pays est donc exigé.
        """
        code = (country_code or "").strip().upper()
        if not code:
            return []
        etats = self.sudo().search(
            [("country_id.code", "=", code)], order="name")
        return [{"code": e.code, "name": e.name} for e in etats]


class AccountIncoterms(models.Model):
    _inherit = "account.incoterms"

    @api.model
    def _dally_public_incoterms(self):
        """Les incoterms d'Odoo, qui sont ceux de la CCI — donc publics."""
        incoterms = self.sudo().search([("active", "=", True)], order="code")
        return [{"code": i.code, "name": i.name} for i in incoterms]


class FreightPort(models.Model):
    _inherit = "freight.port"

    @api.model
    def _dally_public_locations(self, mode=None):
        """Les lieux desservis, filtrés par mode.

        Sans mode, la liste complète : c'est ce que demande un service dont le
        transport n'est pas encore déterminé, et il n'y a rien de confidentiel
        dans un port. Avec un mode inconnu, une liste vide plutôt qu'une liste
        entière — un paramètre incompris ne doit jamais élargir une réponse.
        """
        domaine = [("active", "=", True)]
        if mode:
            drapeau = MODES_PUBLICS.get(mode)
            if not drapeau:
                return []
            domaine.append((drapeau, "=", True))

        lieux = self.sudo().search(domaine, order="name")
        return [
            {
                "code": lieu.code,
                "name": lieu.name,
                "city": lieu.city or None,
                "country_code": lieu.country_id.code or None,
                "state_code": lieu.state_id.code or None,
                "sea": bool(lieu.ocean),
                "air": bool(lieu.air),
                "road": bool(lieu.land),
            }
            for lieu in lieux
            if lieu.code
        ]
