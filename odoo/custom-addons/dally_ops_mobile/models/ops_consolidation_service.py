# -*- coding: utf-8 -*-
"""Les départs sur lesquels un logisticien peut encore déposer un colis.

## Pourquoi un privilège serveur, et pourquoi ici

Le compte Ops ne lit **aucun** modèle métier : c'est l'architecture retenue à
l'étape précédente, et elle est mesurée par un test qui compte les modèles
accessibles. Un logisticien ne peut donc pas interroger
``dally.freight.consolidation`` — et ne le pourra pas.

Il faut pourtant qu'il voie ses départs. Deux chemins existaient :

1. lui ouvrir une ACL en lecture sur la consolidation ;
2. lui donner **une réponse**, calculée par le serveur, sans lui donner le
   **modèle**.

Le premier chemin ouvre 40 champs pour en montrer 8, et tout ce qu'on ajoutera
plus tard au modèle sera ouvert avec. Le second demande un privilège, mais un
privilège dont on peut écrire la portée exacte — c'est ce que fait ce fichier.

## La frontière de privilège, précisément

- **Pourquoi** : le compte Ops n'a volontairement aucune ACL métier.
- **Sur quoi** : ``dally.freight.consolidation``, et rien d'autre.
- **Pour quelle opération** : une recherche et une lecture, jamais une
  écriture.
- **Sous quel domaine** : société courante de l'utilisateur, enregistrement
  actif, état ``collecting``, mode aérien ou maritime.

Il n'existe pas — et il ne doit pas exister — de méthode générique du genre
``ops_sudo(nom_de_modele, domaine)``. Une telle méthode déplacerait la décision
de sécurité vers l'appelant, c'est-à-dire, tôt ou tard, vers un contrôleur.
Ici le domaine est écrit dans le service : le navigateur ne peut ni le fournir,
ni l'élargir, ni le contourner.

## Pourquoi le routier est absent

La phase 1 de Dally Ops ne traite que des colis. Un départ routier existe bien
dans le modèle, mais il ne se réceptionne pas au comptoir ; l'afficher
inviterait à y enregistrer un colis qui n'y a pas sa place.

## Pourquoi la référence et non l'identifiant

Le DTO expose ``AIR-DSS-CDG-2026-002`` et jamais ``id: 3``. Une référence
métier est stable, lisible sur un bordereau, et déjà comprise par le service de
synchronisation, qui accepte ``planned_consolidation_ref``. Un identifiant
interne, lui, transformerait cette route en instrument d'énumération : il suffit
de compter pour deviner ce qui existe.
"""

from odoo import _, api, models
from odoo.exceptions import AccessError


