"""
Garde-fou du confinement de `tk_freight`.

## Ce que ce fichier défend

`security/tk_freight_portal_lockdown.xml` retire au groupe portail les droits que
le fournisseur lui accorde. Mais une mise à jour de `tk_freight` seul —
`odoo -u tk_freight` — recharge ses propres fichiers de sécurité et **restaure
les valeurs d'origine**, en silence. Le portail redeviendrait ouvert en lecture
et en écriture sur les documents, colis et factures de tous les clients.

Un fichier de données ne peut pas se défendre contre cela. Ce garde-fou le peut :
il est réévalué au chargement du registre, donc après le rechargement des
données du fournisseur, quel que soit l'ordre.

## Pourquoi il ne se contente pas d'une liste

Vérifier les 26 ACL connues ne protège que du passé. Une version ultérieure du
fournisseur peut ajouter **un modèle**, **une ACL** ou **une route** : une liste
figée les laisserait tous passer, et le garde-fou rassurerait à tort.

L'invariant est donc exprimé sur ce qui doit être vrai, jamais sur ce qui a été
constaté un jour :

* **côté ACL** — les modèles de `tk_freight` sont découverts dynamiquement
  depuis `ir.model.data`, puis on exige *aucun* droit portail sur *aucun* d'eux ;
* **côté routes** — les routes sont découvertes dans les classes de contrôleur
  du fournisseur, puis on exige que *chacune* soit neutralisée par le pont.

## Pourquoi « aucune ACL portail », et pas « aucune écriture »

L'architecture n'a pas besoin d'un accès ORM générique du portail aux modèles
tk : le portail lit des enregistrements Dally, et la lecture technique de tk se
fait en `sudo()` *après* résolution d'un enregistrement autorisé par record rule.
Un droit portail natif, même en lecture seule, serait donc au mieux inutile — et
au pire une surface qu'aucune règle d'enregistrement ne borne, puisque 20 des 26
modèles n'en ont aucune.

L'invariant le plus simple est aussi le plus fort : **zéro**.

## Deux niveaux de sévérité, délibérément différents

À l'installation et à la mise à jour du pont, une violation **fait échouer**
l'opération : c'est le moment où quelqu'un regarde, et où le correctif est
d'ajouter `dally_freight_bridge` à la commande.

Au chargement ordinaire du registre, elle est journalisée en `CRITICAL` sans
lever. Faire échouer un démarrage transformerait une régression de sécurité en
panne totale du back-office, qui est resté sain — un remède pire que le mal. Le
signal doit être impossible à manquer sans être destructeur.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

#: Routes du fournisseur que le pont accepterait de laisser ouvertes.
#: Vide, et destiné à le rester : le portail DallyTrading ne consomme aucune
#: route tk. Toute nouvelle route du fournisseur doit donc être neutralisée.
ROUTES_AUTORISEES = frozenset()


class DallyFreightLockdownGuard(models.AbstractModel):
    """Vérifie que le confinement tient, sur des invariants et non des listes."""

    _name = "dally.freight.lockdown.guard"
    _description = "Garde-fou du confinement tk_freight"

    # ------------------------------------------------------------------
    # Découverte
    # ------------------------------------------------------------------

    @api.model
    def _dally_tk_models(self):
        """Modèles définis **uniquement** par `tk_freight`.

        Le critère est `ir.model.modules == "tk_freight"`, et non la présence
        d'un xmlid du fournisseur. La nuance est décisive : `tk_freight` étend
        `res.partner`, `sale.order`, `account.move` et `stock.picking`, et
        possède donc un xmlid `ir.model` pour chacun. Les retenir ferait tomber
        dans le périmètre les ACL portail **du noyau** — celles qui permettent à
        un client de lire sa propre facture ou son propre bon de livraison.

        Mesuré : le premier critère, trop large, désignait huit modèles dont
        quatre appartenaient au noyau. Les fermer aurait cassé le portail Odoo
        standard sans rien gagner en sécurité.
        """
        modeles = self.env["ir.model"].sudo().search([("model", "!=", False)])
        return {
            modele.model
            for modele in modeles
            if self._dally_est_modele_fournisseur(modele.modules)
        }

    @api.model
    def _dally_est_modele_fournisseur(self, modules):
        """Vrai si le modèle est **défini** par le fournisseur.

        Le critère n'est plus « `modules` vaut exactement tk_freight » : cette
        égalité tenait tant que personne n'étendait un modèle du fournisseur, et
        elle a cédé au premier qui l'a fait. Mesuré : après l'ajout de champs
        publics sur `freight.port`, ses modules valaient
        « dally_freight_routing, tk_freight » et le port sortait du périmètre —
        le garde-fou surveillait 31 modèles au lieu de 32, silencieusement.

        C'est le pire mode de défaillance possible pour un garde-fou : il
        continuait d'annoncer que tout allait bien, sur un ensemble rétréci.

        Le critère est donc : `tk_freight` est présent, et tout le reste nous
        appartient. Les modèles que le fournisseur se contente d'**étendre** —
        `res.partner`, `sale.order`, `account.move`, `stock.picking` — portent
        `base`, `account`, `sale`… et restent exclus, ce qui préserve la raison
        d'être du filtre : ne pas fermer au portail les droits du noyau Odoo sur
        sa propre facture ou son propre bon de livraison.
        """
        presents = {m.strip() for m in (modules or "").split(",") if m.strip()}
        if "tk_freight" not in presents:
            return False
        return all(
            module == "tk_freight" or module.startswith("dally_")
            for module in presents
        )

    @api.model
    def _dally_tk_acl_xmlids(self):
        """Identifiants des ACL déclarées par `tk_freight`.

        Second critère, complémentaire du précédent : une ACL du fournisseur
        est dans le périmètre même si elle porte sur un modèle du noyau. C'est
        ce qui permet de détecter une future ACL vendeur ouvrant, par exemple,
        `res.partner` en écriture au portail.
        """
        donnees = self.env["ir.model.data"].sudo().search(
            [("module", "=", "tk_freight"), ("model", "=", "ir.model.access")]
        )
        return set(donnees.mapped("res_id"))

    # ------------------------------------------------------------------
    # Invariant 1 — aucun droit portail sur un modèle tk
    # ------------------------------------------------------------------

    @api.model
    def _dally_audit_portal_access(self):
        """Retourne les droits portail encore ouverts sur des modèles tk.

        Lit `ir.model.access` en base : c'est le seul état qui compte. Un
        fichier XML correct dans le dépôt ne prouve rien sur l'instance.
        """
        portail = self.env.ref("base.group_portal", raise_if_not_found=False)
        if not portail:
            return []

        modeles_tk = self._dally_tk_models()
        acl_tk = self._dally_tk_acl_xmlids()
        if not modeles_tk and not acl_tk:
            return []

        # Deux critères réunis, chacun couvrant ce que l'autre laisserait
        # passer : un modèle du fournisseur ouvert par n'importe qui, et une
        # ACL du fournisseur portant sur n'importe quel modèle.
        acces = self.env["ir.model.access"].sudo().search(
            [
                ("group_id", "=", portail.id),
                "|",
                ("model_id.model", "in", sorted(modeles_tk)),
                ("id", "in", sorted(acl_tk)),
            ]
        )

        ouverts = []
        for acl in acces:
            accorde = [
                nom
                for nom, valeur in (
                    ("read", acl.perm_read),
                    ("write", acl.perm_write),
                    ("create", acl.perm_create),
                    ("unlink", acl.perm_unlink),
                )
                if valeur
            ]
            if accorde:
                ouverts.append((acl.model_id.model, accorde))
        return sorted(ouverts)

    # ------------------------------------------------------------------
    # Invariant 2 — aucune route tk servie par le fournisseur
    # ------------------------------------------------------------------

    @api.model
    def _dally_audit_tk_routes(self):
        """Retourne les routes tk que le pont ne neutralise pas.

        Python résout une méthode par son **nom** le long du MRO. Le pont
        héritant des classes du fournisseur, une route est neutralisée si et
        seulement si le pont redéfinit la méthode qui la porte. On compare donc
        des noms de méthodes, et non des chemins d'URL : c'est l'implémentation
        qui décide de ce qui est servi.
        """
        try:
            from odoo.addons.tk_freight.controllers import main as tk_main
        except ImportError:  # le fournisseur n'est pas installé
            return []

        from odoo.addons.dally_freight_bridge.controllers import (
            neutralise_tk_routes as pont,
        )

        classes_vendeur = [
            objet
            for objet in vars(tk_main).values()
            if isinstance(objet, type) and objet.__module__ == tk_main.__name__
        ]
        classes_pont = [
            objet
            for objet in vars(pont).values()
            if isinstance(objet, type) and objet.__module__ == pont.__name__
        ]
        neutralisees = {
            nom for classe in classes_pont for nom in vars(classe)
        }

        non_couvertes = []
        for classe in classes_vendeur:
            for nom, methode in vars(classe).items():
                routing = getattr(methode, "original_routing", None) or getattr(
                    methode, "routing", None
                )
                if not routing:
                    continue
                chemins = [
                    chemin
                    for chemin in routing.get("routes", [])
                    if chemin not in ROUTES_AUTORISEES
                ]
                if chemins and nom not in neutralisees:
                    non_couvertes.extend(chemins)

        return sorted(set(non_couvertes))

    # ------------------------------------------------------------------
    # Restitution
    # ------------------------------------------------------------------

    @api.model
    def _dally_audit(self):
        """Retourne `(acl_ouvertes, routes_non_couvertes)`."""
        return self._dally_audit_portal_access(), self._dally_audit_tk_routes()

    @api.model
    def _dally_audit_message(self):
        """Message d'anomalie, ou `None` si le confinement tient."""
        acl, routes = self._dally_audit()
        if not acl and not routes:
            return None

        morceaux = []
        if acl:
            morceaux.append(
                "%d modele(s) tk accessibles au portail : %s"
                % (
                    len(acl),
                    ", ".join(f"{m} ({'+'.join(p)})" for m, p in acl),
                )
            )
        if routes:
            morceaux.append(
                "%d route(s) tk non neutralisees : %s"
                % (len(routes), ", ".join(routes))
            )
        return (
            "CONFINEMENT tk_freight DEFAIT — "
            + " ; ".join(morceaux)
            + ". Cause la plus probable : tk_freight a ete mis a jour seul, "
            "rechargeant ses propres donnees. Correctif : "
            "odoo -u tk_freight,dally_freight_bridge"
        )

    def _register_hook(self):
        """Chargement ordinaire du registre : signaler sans faire tomber."""
        resultat = super()._register_hook()

        anomalie = self._dally_audit_message()
        if anomalie:
            _logger.critical("%s", anomalie)
        else:
            _logger.info(
                "Confinement tk_freight verifie : aucun acces portail et "
                "aucune route ouverte sur %d modeles tk.",
                len(self._dally_tk_models()),
            )
        return resultat


def verifier_confinement(env):
    """Point d'ancrage d'installation et de mise à jour : échouer bruyamment.

    Appelé par `post_init_hook`. C'est le moment où quelqu'un regarde la sortie
    de la commande, et où le correctif tient en un mot ajouté à la ligne de
    commande. Laisser passer ici reviendrait à déployer une ouverture.
    """
    anomalie = env["dally.freight.lockdown.guard"]._dally_audit_message()
    if anomalie:
        _logger.critical("%s", anomalie)
        raise AssertionError(anomalie)
