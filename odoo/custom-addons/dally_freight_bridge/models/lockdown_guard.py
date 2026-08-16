"""
Garde-fou du confinement de `tk_freight`.

## Le problème que ce fichier résout

`security/tk_freight_portal_lockdown.xml` remet à zéro les 26 droits que le
fournisseur accorde au groupe portail. Mais une mise à jour de `tk_freight`
seul — `odoo -u tk_freight` — recharge ses propres fichiers de sécurité et
**restaure les valeurs d'origine**. Le confinement disparaîtrait alors sans
qu'aucun message ne le signale : le portail redeviendrait ouvert en lecture et
en écriture sur les documents, colis et factures de tous les clients.

Un fichier de données ne peut pas se défendre contre cela. Ce garde-fou le
peut : il est réévalué au chargement du registre, donc après le rechargement
des données du fournisseur, quel que soit l'ordre.

## Ce qu'il fait

Il vérifie l'état réel en base — pas le contenu des fichiers — et journalise en
`CRITICAL` chaque droit rouvert. Il ne lève pas d'exception : faire échouer le
démarrage d'Odoo transformerait une régression de sécurité en panne totale, ce
qui est un remède pire que le mal quand le back-office, lui, reste sain. Le
signal doit être impossible à manquer sans être destructeur.

Le test `tests/test_tk_lockdown.py` transforme la même vérification en échec
dur, là où c'est le bon endroit pour échouer.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

#: Modèles que `tk_freight` ouvre au groupe portail, et que le pont referme.
#: La liste est explicite plutôt que déduite d'un préfixe : un modèle ajouté par
#: une version ultérieure du fournisseur doit être *constaté*, pas absorbé
#: silencieusement par un motif trop large.
TK_PORTAL_MODELS = (
    "booking.line",
    "booking.order.line",
    "certificate.type",
    "freight.airline",
    "freight.documents",
    "freight.frequent.route",
    "freight.incoterms",
    "freight.move.type",
    "freight.multiple.invoice",
    "freight.package",
    "freight.port",
    "freight.route",
    "freight.service",
    "freight.shipment",
    "freight.shipment.stages",
    "freight.vessel",
    "shipment.freight.booking",
    "shipment.invoice",
    "shipment.item",
    "shipment.location",
    "shipment.location.activity",
    "shipment.package.line",
    "shipment.quotation",
    "shipment.tracking",
    "tracking.template",
    "tracking.template.line",
)


class DallyFreightLockdownGuard(models.AbstractModel):
    """Vérifie, au chargement du registre, que le confinement tient."""

    _name = "dally.freight.lockdown.guard"
    _description = "Garde-fou du confinement tk_freight"

    @api.model
    def _dally_audit_portal_access(self):
        """Retourne les accès portail encore ouverts sur les modèles tk.

        Lit `ir.model.access` en base : c'est le seul état qui compte. Un
        fichier XML correct dans le dépôt ne prouve rien sur l'instance.
        """
        portal = self.env.ref("base.group_portal", raise_if_not_found=False)
        if not portal:
            return []

        access = self.env["ir.model.access"].sudo().search(
            [
                ("group_id", "=", portal.id),
                ("model_id.model", "in", list(TK_PORTAL_MODELS)),
            ]
        )

        ouverts = []
        for acl in access:
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

    @api.model
    def _dally_audit_neutralised_routes(self):
        """Retourne les routes tk encore servies par le contrôleur d'origine.

        Une route est considérée fermée si le point d'entrée résolu appartient
        au pont. Comparer les noms de classe plutôt que les chemins : c'est
        l'implémentation qui compte, pas la présence de l'URL dans la table.
        """
        try:
            from odoo.addons.tk_freight.controllers import main as tk_main
        except ImportError:
            return []

        ouvertes = []
        for classe in (tk_main.BookingsCustom, tk_main.FreightCustomerPortal):
            for nom in dir(classe):
                methode = getattr(classe, nom, None)
                routing = getattr(methode, "original_routing", None) or getattr(
                    methode, "routing", None
                )
                if not routing or "routes" not in routing:
                    continue
                # `type(self).__mro__` du contrôleur effectif n'est pas
                # accessible ici ; on se rabat sur le module de définition de
                # la méthode telle qu'elle sera résolue par héritage.
                effectif = getattr(methode, "__module__", "")
                if not effectif.startswith("odoo.addons.dally_freight_bridge"):
                    ouvertes.extend(routing["routes"])
        return sorted(set(ouvertes))

    def _register_hook(self):
        """Point d'accroche appelé après chaque chargement du registre."""
        resultat = super()._register_hook()

        ouverts = self._dally_audit_portal_access()
        if ouverts:
            _logger.critical(
                "CONFINEMENT tk_freight DEFAIT — le groupe portail a de nouveau "
                "acces a %d modele(s) fret : %s. Cause la plus probable : "
                "tk_freight a ete mis a jour seul, rechargeant ses propres ACL. "
                "Correctif : odoo -u tk_freight,dally_freight_bridge",
                len(ouverts),
                ", ".join(f"{modele} ({'+'.join(perms)})" for modele, perms in ouverts),
            )
        else:
            _logger.info(
                "Confinement tk_freight verifie : aucun acces portail sur les "
                "%d modeles fret.",
                len(TK_PORTAL_MODELS),
            )

        return resultat
