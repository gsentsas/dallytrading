# -*- coding: utf-8 -*-
"""Retrouver un client sans pouvoir parcourir le fichier clients.

## Pourquoi pas de recherche par nom

Le CRM tient déjà cette règle et l'explique : « a first name and last name are
never matched on: homonyms are common and a false positive would attach one
person's request to another's file ». Elle vaut ici pour une raison de plus —
une recherche par nom, même honnête, est aussi un moyen de feuilleter le
fichier clients depuis un téléphone d'entrepôt. « Diop » suffirait.

Le geste de terrain n'en a pas besoin : « quel est votre numéro de téléphone ? »
est ce qu'on demande au comptoir, et c'est exactement ce que cette recherche
accepte.

## Pourquoi jamais la première correspondance

`_dally_find_existing` renvoie *une* correspondance — la meilleure selon son
ordre de fiabilité. C'est le bon comportement quand il s'agit de **rattacher**
une demande à un dossier : au pire on se trompe de fiche et un humain corrige.

Ici, ce n'est pas ce qui se joue. Renvoyer la première fiche de deux, c'est
montrer le nom, le téléphone et l'adresse de quelqu'un qui n'est pas devant le
comptoir. Alors deux correspondances valent **refus**, jamais choix. C'est la
même prudence que le repli téléphonique de Freight, qui ne relie que lorsqu'il
existe exactement une correspondance.

## Portée du privilège

- **Pourquoi** : le compte Ops n'a volontairement aucune ACL métier.
- **Sur quoi** : `res.partner` en lecture seule, `dally.ops.customer.handle`
  en lecture et création.
- **Opérations** : une recherche exacte par empreinte téléphonique ou par
  adresse électronique ; la lecture de six champs ; la pose d'un jeton.
- **Domaine** : partenaire actif, société courante ou partenaire global.

Aucune écriture sur `res.partner`. Si la fiche porte `CLIENT@EXAMPLE.COM` et
qu'on cherche `client@example.com`, on la trouve et on ne la corrige pas :
« corriger » au passage transformerait une lecture en modification silencieuse
du fichier clients par un téléphone.
"""

import logging

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.dally_crm.models.res_partner import (
    PHONE_SIGNIFICANT_DIGITS,
    normalize_email,
    normalize_phone,
)

_logger = logging.getLogger(__name__)

#: Les seuls critères acceptés. Tout autre champ fait échouer la requête.
CRITERES = ("phone", "email")


