# -*- coding: utf-8 -*-
"""Le seul chemin par lequel un fichier peut atteindre un client.

## Pourquoi des relations explicites plutôt qu'un couple ``res_model`` / ``res_id``

Un couple générique est plus souple, et c'est précisément le problème : il rend
*possible* de publier un document rattaché à ``dally.sourcing.offer`` ou à
``dally.trade.cost``. La sécurité reposerait alors sur une liste de modèles
autorisés vérifiée quelque part — c'est-à-dire sur le fait que personne n'oublie de
la consulter.

Avec cinq ``Many2one`` nommés, publier un document d'offre fournisseur n'est pas
« interdit » : c'est **inexprimable**. Il n'existe aucun champ où le poser. La
contrainte devient structurelle plutôt que procédurale, et c'est la seule forme de
règle qui survit à un développeur pressé.

## Le propriétaire n'est pas saisi, il est déduit

``commercial_partner_id`` est calculé et stocké depuis l'objet métier. S'il était
saisissable, publier un document au nom du mauvais client ne serait qu'une faute de
frappe. Étant dérivé, il ne peut désigner que le client réellement rattaché au
dossier — et la record rule portail s'appuie dessus.

Stocké parce qu'une record rule doit pouvoir filtrer en SQL ; un champ calculé non
stocké ne peut pas apparaître dans un domaine.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

#: Les cinq rattachements autorisés, et le champ qui porte le client sur chacun.
#:
#: Déclaré comme donnée : le calcul du propriétaire, la contrainte d'unicité et les
#: tests lisent tous cette table. Ajouter un rattachement demain, c'est ajouter une
#: ligne ici — et si on oublie, la contrainte le refusera plutôt que de laisser
#: passer un document sans propriétaire.
BUSINESS_LINKS = {
    "quote_request_id": "partner_id",
    "sourcing_request_id": "customer_id",
    "sourcing_proposal_id": "customer_id",
    "trade_opportunity_id": "customer_id",
    "shipment_id": "partner_id",
}

DOCUMENT_TYPES = [
    ("quotation", "Devis / proposition"),
    ("transport", "Document de transport"),
    ("customs", "Document douanier"),
    ("invoice", "Facture"),
    ("certificate", "Certificat"),
    ("other", "Autre"),
]


class DallyPortalDocument(models.Model):
    _name = "dally.portal.document"
    _description = "DallyTrading Portal Document"
    _order = "create_date desc, id desc"

    name = fields.Char(string="Libellé", required=True)
    attachment_id = fields.Many2one(
        comodel_name="ir.attachment",
        string="Fichier",
        required=True,
        ondelete="cascade",
        help="La pièce jointe réelle. Le portail n'y accède jamais directement : "
             "le téléchargement passe par un contrôleur qui refait le contrôle.",
    )
    document_type = fields.Selection(
        selection=DOCUMENT_TYPES, string="Type", required=True, default="other",
    )

    # ─── Les cinq rattachements autorisés ────────────────────────────
    quote_request_id = fields.Many2one(
        comodel_name="dally.quote.request", string="Demande de devis",
        ondelete="cascade", index=True,
    )
    sourcing_request_id = fields.Many2one(
        comodel_name="dally.sourcing.request", string="Demande de sourcing",
        ondelete="cascade", index=True,
    )
    sourcing_proposal_id = fields.Many2one(
        comodel_name="dally.sourcing.proposal", string="Proposition de sourcing",
        ondelete="cascade", index=True,
    )
    trade_opportunity_id = fields.Many2one(
        comodel_name="dally.trade.opportunity", string="Opération de trading",
        ondelete="cascade", index=True,
    )
    shipment_id = fields.Many2one(
        comodel_name="dally.shipment", string="Expédition",
        ondelete="cascade", index=True,
    )

    published_to_portal = fields.Boolean(
        string="Publié au client",
        default=False,
        index=True,
        help="Tant que ce drapeau est faux, le document n'existe pas pour le "
             "client. La publication est un geste explicite du personnel, jamais "
             "une conséquence du dépôt d'un fichier.",
    )
    published_on = fields.Datetime(string="Publié le", readonly=True, copy=False)
    published_by_id = fields.Many2one(
        comodel_name="res.users", string="Publié par", readonly=True, copy=False,
        groups="dally_core.group_dally_readonly",
    )

    commercial_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Client propriétaire",
        compute="_compute_commercial_partner_id",
        store=True,
        index=True,
        readonly=True,
        help="Déduit de l'objet métier, jamais saisi. Stocké parce qu'une record "
             "rule doit pouvoir filtrer dessus en SQL.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company", string="Société",
        default=lambda self: self.env.company, required=True, index=True,
    )
    active = fields.Boolean(default=True)

    # ─── Calculs ─────────────────────────────────────────────────────

    @api.depends(*[f"{link}.{owner}.commercial_partner_id"
                   for link, owner in BUSINESS_LINKS.items()])
    def _compute_commercial_partner_id(self):
        """Remonter au client depuis l'objet métier, quel que soit son nom de champ.

        Les cinq modèles ne nomment pas leur client pareil — `partner_id` ici,
        `customer_id` là. La table `BUSINESS_LINKS` porte la correspondance une
        seule fois ; la deviner à chaque endroit finirait par produire une erreur
        sur le modèle qu'on regarde le moins.
        """
        for document in self:
            owner = self.env["res.partner"]
            for link, owner_field in BUSINESS_LINKS.items():
                record = document[link]
                if record:
                    owner = record[owner_field].commercial_partner_id
                    break
            document.commercial_partner_id = owner

    # ─── Contraintes ─────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        """Revalider à la création, y compris quand AUCUN rattachement n'est fourni.

        `@api.constrains` ne se déclenche, à la création, que pour les champs
        présents dans les valeurs. Un document créé sans aucun rattachement ne
        touche donc aucun des champs surveillés, et passait au travers : il
        existait, sans propriétaire, dans un état que la contrainte est justement
        censée rendre impossible.

        Ce n'était pas exploitable — sans `commercial_partner_id`, la record rule
        ne le montre à personne, et la publication est refusée par
        `_check_published_has_owner`. Mais un état interdit qui existe finit par
        être traité comme autorisé.
        """
        documents = super().create(vals_list)
        documents._check_exactly_one_business_link()
        return documents

    @api.constrains(*BUSINESS_LINKS)
    def _check_exactly_one_business_link(self):
        """Exactement un rattachement, ni zéro ni deux.

        Zéro : le document n'aurait pas de propriétaire, donc aucune record rule ne
        s'y appliquerait — il serait invisible, ou visible de tous selon le sens du
        domaine. Deux : le propriétaire dépendrait de l'ordre d'évaluation, ce qui
        revient à ne pas savoir à qui appartient le fichier.
        """
        for document in self:
            filled = [link for link in BUSINESS_LINKS if document[link]]
            if len(filled) != 1:
                raise ValidationError(
                    _(
                        "Un document portail doit être rattaché à exactement un "
                        "dossier métier ; celui-ci en a %(count)s (%(links)s).\n\n"
                        "Les rattachements possibles sont limités à : demande de "
                        "devis, demande de sourcing, proposition de sourcing, "
                        "opération de trading, expédition. Un document d'offre "
                        "fournisseur, de coût ou de commission n'a volontairement "
                        "aucun champ où être rattaché.",
                        count=len(filled),
                        links=", ".join(filled) or _("aucun"),
                    )
                )

    @api.constrains("published_to_portal", "commercial_partner_id")
    def _check_published_has_owner(self):
        """Rien ne se publie sans propriétaire identifié.

        Un document publié dont le `commercial_partner_id` est vide échapperait au
        domaine de la record rule. Selon l'opérateur employé il serait alors soit
        invisible, soit visible par tous — et le second cas ne se remarque pas.
        """
        for document in self:
            if document.published_to_portal and not document.commercial_partner_id:
                raise ValidationError(
                    _(
                        "Le document « %s » ne peut pas être publié : son dossier "
                        "métier ne désigne aucun client. Renseignez le client sur "
                        "le dossier d'abord.",
                        document.name,
                    )
                )

    # ─── Publication ─────────────────────────────────────────────────

    def action_publish(self):
        """Publier au client. Réservé au personnel par les ACL."""
        for document in self:
            document.write({
                "published_to_portal": True,
                "published_on": fields.Datetime.now(),
                "published_by_id": self.env.user.id,
            })
        return True

    def action_unpublish(self):
        """Retirer du portail. Le document reste, il cesse d'être visible."""
        self.write({
            "published_to_portal": False,
            "published_on": False,
            "published_by_id": False,
        })
        return True

    # ─── Projection portail ──────────────────────────────────────────

    #: Ce qu'un client peut voir d'un document. Liste blanche.
    PORTAL_PAYLOAD_KEYS = (
        "reference", "name", "documentType", "documentTypeLabel",
        "relatedTo", "relatedReference", "publishedOn",
    )

    def _dally_portal_payload(self):
        """Ce que le client voit. Aucun identifiant technique, aucun chemin fichier.

        `attachment_id` est absent volontairement : le client n'a pas besoin de
        connaître l'identifiant de la pièce jointe, et le lui donner inviterait à
        tenter `/web/content/<id>`, qui court-circuiterait le contrôle.
        """
        self.ensure_one()
        labels = dict(DOCUMENT_TYPES)
        related_model, related_reference = "", ""
        for link in BUSINESS_LINKS:
            record = self[link]
            if record:
                related_model = record._description
                related_reference = getattr(record, "reference", "") or ""
                break
        payload = {
            "reference": f"DOC-{self.id}",
            "name": self.name,
            "documentType": self.document_type,
            "documentTypeLabel": labels.get(self.document_type, self.document_type),
            "relatedTo": related_model,
            "relatedReference": related_reference,
            "publishedOn": (
                self.published_on.date().isoformat() if self.published_on else None
            ),
        }
        return {key: payload[key] for key in self.PORTAL_PAYLOAD_KEYS}

    def _dally_portal_detail_payload(self):
        """Un document n'a rien de plus à montrer en détail qu'en liste.

        Présent explicitement plutôt qu'hérité d'un mixin : ce modèle est défini
        dans ce fichier, et la liste des clés qu'il expose est juste au-dessus.
        """
        self.ensure_one()
        return self._dally_portal_payload()

    def _dally_portal_readable_attachment(self):
        """Renvoyer la pièce jointe **après** que l'accès a été prouvé.

        La frontière `sudo()` est ici, et nulle part ailleurs.

        Ce qui précède l'appel est exécuté sous l'identité du client : le `browse`
        et le `check_access` ci-dessous passent par les ACL et la record rule
        portail. Si le document ne lui appartient pas, ou n'est pas publié, la
        lecture lève avant qu'on arrive aux octets.

        Le `sudo()` ne sert qu'à lire le contenu de `ir.attachment` une fois cette
        preuve faite. Il n'élargit pas ce à quoi le client a droit : il lit une
        pièce jointe précise, désignée par un document déjà autorisé.
        """
        self.ensure_one()
        # Sous l'identité de l'appelant : lève si la record rule ne le permet pas.
        self.check_access("read")
        if not self.published_to_portal:
            raise ValidationError(
                _("Ce document n'est pas publié.")
            )
        # Frontière assumée : le contrôle d'accès est franchi, on lit les octets.
        return self.sudo().attachment_id
