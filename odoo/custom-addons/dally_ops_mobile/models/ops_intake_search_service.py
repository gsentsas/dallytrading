# -*- coding: utf-8 -*-
"""Retrouver un dossier au comptoir, à partir de ce que le client dit.

## Pourquoi une recherche séparée du dossier

Lire un dossier et en chercher un ne posent pas la même question. La lecture
part d'une identité connue et refuse tout le reste ; la recherche part d'une
bribe — un nom mal orthographié, les derniers chiffres d'un numéro — et doit
proposer sans jamais déborder de la société de l'opérateur.

## Ce que cette recherche montre, et ce qu'elle ne promet pas

Elle couvre **tous** les dossiers de la société, y compris ceux repris du
classeur historique. Un tel dossier existe : le cacher ferait croire au
comptoir qu'il n'a jamais été enregistré.

Mais la fiche détaillée d'Ops ne sait afficher que les dossiers nés de Dally
Ops. Chaque résultat porte donc `detail_access`, calculé **ici** avec le
domaine de la fiche lui-même — jamais avec une copie. L'interface lit cette
valeur ; elle ne reconstitue aucune règle, et ne peut donc pas se tromper.

## Ce que la référence désigne

`reference` est toujours `external_reference`, la référence globale, et c'est
la seule clé de navigation. `A001` est local à son départ : deux consolidations
en ont chacune un, et composer une URL avec lui ouvrirait le dossier d'un autre
client. `local_reference` est publiée à côté, pour l'œil, jamais pour l'URL.

## Ce qui ne sort jamais

Aucun identifiant de base : ni dans un champ, ni dans un jeton de parcours.
La réponse tient en une page et un booléen.

## La surface d'énumération

Une recherche est une porte. Le rôle, la société, la longueur minimale de la
requête et le plafond de résultats sont imposés ici, dans le service — pas dans
le contrôleur, et surtout pas dans le navigateur.
"""

import re

from odoo import _, api, models
from odoo.fields import Domain

from odoo.addons.dally_crm.models.res_partner import normalize_phone

from .ops_errors import DallyOpsError

#: Une référence locale telle que le serveur les alloue : `A001`, `A012`.
#: Deux caractères suffisent à la reconnaître, et un préfixe de deux
#: caractères ne ramène jamais qu'une poignée de dossiers d'un même départ.
REFERENCE_LOCALE = re.compile(r"^[A-Za-z]\d{1,5}$")

#: En deçà, une requête générique ne cherche plus : elle énumère.
LONGUEUR_MINIMALE = 3

#: Au-delà, ce n'est plus une recherche de comptoir.
LONGUEUR_MAXIMALE = 64

LIMITE_DEFAUT = 20
LIMITE_MAXIMALE = 50


