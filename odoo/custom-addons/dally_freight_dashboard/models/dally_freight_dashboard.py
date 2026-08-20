# -*- coding: utf-8 -*-
"""Les cartes du tableau de bord, et le domaine unique de chacune.

## L'invariant que ce fichier tient

Un tableau de bord ment le jour où un chiffre et l'écran qu'il ouvre ne
décrivent plus le même ensemble. C'est arrivé partout, et toujours de la même
façon : le critère est écrit une fois pour compter, une autre pour filtrer, et
les deux dérivent.

Ici il n'est écrit qu'une fois. `CARTES` associe à chaque code un modèle et un
domaine ; `_compute_count` s'en sert pour compter, `action_open` pour ouvrir.
La parité n'est pas vérifiée, elle est impossible à rompre sans supprimer la
table.

## Compter avec les droits de celui qui regarde

Aucun `sudo`. `search_count` s'exécute comme l'utilisateur courant, donc un
commercial qui ne voit qu'une partie des dossiers voit un chiffre qui
correspond à sa liste. C'est le contraire du tableau de bord du fournisseur,
qui compte tout pour tout le monde.

Et une carte dont le modèle source n'est pas lisible **n'apparaît pas** :
`available` la retire, plutôt que d'afficher un zéro trompeur ou un bouton qui
échouerait au clic.
"""

from odoo import _, api, fields, models

#: Préfixe des services relevant du fret. Repris du pont plutôt que redéfini.
from odoo.addons.dally_freight_bridge.models.freight_mapping import (
    PREFIXE_SERVICE_FRET,
)

#: États d'une demande considérés comme « à qualifier ».
#:
#: `new` seulement : une demande qualifiée ou chiffrée a déjà été prise en
#: main, et la faire réapparaître dans la file d'attente ferait travailler deux
#: fois.
ETATS_A_QUALIFIER = ("new",)

#: États d'une demande déjà travaillée commercialement.
ETATS_COTATION = ("qualified", "quoted")


def _domaine_fret():
    """Demandes relevant du fret, par préfixe de code de service.

    Un `freight_rail` ajouté demain entrera dans le périmètre sans qu'on ait à
    modifier ce fichier — c'est la règle déjà retenue par le pont.
    """
    return [("service_type_id.code", "=like", "%s%%" % PREFIXE_SERVICE_FRET)]


#: Code de carte → (modèle, domaine, intitulé, groupe visuel).
#:
#: L'ordre de ce dictionnaire est celui d'affichage : file d'attente
#: commerciale, puis exécution, puis modes, puis étapes.
CARTES = {
    # ── Pipeline commercial ──
    "quote_requests": (
        "dally.quote.request", _domaine_fret, "Demandes Freight", "pipeline"),
    "to_qualify": (
        "dally.quote.request",
        lambda: _domaine_fret() + [("state", "in", list(ETATS_A_QUALIFIER))],
        "À qualifier", "pipeline"),
    "quotations": (
        "dally.quote.request",
        lambda: _domaine_fret() + [("state", "in", list(ETATS_COTATION))],
        "Cotations", "pipeline"),
    "bookings": (
        "shipment.freight.booking", lambda: [], "Réservations", "pipeline"),

    # ── Exécution ──
    "shipments": ("dally.shipment", lambda: [], "Expéditions", "execution"),

    # ── Modes physiques ──
    "sea": ("dally.shipment", lambda: [("transport_mode", "=", "sea")],
            "Maritime", "mode"),
    "air": ("dally.shipment", lambda: [("transport_mode", "=", "air")],
            "Aérien", "mode"),
    "road": ("dally.shipment", lambda: [("transport_mode", "=", "road")],
             "Routier", "mode"),
    "groupage": ("dally.shipment", lambda: [("transport_mode", "=", "groupage")],
                 "Groupage", "mode"),
    "vehicle": ("dally.shipment", lambda: [("transport_mode", "=", "vehicle")],
                "Véhicules", "mode"),

    # ── Étapes ──
    "in_transit": ("dally.shipment", lambda: [("state", "=", "in_transit")],
                   "En transit", "etape"),
    "arrived": ("dally.shipment", lambda: [("state", "=", "arrived")],
                "Arrivées", "etape"),
    "customs": ("dally.shipment", lambda: [("state", "=", "customs")],
                "Douane", "etape"),
    "available": ("dally.shipment", lambda: [("state", "=", "available")],
                  "Disponibles", "etape"),
    "out_for_delivery": (
        "dally.shipment", lambda: [("state", "=", "out_for_delivery")],
        "En livraison", "etape"),
    "delivered": ("dally.shipment", lambda: [("state", "=", "delivered")],
                  "Livrés", "etape"),
    "cancelled": ("dally.shipment", lambda: [("state", "=", "cancelled")],
                  "Annulés", "etape"),
}