class DallyOpsCustomerService(models.AbstractModel):
    """Service de recherche client, sans table ni ACL."""

    _name = "dally.ops.customer.service"
    _description = "Dally Ops — recherche client"

    # ------------------------------------------------------------------
    # Entrée publique
    # ------------------------------------------------------------------

    @api.model
    def search_unique(self, criteres):
        """Résout un critère unique en zéro, un, ou « plusieurs ».

        Renvoie un dictionnaire, jamais un enregistrement : le contrôleur n'a
        donc rien sur quoi rebondir pour lire un champ de plus.
        """
        self._exiger_role_ops()
        champ, valeur = self._critere_unique(criteres)

        partenaires = (
            self._chercher_par_telephone(valeur) if champ == "phone"
            else self._chercher_par_email(valeur)
        )

        if len(partenaires) == 0:
            return {"status": "not_found", "customer": None}
        if len(partenaires) > 1:
            # Aucune donnée du client : deux fiches veulent dire qu'on ignore
            # laquelle est devant le comptoir.
            return {"status": "ambiguous", "customer": None}
        return {"status": "match", "customer": self._en_dto(partenaires)}

    # ------------------------------------------------------------------
    # Validation de la demande
    # ------------------------------------------------------------------

    @api.model
    def _critere_unique(self, criteres):
        """Exactement un critère connu, sinon la requête est invalide.

        Refuser les clés inconnues n'est pas du pédantisme : accepter
        silencieusement `{"name": "Mamadou"}` laisserait croire à l'appelant
        qu'il a cherché par nom, alors qu'il aurait cherché sur rien.
        """
        if not isinstance(criteres, dict):
            raise UserError(_("Requête de recherche invalide."))

        inconnus = set(criteres) - set(CRITERES)
        if inconnus:
            raise UserError(_("Critère de recherche non pris en charge."))

        fournis = [champ for champ in CRITERES if criteres.get(champ)]
        if len(fournis) != 1:
            raise UserError(_("Fournissez exactement un critère de recherche."))

        champ = fournis[0]
        brut = criteres[champ]
        if not isinstance(brut, str):
            raise UserError(_("Critère de recherche invalide."))

        if champ == "phone":
            valeur = normalize_phone(brut)
            if not valeur:
                # Moins de neuf chiffres : « 77 » rapprocherait la moitié du
                # fichier. Mieux vaut refuser que répondre n'importe quoi.
                raise UserError(
                    _("Numéro de téléphone incomplet : %(n)s chiffres au minimum.",
                      n=PHONE_SIGNIFICANT_DIGITS))
        else:
            valeur = normalize_email(brut)
            if not valeur or "@" not in valeur:
                raise UserError(_("Adresse électronique invalide."))

        return champ, valeur

    @api.model
    def _exiger_role_ops(self):
        """Le service décide lui-même pour qui il travaille."""
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))

    # ------------------------------------------------------------------
    # Les recherches privilégiées
    # ------------------------------------------------------------------

    @api.model
    def _chercher_par_telephone(self, empreinte):
        """Les partenaires dont le numéro se termine par cette empreinte.

        La comparaison se fait en SQL sur les chiffres du champ brut, comme le
        fait déjà le repli téléphonique de Freight, et pour la même raison :
        `phone_sanitized` est vide sur les fiches anciennes, et une recherche
        qui dépend de lui rate silencieusement les clients de longue date.

        `LIMIT 3` suffit à distinguer les trois cas — aucun, un seul,
        plusieurs. Ramener davantage ne servirait qu'à charger en mémoire des
        fiches qu'on a justement décidé de ne pas montrer.
        """
        self.env.cr.execute(
            """
            SELECT id
              FROM res_partner
             WHERE active IS TRUE
               AND (company_id IS NULL OR company_id = %s)
               AND (
                    RIGHT(regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g'), %s) = %s
                 OR RIGHT(regexp_replace(COALESCE(dally_whatsapp, ''), '[^0-9]', '', 'g'), %s) = %s
               )
             ORDER BY id
             LIMIT 3
            """,
            [self.env.company.id,
             PHONE_SIGNIFICANT_DIGITS, empreinte,
             PHONE_SIGNIFICANT_DIGITS, empreinte],
        )
        return self.env["res.partner"].sudo().browse(
            [ligne[0] for ligne in self.env.cr.fetchall()])

    @api.model
    def _chercher_par_email(self, email):
        """Les partenaires dont l'adresse est exactement celle-ci.

        `lower(email) = %s` et non `ilike` : l'opérateur `ilike` d'Odoo
        interprète `%` et `_` comme des jokers, si bien qu'une recherche sur
        `a%@example.com` ramènerait tout un domaine. Une comparaison d'égalité
        n'a pas de jokers à échapper.
        """
        self.env.cr.execute(
            """
            SELECT id
              FROM res_partner
             WHERE active IS TRUE
               AND (company_id IS NULL OR company_id = %s)
               AND lower(email) = %s
             ORDER BY id
             LIMIT 3
            """,
            [self.env.company.id, email],
        )
        return self.env["res.partner"].sudo().browse(
            [ligne[0] for ligne in self.env.cr.fetchall()])

    # ------------------------------------------------------------------
    # La référence opaque
    # ------------------------------------------------------------------

    @api.model
    def get_or_create_handle(self, partenaire):
        """Le jeton du client, posé une seule fois.

        Deux téléphones peuvent chercher le même client à la même seconde. La
        contrainte d'unicité rend la course inoffensive : on tente la création
        dans un point de sauvegarde, et si la base refuse, on relit ce que
        l'autre vient d'écrire. Une course de création ne doit jamais devenir
        une erreur 500 devant un client qui attend.
        """
        Handle = self.env["dally.ops.customer.handle"].sudo()
        societe = self.env.company

        existant = Handle.search(
            [("partner_id", "=", partenaire.id), ("company_id", "=", societe.id)], limit=1)
        if existant:
            return existant.token

        try:
            with self.env.cr.savepoint():
                return Handle.create({
                    "partner_id": partenaire.id,
                    "company_id": societe.id,
                }).token
        except Exception:
            # Le point de sauvegarde a annulé notre insertion ; la ligne de
            # l'autre transaction, elle, tient.
            _logger.info("Reference client Ops deja posee par une transaction concurrente.")

        rattrapage = Handle.search(
            [("partner_id", "=", partenaire.id), ("company_id", "=", societe.id)], limit=1)
        if not rattrapage:
            raise UserError(_("Impossible de préparer la référence client."))
        return rattrapage.token

    # ------------------------------------------------------------------
    # Mise en forme
    # ------------------------------------------------------------------

    @api.model
    def _en_dto(self, partenaire):
        """Six champs, et pas un de plus.

        Ni solde, ni factures, ni étiquettes, ni commercial, ni notes : rien de
        tout cela n'aide à savoir si la personne devant le comptoir est bien
        celle de la fiche.
        """
        return {
            "reference": self.get_or_create_handle(partenaire),
            "name": partenaire.name or "",
            "phone": partenaire.phone or "",
            "email": partenaire.email or "",
            "address": self._en_adresse(partenaire),
            "customer_type": "business" if partenaire.is_company else "individual",
        }

    @staticmethod
    def _en_adresse(partenaire):
        """Une seule chaîne, lisible à voix haute.

        Rendre `street`, `street2`, `zip`, `city` séparément exposerait la
        structure interne de `res.partner` sans rien apporter : l'opérateur lit
        l'adresse pour la confirmer avec le client, il ne la saisit pas.
        """
        rue = ", ".join(part for part in (partenaire.street, partenaire.street2) if part)
        ville = " ".join(part for part in (partenaire.zip, partenaire.city) if part)
        pays = partenaire.country_id.name or ""
        return ", ".join(part for part in (rue, ville, pays) if part)
