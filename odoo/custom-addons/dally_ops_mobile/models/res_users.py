# -*- coding: utf-8 -*-
"""L'acteur de caisse d'un utilisateur, déclaré et non deviné.

## Le problème mesuré

Les opérations de caisse désignent leur acteur par du **texte libre** :
`dally.cash.expense.allocation.actor_name`, et `from_actor` / `to_actor` sur
les transferts. En production, ces colonnes contiennent « Gilles » et
« Alain ». Les paiements, eux, ont déjà `collected_by_id` vers `res.users`.
Il n'existe donc pas d'acteur canonique — la moitié du domaine l'ignore.

## Pourquoi pas `display_name`

Parce qu'il change. Un utilisateur renommé, un homonyme, un second prénom
ajouté, un accent saisi différemment, et la dépense est imputée à quelqu'un
d'autre. Une caisse mal attribuée ne se voit pas le jour même : elle se
découvre au rapprochement, quand plus personne ne se souvient.

La correspondance est donc **déclarée une fois**, dans un champ dédié, et lue
telle quelle. Elle peut différer du nom affiché sans que rien ne casse.

## Fail closed

`_dally_ops_actor()` **lève** quand l'utilisateur n'a pas d'acteur configuré,
au lieu de retomber sur son nom. Un logisticien mal configuré ne peut pas
enregistrer de caisse — c'est bruyant, immédiat, et corrigé en une minute.
L'inverse produirait des écritures fausses que personne ne remarquerait.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResUsers(models.Model):
    _name = "res.users"
    _inherit = "res.users"

    dally_ops_cash_actor = fields.Char(
        string="Acteur de caisse",
        help="Nom exact sous lequel cet utilisateur apparaît dans les "
             "opérations de caisse — dépenses, transferts, encaissements. "
             "Doit correspondre aux valeurs déjà employées par la feuille de "
             "calcul, sans quoi les deux sources décriraient deux personnes "
             "différentes.",
        copy=False,
    )

    def _dally_ops_actor(self):
        """Le nom d'acteur de cet utilisateur, ou une erreur explicite."""
        self.ensure_one()
        actor = (self.dally_ops_cash_actor or "").strip()
        if not actor:
            raise UserError(_(
                "Aucun acteur de caisse n'est configuré pour %s. "
                "Un responsable doit le renseigner avant toute opération de "
                "caisse : l'imputation ne se devine pas.",
                self.display_name,
            ))
        return actor

    @api.model
    def _dally_ops_role(self):
        """« supervisor », « logistician », ou False si ni l'un ni l'autre."""
        if self.env.user.has_group("dally_ops_mobile.group_dally_ops_supervisor"):
            return "supervisor"
        if self.env.user.has_group("dally_ops_mobile.group_dally_ops_logistician"):
            return "logistician"
        return False
