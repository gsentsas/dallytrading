# -*- coding: utf-8 -*-
"""La référence Wave d'un encaissement, et la note du comptoir.

## Pourquoi deux champs et pas un modèle

`dally.freight.collection` porte déjà tout le reste : le dossier, le client et
la facture par relation **stockée et en lecture seule** depuis le dossier, le
montant, la devise, la date, le moyen, l'encaisseur, l'état et une clé métier
unique. Un second modèle de paiement dupliquerait cela — et deux systèmes de
paiement finissent toujours par diverger sur le montant qui compte.

Il manquait exactement deux choses au flux Wave : le numéro que l'opérateur
lit sur son téléphone, et une ligne libre pour ce qui ne rentre nulle part.

## Pourquoi la référence Wave est facultative

Parce qu'elle l'est dans la vie réelle. Un transfert reçu se voit dans
l'application Wave avant que son identifiant soit recopiable ; exiger le
numéro bloquerait un encaissement qui a bel et bien eu lieu. Le principe tenu
depuis l'étape 9 vaut ici : l'argent reçu ne se perd jamais pour un défaut de
saisie.

## Pourquoi elle est unique quand elle est fournie

Un même transfert Wave ne peut pas payer deux dossiers. Recopier le numéro
précédent est l'erreur de comptoir la plus facile à commettre — deux dossiers
du même client, deux minutes d'écart — et la plus pénible à démêler ensuite,
puisqu'elle ne se voit qu'au rapprochement. La base la refuse.

L'unicité est portée par la société : deux sociétés distinctes n'ont aucune
raison de partager un espace de numéros. PostgreSQL laisse coexister autant de
`NULL` qu'il le faut, si bien que la contrainte ne gêne jamais les
encaissements sans référence.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DallyFreightCollection(models.Model):
    _inherit = "dally.freight.collection"

    wave_reference = fields.Char(
        string="Référence Wave", copy=False, index=True,
        help="Identifiant du transfert lu dans l'application Wave. "
             "Facultatif : un encaissement réellement reçu ne doit pas être "
             "refusé faute de numéro recopiable.")
    ops_note = fields.Char(
        string="Note comptoir", copy=False,
        help="Précision libre saisie au comptoir. N'entre dans aucun calcul.")

    _wave_reference_unique = models.Constraint(
        "UNIQUE(company_id, wave_reference)",
        "Cette référence Wave a déjà été utilisée pour un autre encaissement.")

    @api.constrains("wave_reference")
    def _check_wave_reference_not_blank(self):
        """Une suite d'espaces n'est pas une référence.

        L'enregistrer ferait paraître le champ rempli, et la contrainte
        d'unicité refuserait alors le deuxième encaissement sans référence de
        la société — pour une valeur que personne n'a saisie.
        """
        for collection in self:
            valeur = collection.wave_reference
            if valeur is not False and not (valeur or "").strip():
                raise ValidationError(
                    "La référence Wave ne peut pas être vide. "
                    "Laissez le champ non renseigné.")
