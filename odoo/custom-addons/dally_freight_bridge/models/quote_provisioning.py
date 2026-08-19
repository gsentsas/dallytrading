"""
Provisionnement du fret à l'acceptation d'un devis.

```
dally.quote.request (state -> won)
        │  même transaction
        ▼
shipment.freight.booking          (fournisseur)
        │  convert_to_operation()
        ▼
freight.shipment                  (fournisseur, source de vérité opérationnelle)
        │  projection à sens unique
        ▼
dally.shipment                    (projection client)
```

## Pourquoi un `write()` surchargé, et non le contrôleur HTTP

La décision de devis fonctionne déjà en production. En faire le point d'entrée
d'un workflow fret le transformerait en pièce fragile : une erreur du
fournisseur deviendrait une 500 sur une fonctionnalité qui marche.

Le déclencheur est donc la **transition d'état**, quel que soit son auteur —
portail, back-office, script d'import. C'est le fait métier qui compte, pas le
canal qui l'a produit. Aucun appel HTTP interne, aucun cron, aucun commit
manuel : le provisionnement s'exécute dans la transaction qui écrit la
transition.

## Pourquoi la même transaction (choix transactionnel)

Si l'acceptation était commitée et le provisionnement différé, un échec du
fournisseur laisserait un devis « accepté » sans expédition, sans que personne
ne le sache. L'incohérence silencieuse est le pire des états.

Ici, une exception du fournisseur annule **aussi** l'acceptation : le client
revoit son devis en attente et peut réessayer, l'exploitation voit l'erreur dans
les journaux. C'est un comportement compréhensible sans machinerie de reprise —
et une file de reprise reste ajoutable plus tard si le volume l'exige, sans rien
défaire d'ici.

## Idempotence

Trois barrières, et **une correction issue de la mesure**.

1. Le verrou `FOR UPDATE` sur la ligne du devis, qui sérialise l'exécution.
2. La relecture du lien après le verrou, qui écarte le rejeu séquentiel — deux
   appels l'un après l'autre, un rejeu de méthode, une réexécution de hook.
3. L'index unique `dally_quote_request_id`, évalué par PostgreSQL.

La barrière 2 **ne suffit pas en concurrence réelle**, et c'est un point qu'il
faut énoncer plutôt que supposer. Odoo force `REPEATABLE READ` au niveau de la
connexion (`odoo/sql_db.py`), indépendamment du défaut PostgreSQL. Quand la
transaction perdante obtient enfin le verrou, elle travaille toujours sur
l'instantané pris à son ouverture : elle **ne voit pas** le booking que la
gagnante vient de committer. Sa relecture ne trouve rien, elle crée, et l'index
unique la rejette.

Mesuré : deux acceptations simultanées donnaient bien 1 booking / 1 expédition /
1 projection, mais la perdante levait `UniqueViolation`. Or `UniqueViolation`
n'appartient pas à `PG_CONCURRENCY_EXCEPTIONS_TO_RETRY` — Odoo ne la rejoue pas,
et l'appelant reçoit une 500 sur une opération pourtant parfaitement légitime.

D'où la barrière 4 : la course est convertie en `SerializationFailure`, qu'Odoo
rejoue jusqu'à cinq fois. La nouvelle transaction ouvre un instantané frais, y
voit le booking de la gagnante, et retourne le résultat idempotent. Le résultat
observable est alors identique pour les deux appelants.
"""

import logging

from psycopg2.errors import SerializationFailure, UniqueViolation

from odoo import _, api, models
from odoo.exceptions import UserError

from .freight_mapping import (
    DIRECTION_TO_DIRECTION,
    TransportIndeterminable,
    carries_own_mode,
    is_freight_service,
    transport_from_groupage_mode,
    transport_from_vehicle_mode,
    mode_from_transport,
    state_from_stage,
    transport_from_service,
)

_logger = logging.getLogger(__name__)

#: États du devis qui déclenchent le provisionnement.
ETATS_ACCEPTES = frozenset({"won"})

