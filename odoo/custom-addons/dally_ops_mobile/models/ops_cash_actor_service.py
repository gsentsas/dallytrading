# -*- coding: utf-8 -*-
"""Qui est qui, à la caisse.

## Le problème que ce service existe pour fermer

Les opérations de caisse désignent leurs acteurs par du **texte libre** :
`from_actor`, `to_actor`, `actor_name`. Rien, dans la base, ne garantit qu'un
nom d'acteur désigne une seule personne. Laisser le navigateur en saisir un
reviendrait à accepter « Dalandaa », « dalanda » ou « Dalanda Ba » comme trois
caisses distinctes — et à découvrir l'écart au rapprochement, quand plus
personne ne se souvient de la remise.

Le terrain choisit donc dans une liste que le serveur construit, et le serveur
refuse de deviner quand la configuration est ambiguë.

## Ce qu'ambigu veut dire ici

Deux comptes actifs dont l'acteur, une fois les espaces retirés et la casse
neutralisée, donne la même chaîne. C'est une **configuration**, pas une
donnée : elle se corrige en une minute côté back-office. Mais tant qu'elle
dure, ce service ne choisit pas — il retire l'acteur de la liste, et refuse
l'opération si c'est celui de l'utilisateur connecté.

## Pourquoi aucune contrainte SQL n'est posée ici

Audité : `res.users.dally_ops_cash_actor` ne porte aujourd'hui ni contrainte
ni index, et la colonne n'existe pas encore dans la base de production — le
module n'y est pas installé. Poser une contrainte d'unicité maintenant
n'échouerait sur rien, mais elle transformerait une erreur de saisie
back-office en erreur de migration plus tard, sans rien apporter que cette
résolution ne donne déjà. La détection vit donc dans le service, où elle sait
expliquer ce qui ne va pas.
"""

from odoo import _, api, models

from .ops_errors import DallyOpsConflict, DallyOpsError


def canonique(valeur):
    """La forme sous laquelle deux acteurs se comparent.

    Espaces retirés, casse neutralisée. `casefold` et non `lower` : il traite
    les alphabets que `lower` laisse passer, et deux orthographes qui ne
    diffèrent que par la casse désignent la même personne.
    """
    return (valeur or "").strip().casefold()


class DallyOpsCashActorService(models.AbstractModel):
    _name = "dally.ops.cash.actor.service"
    _description = "Dally Ops — acteurs de caisse"

    # ------------------------------------------------------------------
    # Recensement
    # ------------------------------------------------------------------

    @api.model
    def _comptes_de_caisse(self):
        """Les comptes Ops actifs qui portent un acteur de caisse.

        `all_group_ids` et non `group_ids` : un responsable **implique** le
        logisticien sans porter le groupe directement, et l'oublier le rendrait
        invisible comme destinataire.
        """
        groupe = self.env.ref("dally_ops_mobile.group_dally_ops_logistician")
        comptes = self.env["res.users"].sudo().search([
            ("active", "=", True),
            ("all_group_ids", "in", [groupe.id]),
            ("company_ids", "in", [self.env.company.id]),
            ("dally_ops_cash_actor", "!=", False),
        ])
        return comptes.filtered(lambda compte: canonique(compte.dally_ops_cash_actor))

    @api.model
    def _index_par_acteur(self):
        """Chaque acteur canonique, et les comptes qui le revendiquent."""
        index = {}
        for compte in self._comptes_de_caisse():
            index.setdefault(canonique(compte.dally_ops_cash_actor), []).append(compte)
        return index

    # ------------------------------------------------------------------
    # L'acteur de l'utilisateur connecté
    # ------------------------------------------------------------------

    @api.model
    def current_actor(self):
        """L'acteur de l'utilisateur connecté, ou un refus explicite.

        Deux refus distincts, parce qu'ils appellent deux gestes différents :
        « votre compte n'est pas configuré » se corrige en renseignant un
        champ ; « deux comptes portent votre acteur » se corrige en choisissant
        lequel le garde. Un message unique laisserait le back-office chercher.
        """
        acteur = (self.env.user.dally_ops_cash_actor or "").strip()
        if not acteur:
            raise DallyOpsConflict(
                _("Votre compte n'est pas encore configuré pour les opérations de caisse."),
                code="cash_actor_not_configured")
        porteurs = self._index_par_acteur().get(canonique(acteur), [])
        if len(porteurs) > 1:
            raise DallyOpsConflict(
                _("Plusieurs comptes portent votre acteur de caisse. "
                  "Un responsable doit corriger la configuration."),
                code="cash_actor_configuration_conflict")
        return acteur

    # ------------------------------------------------------------------
    # Les destinataires possibles
    # ------------------------------------------------------------------

    @api.model
    def available_recipients(self):
        """Les acteurs à qui l'utilisateur connecté peut remettre de la caisse.

        L'acteur courant en est retiré — on ne se remet pas à soi-même — et
        tout acteur ambigu aussi : proposer un nom que le serveur refuserait
        ensuite de résoudre ferait échouer la remise après la saisie.
        """
        courant = canonique(self.current_actor())
        acteurs = []
        for cle, porteurs in self._index_par_acteur().items():
            if cle == courant or len(porteurs) != 1:
                continue
            acteurs.append((porteurs[0].dally_ops_cash_actor or "").strip())
        # Trié par la forme canonique : l'ordre affiché ne doit pas dépendre de
        # l'ordre des identifiants de compte.
        return sorted(acteurs, key=canonique)

    @api.model
    def resolve_recipient(self, valeur):
        """Le nom exact d'un destinataire, ou un refus.

        Aucune recherche approchante : ni `ilike`, ni « commence par », ni
        « premier résultat ». Le navigateur renvoie ce que le serveur lui a
        donné, et tout le reste est refusé.
        """
        if not isinstance(valeur, str) or not canonique(valeur):
            raise DallyOpsError(
                _("Ce destinataire n'est pas disponible."),
                code="cash_recipient_not_available", status=422)
        porteurs = self._index_par_acteur().get(canonique(valeur), [])
        if len(porteurs) != 1:
            raise DallyOpsError(
                _("Ce destinataire n'est pas disponible."),
                code="cash_recipient_not_available", status=422)
        return (porteurs[0].dally_ops_cash_actor or "").strip()