class DallyFreightDashboard(models.Model):
    _name = "dally.freight.dashboard"
    _description = "Carte du tableau de bord Freight"
    _order = "sequence, id"

    code = fields.Char(
        string="Code", required=True, index=True,
        help="Clé dans `CARTES`. C'est elle, et non l'intitulé, qui porte le "
             "domaine : renommer une carte ne change donc jamais ce qu'elle "
             "compte.",
    )
    name = fields.Char(string="Intitulé", required=True, translate=True)
    sequence = fields.Integer(string="Ordre", default=10)
    group = fields.Selection(
        selection=[("pipeline", "Pipeline"), ("execution", "Exécution"),
                   ("mode", "Mode"), ("etape", "Étape")],
        string="Groupe", default="pipeline",
    )

    count = fields.Integer(
        string="Nombre", compute="_compute_count",
        help="Compté avec les droits du lecteur. Le même domaine ouvre la "
             "liste : les deux ne peuvent pas diverger.",
    )
    available = fields.Boolean(
        string="Lisible", compute="_compute_available",
        search="_search_available",
        help="Faux quand le modèle source n'est pas lisible par cet "
             "utilisateur. La carte disparaît alors : un bouton qui échoue au "
             "clic vaut moins que pas de bouton.",
    )

    _code_uniq = models.Constraint("unique(code)", "Ce code de carte existe déjà.")

    # ------------------------------------------------------------------
    # La source unique
    # ------------------------------------------------------------------

    def _dally_carte(self):
        """(modèle, domaine) de cette carte, ou (None, None) si inconnue."""
        self.ensure_one()
        entree = CARTES.get(self.code)
        if not entree:
            return None, None
        modele, domaine, _libelle, _groupe = entree
        return modele, domaine()

    def _dally_lisible(self, modele):
        """L'utilisateur courant peut-il lire ce modèle ?

        `has_access` plutôt qu'un essai suivi d'un rattrapage : on veut la
        réponse avant de compter, pas après avoir levé.
        """
        if not modele or modele not in self.env:
            return False
        return self.env[modele].has_access("read")

    @api.depends_context("uid", "allowed_company_ids")
    def _compute_count(self):
        for carte in self:
            modele, domaine = carte._dally_carte()
            if not carte._dally_lisible(modele):
                carte.count = 0
                continue
            # Sans `sudo` : le chiffre est celui de cet utilisateur, et les
            # règles d'enregistrement s'y appliquent comme dans la liste.
            carte.count = self.env[modele].search_count(domaine)

    @api.depends_context("uid")
    def _compute_available(self):
        for carte in self:
            modele, _domaine = carte._dally_carte()
            carte.available = carte._dally_lisible(modele)

    def _search_available(self, operator, value):
        """Rend `available` filtrable, pour que l'action masque les cartes.

        Un champ calculé non stocké n'est pas cherchable sans cela, et le
        tableau de bord afficherait des cartes que l'utilisateur ne peut pas
        ouvrir.
        """
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise NotImplementedError(
                _("Only equality on a boolean is supported here."))
        veut_lisible = (operator == "=") == bool(value)
        lisibles = {
            code for code, (modele, _d, _l, _g) in CARTES.items()
            if modele in self.env and self.env[modele].has_access("read")
        }
        cartes = self.search_fetch([], ["code"])
        retenues = [
            carte.id for carte in cartes
            if (carte.code in lisibles) == veut_lisible
        ]
        return [("id", "in", retenues)]

    # ------------------------------------------------------------------
    # Le clic
    # ------------------------------------------------------------------

    def action_open(self):
        """Ouvrir exactement ce que la carte compte.

        Le domaine vient de `CARTES`, comme le compteur. Aucun `sudo` : si
        l'utilisateur n'a pas le droit de lire ce modèle, Odoo refuse
        l'ouverture — mais il n'aurait de toute façon pas vu la carte.
        """
        self.ensure_one()
        modele, domaine = self._dally_carte()
        if not modele:
            raise models.UserError(
                _("Carte inconnue : %s", self.code or ""))
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": modele,
            "view_mode": "list,form",
            "domain": domaine,
            # Pas de `search_default_*` : un filtre par défaut ajouterait un
            # critère invisible et le nombre de lignes ne correspondrait plus
            # au chiffre affiché.
            "context": {},
        }