#: Drapeau de contexte supprimant le courriel du fournisseur. Voir
#: `vendor_mail.py` pour la justification.
CTX_SANS_MAIL_VENDEUR = "dally_freight_suppress_vendor_mail"


class DallyQuoteRequest(models.Model):
    """Déclenche le provisionnement fret quand le devis devient accepté."""

    _name = "dally.quote.request"
    _inherit = "dally.quote.request"

    def write(self, vals):
        """Provisionne le fret sur la transition vers un état accepté.

        On compare l'état **avant** et **après** : réécrire `won` sur un devis
        déjà `won` n'est pas une transition et ne doit rien provoquer. C'est le
        cas du rejeu idempotent d'une décision portail.
        """
        nouvel_etat = vals.get("state")
        if nouvel_etat not in ETATS_ACCEPTES:
            return super().write(vals)

        a_provisionner = self.filtered(lambda devis: devis.state != nouvel_etat)
        resultat = super().write(vals)

        for devis in a_provisionner:
            # Seuls les devis fret provisionnent. Un devis de sourcing, de
            # trading ou d'e-commerce s'accepte normalement et ne crée aucune
            # expédition — le moteur fret n'a rien à en dire.
            if is_freight_service(devis.sudo().service_type_id):
                devis._dally_freight_provision()
        return resultat

    # ------------------------------------------------------------------
    # Provisionnement
    # ------------------------------------------------------------------

    def _dally_freight_provision(self):
        """Crée booking, expédition et projection. Idempotent.

        Retourne la projection `dally.shipment`, existante ou nouvelle.
        """
        self.ensure_one()

        # Barrière 1 : sérialise deux provisionnements concurrents du même
        # devis. La décision portail pose déjà ce verrou ; on ne peut pas s'y
        # fier ici, car un écrivain back-office n'emprunte pas ce chemin.
        self.env.cr.execute(
            f'SELECT id FROM "{self._table}" WHERE id = %s FOR UPDATE',
            [self.id],
        )

        # Barrière 2 : relecture APRÈS le verrou. La transaction perdante voit
        # ici le booking créé par la gagnante et s'arrête.
        booking = self.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", self.id)], limit=1
        )
        if booking:
            _logger.info(
                "Provisionnement fret deja fait pour le devis %s : booking %s.",
                self.id,
                booking.name,
            )
            return self._dally_freight_projection(booking)

        # Barrière 4 : la course perdue devient une erreur qu'Odoo rejoue.
        #
        # Sous REPEATABLE READ, la relecture ci-dessus ne peut pas voir le
        # booking committé par la transaction gagnante — voir l'en-tête. La
        # violation d'unicité est donc le signal « quelqu'un d'autre a gagné »,
        # et non une anomalie de données.
        #
        # La transaction PostgreSQL est de toute façon avortée à ce stade : rien
        # ne peut être rattrapé sur place. La seule sortie correcte est de faire
        # rejouer la requête entière, ce qu'Odoo sait faire pour
        # `SerializationFailure` — cinq tentatives, attente exponentielle. Au
        # tour suivant, l'instantané est frais et le chemin idempotent
        # ci-dessus s'applique.
        try:
            booking = self._dally_freight_create_booking()
        except UniqueViolation as course_perdue:
            _logger.info(
                "Course de provisionnement perdue sur le devis %s : rejeu demande.",
                self.id,
            )
            raise SerializationFailure(
                "Concurrent freight provisioning for quote %s" % self.id
            ) from course_perdue

        return self._dally_freight_projection(booking)

    def _dally_freight_create_booking(self):
        """Crée le booking fournisseur et le convertit en expédition.

        Passe par `convert_to_operation()`, la méthode métier du fournisseur,
        plutôt que par un `create()` sur `freight.shipment` : elle recopie les
        lignes de colis, crée les lignes de service et pose `booking_id`. La
        reproduire à la main serait un fork déguisé, à re-vérifier à chaque
        mise à jour.
        """
        self.ensure_one()

        expediteur, destinataire = self._dally_freight_parties()
        transport, type_maritime = self._dally_freight_transport()
        valeurs = {
            "dally_quote_request_id": self.id,
            # L'opérateur est l'utilisateur courant s'il est interne, faute de
            # quoi le compte système : un utilisateur portail ne peut pas être
            # l'opérateur d'un dossier d'exploitation.
            "operator_id": self._dally_freight_operator().id,
            "shipper_id": expediteur.id,
            "consignee_id": destinataire.id,
            "transport": transport,
            "operation": "direct",
        }
        # `ocean_shipment_type` n'est posé que lorsqu'il a un sens : LCL est une
        # notion maritime. L'écrire sur une expédition aérienne serait une
        # donnée fausse dans le dossier d'exploitation.
        if type_maritime:
            valeurs["ocean_shipment_type"] = type_maritime

        booking = self.env["shipment.freight.booking"].sudo().create(valeurs)

        # Force l'évaluation de l'index unique ici, et non plus tard au gré d'un
        # flush implicite : la course doit être détectée dans le `try` de
        # l'appelant, pas au milieu du code du fournisseur.
        booking.flush_recordset(["dally_quote_request_id"])

        # Le fournisseur envoie un courriel au client en `force_send=True`.
        # DallyTrading est seul maître de sa communication client : le drapeau
        # de contexte le supprime (voir `vendor_mail.py`).
        resultat = booking.with_context(**{CTX_SANS_MAIL_VENDEUR: True}).convert_to_operation()

        # Piège du fournisseur : quand shipper ou consignee manque,
        # `convert_to_operation()` ne lève pas — il **retourne une notification**
        # et ne crée rien. Un appelant qui ignore le retour croit avoir réussi.
        if not isinstance(resultat, dict) or resultat.get("type") != "ir.actions.act_window":
            raise UserError(
                _(
                    "Le moteur fret a refusé de convertir le booking %s. "
                    "Réponse du fournisseur : %s"
                )
                % (booking.name, resultat)
            )

        return booking

    def _dally_freight_operator(self):
        """Utilisateur interne responsable du dossier côté exploitation."""
        self.ensure_one()
        utilisateur = self.env.user
        if not utilisateur.share:
            return utilisateur
        return self.env.ref("base.user_root")

    def _dally_freight_vehicle_cargo(self):
        """Véhicule décrit par ce devis, s'il y en a un.

        `sudo()` pour la même raison que le service : la transition a déjà été
        autorisée, et lire la marchandise du dossier en est la conséquence
        serveur. Aucune donnée d'un autre client n'y transite — la recherche est
        bornée à ce devis.
        """
        self.ensure_one()
        if "dally.freight.vehicle.cargo" not in self.env:
            return self.env["dally.quote.request"].browse()
        return self.env["dally.freight.vehicle.cargo"].sudo().search(
            [("quote_request_id", "=", self.id)], limit=1
        )

    def _dally_freight_parties(self):
        """Détermine expéditeur et destinataire.

        Aucune règle par défaut du type « le client est toujours destinataire » :
        elle serait fausse une fois sur deux. La direction du dossier tranche —
        à l'import le client reçoit, à l'export il expédie — et DallyTrading est
        la contrepartie dans les deux cas.
        """
        self.ensure_one()
        # Même raison que pour le service : la transition est autorisée, la
        # résolution des parties en est la conséquence serveur.
        client = self.sudo().partner_id.commercial_partner_id
        if not client:
            raise UserError(
                _("Le devis %s n'a pas de client : provisionnement fret impossible.")
                % self.display_name
            )

        maison = self.env.company.sudo().partner_id
        if self._dally_freight_direction() == "export":
            return client, maison
        return maison, client

    def _dally_freight_direction(self):
        """Direction du dossier, `import` par défaut.

        `dally.quote.request` ne porte pas de direction ; l'import est le flux
        très majoritaire de DallyTrading. La valeur est isolée ici pour que le
        jour où le devis portera l'information, un seul endroit change.
        """
        self.ensure_one()
        return DIRECTION_TO_DIRECTION.get("import", "import")

    def _dally_freight_transport(self):
        """Transport tk, déduit du service demandé par le client.

        Le devis porte l'information : `dally.service.type.code` distingue
        `freight_sea`, `freight_air`, `freight_vehicle` et `freight_groupage`.
        La lire évite de décider à la place du client — un mode fixé en dur
        aurait créé toutes les expéditions en maritime, y compris les aériennes.

        ## Aucun repli

        Un service dont le mode n'est pas déductible **annule le
        provisionnement**, et avec lui l'acceptation du devis : les deux sont
        dans la même transaction. Le devis reste en attente — un état vrai, que
        l'exploitation voit et peut traiter — au lieu d'une expédition maritime
        fausse que personne ne sait devoir corriger.

        ## Pourquoi `sudo()` ici

        Le provisionnement est déclenché par une transition d'état, y compris
        celle qu'un client produit en acceptant son devis depuis le portail. Or
        `dally.service.type` est une table de configuration : le portail n'y a
        aucun droit de lecture.

        Sans `sudo()`, l'acceptation échouait donc sur un `AccessError` — et,
        sous concurrence, la suite de tests se bloquait purement et simplement.
        Le `sudo()` est légitime parce qu'il vient **après** la décision
        d'autorisation, pas à sa place : c'est la transition du devis qui a été
        autorisée, et cette lecture n'est qu'une conséquence serveur. Il est
        limité à un champ de configuration, sans donnée d'un autre client.
        """
        self.ensure_one()
        service = self.sudo().service_type_id

        # Services dont le mode voyage avec la marchandise — le transport de
        # véhicule aujourd'hui. On lit le mode sur le véhicule lui-même : le
        # service dit ce que le client achète, pas comment la voiture part.
        code = (service.code or "") if service else ""

        # Groupage : le mode voyage sur le devis, et le maritime emporte avec
        # lui le type d'expédition LCL du fournisseur.
        if code == "freight_groupage":
            try:
                return transport_from_groupage_mode(self.sudo().groupage_transport_mode)
            except TransportIndeterminable as indeterminable:
                raise UserError(
                    _(
                        "Le mode de groupage du devis %(devis)s n'est pas pris "
                        "en charge (« %(mode)s »). L'acceptation est annulée : "
                        "aucune expédition n'a été créée."
                    )
                    % {
                        "devis": self.display_name,
                        "mode": indeterminable.code or "non renseigné",
                    }
                ) from indeterminable

        if carries_own_mode(service):
            vehicule = self._dally_freight_vehicle_cargo()
            if not vehicule:
                raise UserError(
                    _(
                        "Le devis %s demande un transport de véhicule mais aucun "
                        "véhicule n'y est décrit. L'acceptation est annulée : "
                        "aucune expédition n'a été créée."
                    )
                    % self.display_name
                )
            try:
                return transport_from_vehicle_mode(vehicule.transport_mode), False
            except TransportIndeterminable as indeterminable:
                raise UserError(
                    _(
                        "Le mode de transport du véhicule du devis %(devis)s "
                        "n'est pas pris en charge (« %(mode)s »). L'acceptation "
                        "est annulée : aucune expédition n'a été créée."
                    )
                    % {
                        "devis": self.display_name,
                        "mode": indeterminable.code or "non renseigné",
                    }
                ) from indeterminable

        try:
            return transport_from_service(service), False
        except TransportIndeterminable as indeterminable:
            raise UserError(
                _(
                    "Le service « %(service)s » ne correspond à aucun mode de "
                    "transport pris en charge par le moteur fret. L'acceptation "
                    "du devis %(devis)s est annulée : aucune expédition n'a été "
                    "créée. Choisissez un service maritime ou aérien, ou faites "
                    "ajouter ce mode avant d'accepter."
                )
                % {
                    "service": service.display_name or indeterminable.code or "-",
                    "devis": self.display_name,
                }
            ) from indeterminable

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def _dally_freight_projection(self, booking):
        """Crée ou retrouve la projection client de l'expédition du booking."""
        self.ensure_one()

        expedition = self.env["freight.shipment"].sudo().search(
            [("booking_id", "=", booking.id)], limit=1, order="id"
        )
        if not expedition:
            raise UserError(
                _("Le booking %s n'a produit aucune expédition.") % booking.name
            )

        projection = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "=", expedition.id)], limit=1
        )
        if not projection:
            mode = mode_from_transport(expedition.transport) or "other"

            # Garde-fou : le pont ne produit JAMAIS le mode historique
            # « groupage ».
            #
            # Cette valeur existe encore sur `dally.shipment` pour les saisies
            # manuelles et les enregistrements anciens, et elle y reste. Mais
            # elle vaut 1000 kg/m³ dans `VOLUMETRIC_RATIOS`, comme le maritime :
            # une consolidation aérienne projetée ainsi verrait son poids
            # taxable calculé au ratio maritime au lieu de 167, soit un facteur
            # six sur du fret léger et volumineux.
            #
            # « Groupage » est un service commercial ; le mode dit comment la
            # marchandise voyage. Les confondre se paierait en facturation.
            if mode == "groupage":
                raise UserError(
                    _("Le provisionnement a produit le mode « groupage », qui "
                      "décrit un service et non un transport physique. "
                      "L'expédition %s aurait été facturée au mauvais ratio "
                      "volumétrique.") % expedition.display_name
                )

            projection = self.env["dally.shipment"].sudo().create({
                "tk_shipment_id": expedition.id,
                "partner_id": self.sudo().partner_id.commercial_partner_id.id,
                "transport_mode": mode,
                "direction": self._dally_freight_direction(),
                "state": "draft",
            })
            _logger.info(
                "Projection fret creee: devis=%s booking=%s tk=%s dally=%s",
                self.id,
                booking.name,
                expedition.name,
                projection.display_name,
            )

        # Rattachement du véhicule à l'expédition. Écrit seulement s'il change :
        # une resynchronisation ne doit pas produire d'écriture inutile, et
        # surtout pas déplacer un véhicule déjà rattaché ailleurs.
        vehicule = self._dally_freight_vehicle_cargo()
        if vehicule and vehicule.shipment_id != projection:
            vehicule.sudo().shipment_id = projection.id
            _logger.info(
                "Vehicule %s rattache a l'expedition %s.",
                vehicule.id, projection.display_name,
            )

        projection._dally_freight_sync_from_tk()
        return projection