class DallyOpsIntakeSearchService(models.AbstractModel):
    _name = "dally.ops.intake.search.service"
    _description = "Dally Ops — recherche de dossier"

    @api.model
    def search_intakes(self, q, *, limit=None):
        """Les dossiers de la société qui répondent à cette bribe.

        Une seule page, et un drapeau qui dit s'il y en aurait davantage.

        ## Pourquoi pas une pagination par curseur

        Un curseur suppose une clé de tri stable et unique sur l'ensemble
        parcouru. `id` en est une, mais c'est un identifiant de base : le
        publier — même encodé — le ferait sortir vers le navigateur, et un
        encodage n'est pas une protection.

        `external_reference` serait la bonne clé métier : elle porte une
        contrainte `UNIQUE(company_id, external_reference)` et un index. Mais
        PostgreSQL ne contraint pas les NULL, et des dossiers sans référence
        existent — mesuré en production. Deux d'entre eux, remontés par nom ou
        par téléphone, se départageraient mal : une page pourrait en perdre un
        ou le servir deux fois.

        Une recherche de comptoir se raffine ; elle ne se feuillette pas. On
        rend donc les cinquante premiers et on dit qu'il y en a d'autres.
        """
        self._exiger_role_ops()
        requete = self._valider_requete(q)
        limite = self._valider_limite(limit)

        domaine = Domain.AND([
            # La société du dossier, strictement. Un partenaire partagé entre
            # deux sociétés ne doit jamais faire remonter le dossier de
            # l'autre : c'est le dossier qui décide, pas son client.
            Domain([("company_id", "=", self.env.company.id)]),
            self._domaine_de_recherche(requete),
        ])

        Dossier = self.env["dally.shipment"].sudo()
        # Un de plus que demandé : c'est ce surplus qui dit qu'il en reste,
        # sans compter la table entière. Le tri par `id` décroissant place les
        # dossiers les plus récents en tête ; cet identifiant sert au tri et
        # ne quitte jamais le serveur.
        dossiers = Dossier.search(domaine, order="id desc", limit=limite + 1)
        encore = len(dossiers) > limite
        page = dossiers[:limite]

        ouvrables = self._references_ouvrables(page)
        return {
            "items": [self._en_dto(dossier, ouvrables) for dossier in page],
            # Un booléen, et rien d'autre : de quoi inviter l'opérateur à
            # préciser sa recherche, sans lui remettre une clé de parcours.
            "has_more": encore,
        }

    # ------------------------------------------------------------------
    # Portée
    # ------------------------------------------------------------------

    @api.model
    def _exiger_role_ops(self):
        """Le service décide lui-même pour qui il travaille.

        Le contrôleur vérifie déjà le rôle pour choisir le code HTTP ; cette
        seconde vérification garantit que le privilège reste hors d'atteinte
        quel que soit l'appelant.
        """
        if not self.env["res.users"]._dally_ops_role():
            raise DallyOpsError(
                _("Accès refusé."), code="ops_forbidden", status=403)

    @api.model
    def _references_ouvrables(self, dossiers):
        """Les dossiers de cette page que la fiche Ops sait afficher.

        Une seconde requête bornée aux dossiers déjà trouvés, plutôt qu'un test
        par dossier : la règle reste celle de la fiche, et le coût reste de deux
        requêtes quelle que soit la taille de la page.
        """
        if not dossiers:
            return set()
        domaine = self.env["dally.ops.intake.line.service"]._domaine_dossier_ops()
        compatibles = self.env["dally.shipment"].sudo().search(
            domaine + [("id", "in", dossiers.ids)])
        return set(compatibles.ids)

    # ------------------------------------------------------------------
    # Ce que la requête veut dire
    # ------------------------------------------------------------------

    @api.model
    def _valider_requete(self, q):
        if not isinstance(q, str) or not q.strip():
            raise DallyOpsError(
                _("Indiquez ce que vous cherchez."), code="search_query_required")
        requete = q.strip()
        if len(requete) > LONGUEUR_MAXIMALE:
            raise DallyOpsError(
                _("Recherche trop longue."), code="search_query_too_long")
        return requete

    @api.model
    def _valider_limite(self, limit):
        if limit is None:
            return LIMITE_DEFAUT
        try:
            limite = int(limit)
        except (TypeError, ValueError):
            raise DallyOpsError(
                _("Nombre de résultats invalide."), code="search_limit_invalid")
        if limite < 1 or limite > LIMITE_MAXIMALE:
            raise DallyOpsError(
                _("Nombre de résultats invalide."), code="search_limit_invalid")
        return limite

    @api.model
    def _domaine_de_recherche(self, requete):
        """Ce que la bribe désigne : un numéro, une référence, ou un nom.

        Trois formes, essayées dans cet ordre, plutôt qu'un `ilike` sur vingt
        colonnes : chacune vise les champs où la réponse peut réellement se
        trouver, et une seule d'entre elles s'exécute.
        """
        telephone = normalize_phone(requete)
        if telephone:
            return Domain([
                ("partner_id", "in", self._partenaires_par_telephone(telephone)),
            ])

        if REFERENCE_LOCALE.match(requete):
            # Un préfixe : le comptoir tape `A0` puis affine.
            return Domain.OR([
                Domain([("collection_local_ref", "=ilike", requete + "%")]),
                Domain([("external_reference", "=ilike", requete + "%")]),
            ])

        if len(requete) < LONGUEUR_MINIMALE:
            raise DallyOpsError(
                _("Précisez votre recherche."), code="search_query_too_short")

        return Domain.OR([
            Domain([("external_reference", "=ilike", requete + "%")]),
            Domain([("collection_local_ref", "=ilike", requete)]),
            Domain([("partner_id.name", "ilike", requete)]),
        ])

    @api.model
    def _partenaires_par_telephone(self, empreinte):
        """Les partenaires dont le numéro se termine par cette empreinte.

        Même convention que la recherche client : comparaison SQL sur les
        chiffres du champ brut, parce que `phone_sanitized` est vide sur les
        fiches anciennes. Aucune écriture : `res.partner` n'est jamais
        normalisé, seulement comparé.

        Aucun filtre de société ici : c'est le **dossier** qui porte
        l'isolation, et un partenaire partagé ne doit pas la contourner.
        """
        self.env["res.partner"].flush_model(["phone", "dally_whatsapp", "active"])
        self.env.cr.execute(
            """
            SELECT id
              FROM res_partner
             WHERE active IS TRUE
               AND (
                    RIGHT(regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g'),
                          %s) = %s
                 OR RIGHT(regexp_replace(COALESCE(dally_whatsapp, ''),
                          '[^0-9]', '', 'g'), %s) = %s
               )
            """,
            [len(empreinte), empreinte, len(empreinte), empreinte],
        )
        return [ligne[0] for ligne in self.env.cr.fetchall()]

    # ------------------------------------------------------------------
    # Ce que le comptoir voit
    # ------------------------------------------------------------------

    @api.model
    def _en_dto(self, dossier, ouvrables):
        """Assez pour reconnaître le dossier, rien de plus.

        Ni identifiant Odoo, ni clé de source, ni clé de ligne : la navigation
        se fait par la référence globale, et le reste ne regarde que le serveur.
        """
        ouvrable = dossier.id in ouvrables
        return {
            # Toujours la référence globale : c'est elle, et elle seule, qui
            # ouvre une fiche sans ambiguïté.
            "reference": dossier.external_reference or "",
            "local_reference": dossier.collection_local_ref or "",
            "customer_name": dossier.partner_id.name or "",
            "customer_phone": dossier.partner_id.phone or "",
            "state": dossier.state or "",
            "transport_mode": dossier.transport_mode or "",
            "consolidation_reference": (
                dossier.intake_consolidation_id.name
                or dossier.consolidation_id.name or ""),
            "received_on": self._date(
                dossier.goods_received_on or dossier.request_date),
            # La décision d'ouverture appartient au serveur. L'interface la
            # lit ; elle ne redéduit jamais le domaine de la fiche.
            "detail_access": "full" if ouvrable else "unavailable",
            "detail_access_reason": None if ouvrable else "legacy_not_supported",
        }

    @staticmethod
    def _date(valeur):
        return valeur.isoformat() if valeur else ""