class DallyOpsConsolidationService(models.AbstractModel):
    """Service de lecture, sans table ni ACL.

    Un modèle abstrait n'a pas d'enregistrements, donc pas de droits d'accès à
    accorder : appeler ce service n'ouvre rien. C'est le service lui-même qui
    décide ce qu'il accepte de faire, et pour qui.
    """

    _name = "dally.ops.consolidation.service"
    _description = "Dally Ops — départs ouverts à la réception"

    #: Le seul état où un colis peut encore rejoindre un départ.
    ETAT_OUVERT = "collecting"

    #: Les modes que la phase 1 sait réceptionner.
    MODES_COLIS = ("air", "sea")

    @api.model
    def list_open_for_intake(self):
        """Les départs ouverts, en DTO.

        Renvoie des dictionnaires, jamais des enregistrements Odoo. Le
        contrôleur ne reçoit donc rien sur quoi il pourrait rebondir : ni
        ``.sudo()``, ni un champ oublié, ni une relation à suivre.
        """
        self._exiger_role_ops()
        departs = self._rechercher_departs_ouverts()
        return sorted((self._en_dto(depart) for depart in departs), key=self._cle_de_tri)

    # ------------------------------------------------------------------
    # Autorisation
    # ------------------------------------------------------------------

    @api.model
    def _exiger_role_ops(self):
        """Le service décide lui-même pour qui il travaille.

        Le contrôleur vérifie déjà le rôle pour choisir le code HTTP ; cette
        seconde vérification n'est pas une redite. Elle garantit que le
        privilège reste hors d'atteinte quel que soit l'appelant — un autre
        contrôleur, une action serveur, un jour un travail planifié.
        """
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))

    # ------------------------------------------------------------------
    # Le seul privilège du module
    # ------------------------------------------------------------------

    @api.model
    def _rechercher_departs_ouverts(self):
        """L'unique ``sudo`` de Dally Ops, et sa portée entière.

        Le domaine est construit ici, à partir de la seule société de
        l'utilisateur connecté. Aucun paramètre d'appel n'entre dans cette
        méthode : il n'y a donc rien à injecter, rien à élargir, et rien à
        oublier de valider.
        """
        domaine = [
            ("company_id", "=", self.env.company.id),
            # Odoo exclut déjà les enregistrements archivés d'une recherche
            # ordinaire. La clause est écrite quand même : elle survit à un
            # `active_test=False` posé par un appelant futur, et elle dit à la
            # lecture ce que la portée du privilège autorise exactement.
            ("active", "=", True),
            ("state", "=", self.ETAT_OUVERT),
            ("transport_mode", "in", list(self.MODES_COLIS)),
        ]
        return self.env["dally.freight.consolidation"].sudo().search(domaine, order="name")

    # ------------------------------------------------------------------
    # Mise en forme
    # ------------------------------------------------------------------

    @api.model
    def _en_dto(self, consolidation):
        """Ce que le logisticien a besoin de savoir, et rien de plus.

        Le contrat des valeurs manquantes est délibérément asymétrique :

        - un texte absent devient ``""``, parce qu'il s'affiche à sa place et
          qu'une chaîne vide ne s'affiche pas ;
        - une date absente devient ``null``, parce qu'inventer une date de
          départ serait un mensonge, et parce que ``""`` obligerait chaque
          lecteur à distinguer « pas de date » d'une date illisible.
        """
        return {
            "reference": consolidation.name,
            "transport_mode": consolidation.transport_mode,
            "direction": consolidation.direction,
            "origin": {
                "country_code": consolidation.origin_country_id.code or "",
                "city": consolidation.origin_city or "",
                "location": consolidation.origin_location or "",
            },
            "destination": {
                "country_code": consolidation.destination_country_id.code or "",
                "city": consolidation.destination_city or "",
                "location": consolidation.destination_location or "",
            },
            "collection_close_on": self._en_date(consolidation.collection_close_on),
            "scheduled_departure": self._en_horodatage(consolidation.scheduled_departure),
        }

    @staticmethod
    def _en_date(valeur):
        """``YYYY-MM-DD``, ou ``None``."""
        return valeur.isoformat() if valeur else None

    @staticmethod
    def _en_horodatage(valeur):
        """ISO 8601 en UTC, suffixe ``Z`` explicite, ou ``None``.

        Odoo conserve les datetimes en UTC sans fuseau. Les renvoyer tels quels
        laisserait le navigateur les interpréter dans son propre fuseau : un
        départ de 10 h deviendrait 12 h à Paris. Le ``Z`` lève l'ambiguïté.
        """
        return valeur.strftime("%Y-%m-%dT%H:%M:%SZ") if valeur else None

    @staticmethod
    def _cle_de_tri(dto):
        """Les collectes qui ferment bientôt d'abord, les sans-date à la fin.

        Le tri se fait ici et non en SQL : l'ordre des valeurs nulles dépend du
        moteur, et un ordre « à peu près » n'est pas testable. Les chaînes ISO
        se comparent dans l'ordre chronologique, ce qui évite de reconvertir.
        """
        fermeture = dto["collection_close_on"]
        depart = dto["scheduled_departure"]
        return (
            fermeture is None,
            fermeture or "",
            depart is None,
            depart or "",
            dto["reference"],
        )
