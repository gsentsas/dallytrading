"""
Publication contrôlée d'un document opérationnel vers l'espace client.

```
freight.documents            stockage opérationnel du fournisseur
        │                    (jamais lisible par le portail)
        │  décision explicite d'un utilisateur interne
        ▼
dally.portal.document        publication client
        │                    (record rule sur commercial_partner_id)
        ▼
espace client                téléchargement autorisé
```

## Rien n'est publié tout seul

La synchronisation tk → Dally ne touche pas aux documents. Un document déposé
par l'exploitation dans le dossier opérationnel reste invisible du client tant
qu'un utilisateur interne n'a pas décidé de le publier.

C'est le même principe que pour les événements, et pour la même raison : une
publication accidentelle est irrattrapable. Un connaissement peut être partagé ;
une facture fournisseur, une note d'arbitrage ou un échange avec un transitaire
ne le peuvent pas — et rien, dans un fichier binaire, ne permet de les
distinguer automatiquement.

## Pourquoi il n'y a pas de whitelist par type

Le cahier des charges prévoyait d'autoriser certains types — B/L, AWB, CMR,
packing list. L'audit du fournisseur montre que ce n'est pas implémentable
aujourd'hui, et il faut le dire plutôt que de simuler :

* `freight.documents` porte `type_id` vers `certificate.type` ;
* `certificate.type` ne contient que `name`, un **texte libre**, sans code ni
  xmlid ;
* la table est **vide** sur une instance fraîchement installée.

Une whitelist se réduirait donc à comparer des chaînes saisies à la main. C'est
précisément le « type whitelisté à cause de son nom approximatif » qu'il faut
éviter : il suffirait qu'un utilisateur nomme un type « BL » au lieu de « B/L »,
ou l'inverse, pour qu'une facture interne devienne publiable.

La whitelist est donc **vide**, et la publication est explicite, document par
document. Le jour où le fournisseur fournira une taxonomie stable, elle pourra
compléter ce mécanisme sans le remplacer.

## Pourquoi les octets ne sont pas dupliqués

`freight.documents.document` est un champ `Binary` : Odoo stocke son contenu
dans un `ir.attachment` (`res_model='freight.documents'`, `res_field='document'`).
La publication **référence** cette pièce jointe au lieu d'en recopier le
contenu.

Copier produirait deux exemplaires à faire vivre ensemble : une correction du
document opérationnel laisserait le client avec l'ancienne version, sans que
rien ne le signale. La référence garantit qu'il n'existe qu'un seul fichier.

La sécurité ne repose pas sur la pièce jointe elle-même mais sur
`dally.portal.document` : sa record rule sur `commercial_partner_id` décide qui
peut la télécharger, et le portail n'a aucun accès direct ni à
`freight.documents`, ni à `ir.attachment`.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

#: Types `dally.portal.document` proposés à la publication d'un document fret.
#: `transport` par défaut : c'est la nature d'un document de dossier fret, et
#: l'utilisateur interne reste libre de préciser.
TYPE_PAR_DEFAUT = "transport"


class FreightDocuments(models.Model):
    """Le document opérationnel, et sa trace de publication."""

    _name = "freight.documents"
    _inherit = "freight.documents"

    dally_portal_document_id = fields.Many2one(
        comodel_name="dally.portal.document",
        string="Publication client",
        readonly=True,
        copy=False,
        ondelete="set null",
        help="Publication de ce document dans l'espace client. Vide tant qu'il "
             "n'a pas été publié.",
    )

    # `set null` et non `restrict` : dépublier revient à supprimer la
    # publication, et cela ne doit jamais empêcher de retirer un document de
    # l'espace client.

    _dally_publication_unique = models.Constraint(
        "UNIQUE (dally_portal_document_id)",
        "Cette publication est déjà rattachée à un autre document.",
    )

    def dally_publish_to_portal(self, document_type=None, label=None):
        """Publie ces documents dans l'espace client. Idempotent.

        Réservée aux utilisateurs internes : c'est une décision d'exploitation.
        Retourne les `dally.portal.document` correspondants.
        """
        if self.env.user.share:
            raise AccessError(
                _("La publication d'un document est une décision interne.")
            )

        publications = self.env["dally.portal.document"]
        for document in self:
            publications |= document._dally_publish_one(document_type, label)
        return publications

    def _dally_publish_one(self, document_type=None, label=None):
        """Publie un document. Voir `dally_publish_to_portal`."""
        self.ensure_one()

        # Idempotence : republier ne crée pas un second exemplaire. Le contrôle
        # porte sur le lien stocké, pas sur une recherche par nom de fichier —
        # deux documents peuvent légitimement porter le même nom.
        if self.dally_portal_document_id:
            _logger.info(
                "Document fret %s deja publie (%s).",
                self.id,
                self.dally_portal_document_id.display_name,
            )
            return self.dally_portal_document_id

        expedition = self.sudo().freight_id
        if not expedition:
            raise UserError(
                _("Ce document n'est rattaché à aucune expédition : "
                  "impossible de déterminer à quel client le publier.")
            )

        # La projection est retrouvée **côté serveur**, depuis l'expédition du
        # document. Aucun identifiant fourni par l'appelant n'entre ici.
        projection = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "=", expedition.id)], limit=1
        )
        if not projection:
            raise UserError(
                _("L'expédition %s n'a pas de projection client : publiez-la "
                  "d'abord, ou vérifiez qu'elle provient bien d'un devis.")
                % expedition.display_name
            )

        piece_jointe = self._dally_attachment()
        if not piece_jointe:
            raise UserError(
                _("Le document %s n'a aucun fichier attaché.") % self.display_name
            )

        publication = self.env["dally.portal.document"].sudo().create({
            "name": label or self.file_name or _("Document de transport"),
            "attachment_id": piece_jointe.id,
            "document_type": document_type or TYPE_PAR_DEFAUT,
            "shipment_id": projection.id,
            "published_to_portal": True,
            "published_on": fields.Datetime.now(),
            "published_by_id": self.env.user.id,
        })
        self.sudo().dally_portal_document_id = publication.id

        _logger.info(
            "Document fret %s publie pour l'expedition %s par uid=%s.",
            self.id,
            projection.display_name,
            self.env.user.id,
        )
        return publication

    def dally_unpublish_from_portal(self):
        """Retire la publication. Idempotent.

        La publication est supprimée plutôt que dépubliée : `dally.portal.document`
        n'existe que pour être vu du client, et un enregistrement conservé mais
        invisible est une occasion de fuite à chaque évolution du filtre. Le
        document opérationnel, lui, n'est pas touché.
        """
        if self.env.user.share:
            raise AccessError(
                _("La dépublication d'un document est une décision interne.")
            )

        for document in self:
            publication = document.sudo().dally_portal_document_id
            if not publication:
                continue
            _logger.info("Document fret %s depublie par uid=%s.", document.id, self.env.user.id)
            document.sudo().dally_portal_document_id = False
            publication.unlink()
        return True

    def _dally_attachment(self):
        """Pièce jointe portant les octets du champ binaire du fournisseur.

        Odoo range le contenu d'un `fields.Binary` dans `ir.attachment`, repéré
        par `res_model` / `res_field` / `res_id`. On la référence, on ne la
        recopie pas — voir l'en-tête.
        """
        self.ensure_one()
        return self.env["ir.attachment"].sudo().search(
            [
                ("res_model", "=", "freight.documents"),
                ("res_field", "=", "document"),
                ("res_id", "=", self.id),
            ],
            limit=1,
        )


class DallyPortalDocument(models.Model):
    """Empêche un document fret publié de perdre son ancrage."""

    _name = "dally.portal.document"
    _inherit = "dally.portal.document"

    @api.constrains("shipment_id", "published_to_portal")
    def _dally_check_freight_publication(self):
        """Une publication issue du fret reste rattachée à son expédition.

        Sans cela, déplacer la publication vers une autre expédition la ferait
        changer de client — le fichier resterait le même, le propriétaire non.
        """
        # Deux requêtes pour l'ensemble, et non deux par publication : une
        # écriture groupée sur plusieurs documents publiés déclenchait autant
        # d'allers-retours qu'elle portait d'enregistrements.
        origines = self.env["freight.documents"].sudo().search(
            [("dally_portal_document_id", "in", self.ids)]
        )
        if not origines:
            return
        par_publication = {
            origine.dally_portal_document_id.id: origine for origine in origines
        }
        projections = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "in", origines.mapped("freight_id").ids)]
        )
        par_expedition = {
            projection.tk_shipment_id.id: projection for projection in projections
        }

        for publication in self:
            origine = par_publication.get(publication.id)
            if not origine:
                continue
            attendue = par_expedition.get(
                origine.freight_id.id, self.env["dally.shipment"]
            )
            if publication.shipment_id != attendue:
                raise ValidationError(
                    _("Cette publication provient du dossier fret %s et ne peut "
                      "pas être rattachée à une autre expédition.")
                    % origine.freight_id.display_name
                )