class DallyShipmentProjection(models.Model):
    """Synchronisation à sens unique, tk → Dally."""

    _name = "dally.shipment"
    _inherit = "dally.shipment"

    def _dally_freight_sync_from_tk(self):
        """Recopie depuis l'expédition opérationnelle les champs projetés.

        **Sens unique, sans exception.** Rien ici ne réécrit tk : une
        modification faite au portail ne doit jamais remonter dans l'outil
        d'exploitation par un effet de bord de synchronisation.

        Aucun champ financier n'est projeté — ni coût fournisseur, ni marge, ni
        commission. Ils n'ont pas à exister dans un enregistrement dont la
        vocation est d'être lu par le client.
        """
        for projection in self:
            expedition = projection.sudo().tk_shipment_id
            if not expedition:
                continue

            valeurs = {}

            mode = mode_from_transport(expedition.transport)
            if mode:
                valeurs["transport_mode"] = mode

            # Étape inconnue : on conserve l'état courant plutôt que d'en
            # inventer un. Voir `freight_mapping.state_from_stage`.
            etat = state_from_stage(projection.env, expedition.sudo().stage_id)
            if etat:
                valeurs["state"] = etat

            if valeurs:
                projection.sudo().write(valeurs)

            projection._dally_freight_sync_packages(expedition)
            projection._dally_freight_sync_events(expedition)

            # Un dossier provisionné n'est plus un brouillon.
            #
            # La projection naît en `draft` — état de travail, invisible du
            # client — et l'étape du fournisseur, à ce moment, vaut « Draft »
            # elle aussi : rien ne la faisait avancer. Le client dont le devis
            # venait d'être accepté ne voyait donc **rien** dans son espace
            # jusqu'à ce qu'un opérateur touche le dossier à la main.
            #
            # `request_received` est l'état qui dit exactement ce qui vient de
            # se passer : la demande est prise en charge. On y passe par
            # `write()` et non en forçant la colonne, pour que la mécanique
            # habituelle se déclenche — `state_changed_on`, l'événement de
            # suivi, et la mise en file de la notification. Une écriture
            # directe produirait un dossier avancé dont le client n'aurait
            # jamais été prévenu, ce qui est précisément le défaut qu'on
            # corrige.
            if projection.sudo().state == "draft":
                projection.sudo().write({"state": "request_received"})

    def _dally_freight_sync_packages(self, expedition):
        """Projette les colis opérationnels vers les colis client.

        `shipment.package.line` est la source ; `dally.shipment.package` est la
        projection. Les colis absents de la source ne sont pas supprimés ici :
        une projection qui efface est bien plus difficile à diagnostiquer qu'une
        projection qui ajoute, et le MVP ne connaît pas encore de suppression
        côté fournisseur.
        """
        self.ensure_one()
        Package = self.env["dally.shipment.package"].sudo()

        deja_projetes = Package.search_count([("shipment_id", "=", self.id)])
        if deja_projetes:
            return

        lignes = expedition.sudo().package_ids if "package_ids" in expedition._fields else None
        if lignes is None:
            lignes = self.env["shipment.package.line"].sudo().search(
                [("shipment_id", "=", expedition.id)]
            )

        for sequence, ligne in enumerate(lignes, start=1):
            Package.create({
                "shipment_id": self.id,
                "sequence": sequence * 10,
                "quantity": int(ligne.qty or 1),
                "unit_weight_kg": ligne.net_weight or 0.0,
                "length_cm": ligne.length or 0.0,
                "width_cm": ligne.width or 0.0,
                "height_cm": ligne.height or 0.0,
                # Ni `charges`, ni `sale` : ce sont des montants internes.
            })

    def _dally_freight_sync_events(self, expedition):
        """Projette les événements de suivi publiables.

        ## Politique de publication : fermée par défaut

        Tout événement `shipment.tracking` n'est pas destiné au client. Un
        événement interne — attente de paiement, litige, note d'exploitation —
        publié par accident est irrattrapable : le client l'a lu.

        La règle est donc l'inverse de l'intuition : **rien n'est publié tant
        que ce n'est pas explicitement publiable**. Ici, seuls les événements
        dont l'étape est connue du mapping le sont ; un événement ambigu reste
        `visible_to_customer=False` et n'apparaît jamais au portail.
        """
        self.ensure_one()
        Event = self.env["dally.shipment.event"].sudo()

        suivis = self.env["shipment.tracking"].sudo().search(
            [("shipment_id", "=", expedition.id)], order="date, id"
        )

        # Les dates déjà projetées sont lues **en une seule requête**, et non
        # une par événement : une expédition longue accumule des dizaines de
        # points de suivi, et resynchroniser en produisait autant de requêtes.
        deja_projetees = {
            ligne["event_date"]
            for ligne in Event.search_read(
                [("shipment_id", "=", self.id)], ["event_date"], load=""
            )
        }

        a_creer = []
        for suivi in suivis:
            date = suivi.date
            if not date or date in deja_projetees:
                continue
            deja_projetees.add(date)

            a_creer.append({
                "shipment_id": self.id,
                "event_date": date,
                "location": suivi.location_id.display_name or "",
                "description": suivi.location_id.display_name or _("Mise à jour"),
                # Fermé par défaut : la publication est une décision explicite
                # de l'exploitation, pas un effet de bord de la synchronisation.
                "visible_to_customer": False,
                "is_automatic": True,
            })

        # Création groupée : un seul INSERT plutôt qu'un par événement.
        if a_creer:
            Event.create(a_creer)

    @api.model
    def _dally_freight_sync_all(self):
        """Resynchronise toutes les projections liées. Point d'entrée manuel."""
        liees = self.sudo().search([("tk_shipment_id", "!=", False)])
        liees._dally_freight_sync_from_tk()
        return len(liees)
