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

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError

#: Ce que l'application a le droit de faire, exprimé en verbes métier.
#:
#: Le frontend demande « puis-je créer une réception », jamais « suis-je dans
#: tel groupe ». Sans cette indirection, chaque page connaîtrait les noms des
#: groupes Odoo, et ajouter un droit obligerait à rouvrir toutes les pages.
CAPACITES = (
    "intake_create",
    "intake_search",
    "payment_create",
    "expense_create",
    "transfer_create",
    "appointment_manage",
    "supervise",
)


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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "dally_ops_cash_actor" in vals:
                vals["dally_ops_cash_actor"] = self._dally_ops_normalise_actor(
                    vals["dally_ops_cash_actor"])
        return super().create(vals_list)

    def write(self, vals):
        if "dally_ops_cash_actor" in vals:
            self._dally_ops_check_actor_write()
            vals["dally_ops_cash_actor"] = self._dally_ops_normalise_actor(
                vals["dally_ops_cash_actor"])
        return super().write(vals)

    @api.model
    def _dally_ops_normalise_actor(self, valeur):
        """Espaces retirés ; une valeur qui n'est que des espaces est refusée.

        Vider le champ est légitime — on retire son acteur à quelqu'un qui
        quitte le poste. Enregistrer « ` ` » ne l'est pas : le champ paraîtrait
        rempli et l'imputation échouerait plus tard, loin de la saisie.
        """
        if valeur in (False, None, ""):
            return False
        nettoye = str(valeur).strip()
        if not nettoye:
            raise UserError(_(
                "L'acteur de caisse ne peut pas être une suite d'espaces. "
                "Laissez le champ vide pour retirer l'acteur."))
        return nettoye

    def _dally_ops_check_actor_write(self):
        """Seconde barrière sur l'imputation de caisse d'un collègue.

        La première est l'ORM lui-même : mesuré, un compte Ops — logisticien
        comme responsable — n'a **aucun** droit d'écriture sur `res.users`,
        n'étant pas interne. Configurer l'acteur est donc, dans les faits, une
        tâche d'administration back-office et non une action du terrain.

        Ce contrôle existe quand même, et pour une raison précise : le jour où
        quelqu'un accordera un droit d'écriture sur `res.users` à un rôle Ops —
        pour changer un mot de passe, une langue, une photo — l'imputation de
        caisse ne doit pas suivre dans la foulée. Un logisticien qui peut
        choisir son propre acteur peut imputer ses dépenses à un collègue.
        """
        if self.env.su or self.env.uid == SUPERUSER_ID:
            return True
        if self.env.user.has_group("dally_ops_mobile.group_dally_ops_supervisor"):
            return True
        if self.env.user.has_group("base.group_erp_manager"):
            return True
        raise AccessError(_(
            "Seul un responsable des opérations peut définir l'acteur de "
            "caisse d'un utilisateur."))

    @api.model
    def _dally_ops_capabilities(self):
        """Ce que l'utilisateur courant a le droit de faire, en verbes métier.

        Statique par rôle à ce stade, et centralisé exprès : quand les droits
        se préciseront — un logisticien qui n'encaisse pas, un remplaçant qui
        ne fait que consulter — c'est cette méthode qui changera, pas les
        écrans.
        """
        role = self._dally_ops_role()
        capacites = dict.fromkeys(CAPACITES, False)
        if not role:
            return capacites
        # Une capacité s'ouvre le jour où son écran existe, pas avant :
        # l'annoncer plus tôt ferait promettre à l'application une action que
        # le serveur refuserait. L'agenda attend encore le sien.
        capacites["intake_create"] = True
        capacites["intake_search"] = True
        capacites["payment_create"] = True
        capacites["expense_create"] = True
        capacites["transfer_create"] = True
        capacites["appointment_manage"] = True
        if role == "supervisor":
            capacites["supervise"] = True
        return capacites

    @api.model
    def _dally_ops_identity(self):
        """La charge utile de `/api/v1/ops/me`.

        Volontairement pauvre. N'y figurent ni groupes Odoo, ni identifiant de
        session, ni portée d'API, ni clé primaire : ce sont des détails
        d'implémentation du serveur, et les publier inviterait le frontend à
        raisonner dessus.

        Le login suffit à désigner l'opérateur côté navigateur — c'est lui que
        la file hors connexion utilise pour reconnaître son propriétaire. La
        clé primaire, elle, ne servait à personne et descendait quand même.
        """
        utilisateur = self.env.user
        acteur = (utilisateur.dally_ops_cash_actor or "").strip() or None
        return {
            "user": {
                "name": utilisateur.name,
                "login": utilisateur.login,
            },
            "role": self._dally_ops_role() or None,
            "cash_actor": acteur,
            "cash_actor_configured": bool(acteur),
            "capabilities": self._dally_ops_capabilities(),
        }

    @api.model
    def _dally_ops_role(self):
        """« supervisor », « logistician », ou False si ni l'un ni l'autre."""
        if self.env.user.has_group("dally_ops_mobile.group_dally_ops_supervisor"):
            return "supervisor"
        if self.env.user.has_group("dally_ops_mobile.group_dally_ops_logistician"):
            return "logistician"
        return False
