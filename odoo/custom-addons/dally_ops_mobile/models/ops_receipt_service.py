# -*- coding: utf-8 -*-
"""Le reçu remis au client au moment du dépôt.

## Un reçu n'est pas une facture

C'est l'invariant que tout ce fichier existe pour tenir. Le document atteste
que DallyTrading a **pris en charge** des marchandises ; il ne réclame rien et
n'engage aucune écriture comptable. Générer un reçu ne crée aucune facture,
n'en poste aucune, n'en modifie aucune. Si une facture native existe déjà, son
numéro peut y figurer comme référence — mais le reçu reste un autre document.

La confusion serait coûteuse dans les deux sens : un client qui prend un reçu
pour une facture croit devoir payer une somme qui n'est pas encore due, et une
comptabilité qui prend un reçu pour une pièce se retrouve avec des créances
qui n'existent pas.

## Une seule lecture, deux rendus

L'aperçu mobile et le PDF sont construits à partir du **même** contrat. Deux
constructions séparées finiraient par diverger — et c'est toujours le document
imprimé, celui que le client emporte, qui dirait faux.

## Ce que le reçu ne calcule pas

Aucune tarification : il affiche ce qu'Odoo a décidé. Aucune conversion : un
total en euros et un encaissement en francs ne se soustraient pas, et un solde
inventé sur un taux choisi ici serait faux la moitié du temps. Le solde n'est
affiché que lorsqu'il est exact.
"""

import re

from odoo import _, api, models
from odoo.exceptions import AccessError

from .ops_errors import DallyOpsError, DallyOpsNotFound

#: Le rapport natif. Odoo sait déjà produire un PDF propre et paginé ; en
#: écrire un à la main reviendrait à réapprendre la pagination, les polices et
#: les accents. L'enregistrement porte aussi le format de papier.
RAPPORT = "dally_ops_mobile.action_ops_receipt"

#: Le gabarit du document, rendu en HTML complet et autonome.
GABARIT = "dally_ops_mobile.report_ops_receipt"

#: Ce que le classeur des familles affiche au client.
LIBELLES_FAMILLE = {
    "food": "Alimentaire standard",
    "seafood": "Halieutiques",
    "honey": "Miel",
    "clothing": "Habits / Vêtements",
    "non_food": "Non alimentaire",
}

LIBELLES_MODE = {"air": "Aérien", "sea": "Maritime"}

LIBELLES_PAIEMENT = {
    "cash": "Espèces", "wave": "Wave", "bank_transfer": "Virement",
    "bank": "Virement", "other": "Autre",
}

#: Le franc CFA ne se divise pas : écrire « 100 000,00 FCFA » annoncerait une
#: précision que la monnaie n'a pas. L'euro garde ses centimes — un reçu de
#: 67 € pour 67,50 € dus serait une erreur de caisse. Même règle que l'écran
#: (`features/depenses/format.ts`).
DECIMALES = {"XOF": 0}

SYMBOLES = {"EUR": "€", "XOF": "FCFA"}


def montant(valeur, devise):
    """Un montant tel qu'il se lit sur le reçu.

    Le séparateur de milliers est une espace, comme en français. Les chaînes
    sont construites ici plutôt que dans le gabarit : le PDF et l'écran doivent
    afficher les mêmes caractères, et deux formateurs finiraient par diverger
    sur un arrondi que le client, lui, remarquerait.
    """
    if valeur is None:
        return ""
    decimales = DECIMALES.get(devise, 2)
    entier, _, fraction = ("%.*f" % (decimales, valeur)).partition(".")
    signe, chiffres = ("-", entier[1:]) if entier.startswith("-") else ("", entier)
    groupes = []
    while len(chiffres) > 3:
        groupes.insert(0, chiffres[-3:])
        chiffres = chiffres[:-3]
    groupes.insert(0, chiffres)
    nombre = signe + " ".join(groupes)
    if fraction:
        nombre = "%s,%s" % (nombre, fraction)
    return "%s %s" % (nombre, SYMBOLES.get(devise, devise))


def poids(valeur):
    """Un poids tel qu'il se lit sur le reçu — « 13,5 kg ».

    Écrit ici pour la même raison que les montants : le papier affichait
    « 13.5 kg » quand l'écran affichait « 13,5 kg ». Personne n'aurait relu le
    reçu du client pour vérifier un point décimal.
    """
    entier, _, fraction = ("%.3f" % (valeur or 0.0)).partition(".")
    fraction = fraction.rstrip("0")
    return "%s,%s kg" % (entier, fraction) if fraction else "%s kg" % entier


class DallyOpsReceiptService(models.AbstractModel):
    _name = "dally.ops.receipt.service"
    _description = "Dally Ops — reçu de prise en charge"

    # ------------------------------------------------------------------
    # Le contrat
    # ------------------------------------------------------------------

    @api.model
    def receipt_dto(self, reference):
        """Le reçu, relu dans Odoo à l'instant où on le demande.

        Jamais depuis un cache local, un brouillon ou le classeur : le
        document que le client emporte doit dire ce que le CRM affirme, et
        rien d'autre.
        """
        self._exiger_role_ops()
        shipment = self._resoudre_dossier(reference)
        # Enveloppe nommée, comme `{"intake": …}` ailleurs : le jour où le
        # contrat gagne un voisin, il n'y a pas de charge utile anonyme à
        # déplacer.
        return {"receipt": self._construire(shipment)}

    @api.model
    def receipt_pdf(self, reference):
        """Le même reçu, en PDF.

        Rendu par le moteur natif d'Odoo à partir du contrat ci-dessus : le
        papier et l'écran ne peuvent pas raconter deux histoires différentes.

        Le document HTML est complet et autonome, et il est remis tel quel au
        moteur. On ne passe donc pas par `_render_qweb_pdf`, qui réenveloppe
        chaque page dans `web.minimal_layout` et y injecte les paquets d'assets
        d'Odoo : le moteur PDF va alors les chercher **par HTTP** sur le
        serveur, ce qui rend l'apparence du reçu dépendante d'un aller-retour
        réseau et d'un paquet régénérable. Mesuré sur le banc, cet aller-retour
        n'aboutissait même pas pendant une transaction de test — un reçu client
        ne peut pas reposer là-dessus.

        Effet de bord souhaité : le chemin est identique en test et en
        production. `_render_qweb_pdf` renvoie du HTML sous `--test-enable`,
        si bien qu'une suite entière peut passer au vert sans qu'un seul PDF
        ait été produit.
        """
        self._exiger_role_ops()
        shipment = self._resoudre_dossier(reference)
        recu = self._construire(shipment)
        document = self.env["ir.qweb"]._render(GABARIT, {"receipt": recu})
        contenu = self.env.ref(RAPPORT).sudo()._run_wkhtmltopdf(
            [document], report_ref=RAPPORT)
        return {"filename": self._nom_de_fichier(recu), "content": contenu}

    @staticmethod
    def _nom_de_fichier(recu):
        """Un nom de fichier sûr, sans le nom du client.

        Le téléphone d'un logisticien passe de main en main ; un nom de client
        dans une liste de téléchargements en dit trop. La référence du dossier
        suffit à retrouver le document.
        """
        propre = re.sub(
            r"[^A-Za-z0-9_-]", "-", recu["reference"] or "").strip("-")[:60]
        # Le repli s'applique **après** la neutralisation, comme côté
        # navigateur : une référence qui ne laisse que des séparateurs — « .. »
        # — donnerait sinon un fichier sans nom, et les deux implémentations
        # diraient deux choses différentes du même document.
        return "Recu_DallyTrading_%s.pdf" % (propre or "recu")

    # ------------------------------------------------------------------
    # La construction
    # ------------------------------------------------------------------

    @api.model
    def _construire(self, shipment):
        societe = shipment.company_id.sudo()
        consolidation = shipment.intake_consolidation_id.sudo()
        client = shipment.sudo().partner_id
        articles = [self._article(colis) for colis in self._colis(shipment)]
        paiements = self._paiements(shipment)
        totaux = self._totaux(articles, paiements)

        return {
            # L'identité publique du dossier tient lieu d'identité du reçu :
            # créer une seconde séquence documentaire ajouterait un numéro à
            # rapprocher sans rien prouver de plus.
            "document": {
                "title": "REÇU DE PRISE EN CHARGE",
                "reference": shipment.external_reference or "",
                "generated_at": self._maintenant(),
            },
            "company": {
                "name": societe.name or "",
                "phone": societe.phone or "",
                "email": societe.email or "",
                "address": self._adresse(societe.partner_id),
                "vat": societe.vat or "",
            },
            "reference": shipment.external_reference or "",
            "local_reference": shipment.collection_local_ref or "",
            "received_on": self._date(shipment.goods_received_on),
            "state": shipment.state or "",
            "transport_mode": shipment.transport_mode or "",
            "transport_mode_label": LIBELLES_MODE.get(shipment.transport_mode, ""),
            "consolidation": {
                "reference": consolidation.name or "",
                "origin": self._lieu(consolidation, "origin"),
                "destination": self._lieu(consolidation, "destination"),
            },
            # Le client vient du dossier. Le navigateur ne le fournit jamais :
            # sans quoi le reçu d'Aissatou pourrait porter le nom de Fatou.
            "customer": {
                "name": client.name or "",
                "phone": client.phone or "",
                "email": client.email or "",
                "address": self._adresse(client),
            },
            "articles": articles,
            "totals": totaux,
            "payments": paiements,
            "operator": {"name": self._receptionnaire(shipment)},
            # Référence, jamais le document : le reçu ne remplace pas la
            # facture et ne prétend pas la porter.
            "invoice_number": self._numero_facture(shipment),
        }

    @api.model
    def _colis(self, shipment):
        """Les articles réellement enregistrés, dans leur ordre de saisie."""
        return shipment.sudo().package_ids.sorted(lambda c: (c.sequence, c.id))

    @api.model
    def _article(self, colis):
        """Un article, tel que le client peut le relire.

        La question « cet article a-t-il un prix ? » n'est pas rejouée ici :
        c'est le service des lignes qui la tranche, et la rejouer autrement
        ferait dire au reçu autre chose qu'au dossier. Un prix nul ne vaut pas
        absence de prix — un article offert reste tarifé — tandis qu'un article
        laissé sur devis n'en a pas encore, et le montant que le moteur y écrit
        (zéro) ne doit jamais paraître sur le papier : le client y lirait
        « rien à payer ».
        """
        statut = self.env["dally.ops.intake.line.service"]._statut_pricing(colis)
        tarife = statut in ("automatic", "manual")
        return {
            "description": colis.description or "",
            "goods_category": colis.goods_category or "",
            "quantity": colis.quantity or 0,
            "exact_weight_kg": colis.total_weight_kg or 0.0,
            "exact_weight_display": poids(colis.total_weight_kg),
            "billable_weight_kg": colis.billable_weight_kg or 0.0,
            "dimensions": self._dimensions(colis),
            "customs_value_xof": colis.customs_value_xof or 0.0,
            "tariff_family": LIBELLES_FAMILLE.get(
                colis.tariff_family_id.code or "", ""),
            # Le prix réellement appliqué — y compris un tarif spécial. Le
            # motif interne de ce tarif, lui, ne regarde pas le client.
            "applied_unit_price_eur": colis.applied_unit_price_eur if tarife else None,
            "transport_amount_eur": colis.transport_amount_eur if tarife else None,
            "applied_unit_price_display": (
                montant(colis.applied_unit_price_eur, "EUR") if tarife else ""),
            "transport_amount_display": (
                montant(colis.transport_amount_eur, "EUR") if tarife else ""),
        }

    @staticmethod
    def _dimensions(colis):
        cotes = [colis.length_cm, colis.width_cm, colis.height_cm]
        if not all(cotes):
            return ""
        return " × ".join("%g" % cote for cote in cotes) + " cm"

    @api.model
    def _paiements(self, shipment):
        """Les encaissements réels, un par mouvement.

        Deux paiements partiels restent deux lignes : les fondre en un seul
        total ferait disparaître leur traçabilité, et c'est précisément ce que
        le client peut avoir besoin de montrer.
        """
        collections = self.env["dally.freight.collection"].sudo().search([
            ("shipment_id", "=", shipment.id),
            ("state", "!=", "cancelled"),
        ], order="payment_date asc, id asc")
        return [{
            "date": self._date(collection.payment_date),
            "amount": collection.amount or 0.0,
            "currency_code": collection.currency_id.name or "",
            "method": LIBELLES_PAIEMENT.get(
                collection.source_method or "", collection.source_method or ""),
            "collected_by": collection.collected_by_name or "",
            "wave_reference": collection.wave_reference or "",
            "amount_display": montant(
                collection.amount or 0.0, collection.currency_id.name or ""),
        } for collection in collections]

    @api.model
    def _totaux(self, articles, paiements):
        """Poids, montant dû, encaissements — et un solde seulement s'il est vrai.

        La devise de tarification est l'euro ; les encaissements de terrain
        arrivent souvent en francs. Soustraire l'un de l'autre demanderait un
        taux, et un taux choisi ici serait faux la moitié du temps. Le solde
        n'apparaît donc que lorsque toutes les sommes sont comparables.
        """
        complet = bool(articles) and all(
            article["transport_amount_eur"] is not None for article in articles)
        total_eur = (
            sum(article["transport_amount_eur"] or 0.0 for article in articles)
            if complet else None)

        recu = {}
        for paiement in paiements:
            recu[paiement["currency_code"]] = (
                recu.get(paiement["currency_code"], 0.0) + paiement["amount"])
        encaisse = [
            {"currency_code": devise, "amount": somme,
             "display": montant(somme, devise)}
            for devise, somme in sorted(recu.items())
        ]

        devises = set(recu)
        comparable = complet and devises <= {"EUR"}
        solde = None
        motif = None
        if not complet:
            motif = "pricing_incomplete"
        elif not comparable:
            motif = "currency_mismatch"
        else:
            solde = round((total_eur or 0.0) - recu.get("EUR", 0.0), 2)

        return {
            "articles_count": len(articles),
            "weight_kg": round(
                sum(article["exact_weight_kg"] for article in articles), 3),
            "weight_display": poids(
                sum(article["exact_weight_kg"] for article in articles)),
            "transport_amount_eur": total_eur,
            "transport_amount_display": montant(total_eur, "EUR"),
            "currency_code": "EUR",
            "paid": encaisse,
            "balance_eur": solde,
            "balance_display": montant(solde, "EUR"),
            "balance_reason": motif,
        }

    # ------------------------------------------------------------------
    # Résolution et garde-fous
    # ------------------------------------------------------------------

    @api.model
    def _exiger_role_ops(self):
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))

    @api.model
    def _resoudre_dossier(self, reference):
        """Le dossier désigné par sa référence publique, et lui seul.

        Le même domaine imposé qu'aux étapes 7 à 13 : société de l'opérateur,
        origine Dally Ops, départ rattaché. Une référence forgée — `LOCAL-…`
        d'une file hors connexion, ou le dossier d'une autre société — ne
        désigne rien.
        """
        if not isinstance(reference, str) or not reference.strip():
            raise DallyOpsNotFound(_("Dossier introuvable."), code="intake_not_found")
        shipment = self.env["dally.shipment"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("external_reference", "=", reference.strip()),
            ("sync_source", "=", "backoffice"),
            ("sync_source_key", "=like", "ops:%"),
            ("intake_consolidation_id", "!=", False),
        ], limit=1)
        if not shipment:
            raise DallyOpsNotFound(_("Dossier introuvable."), code="intake_not_found")
        if shipment.state == "cancelled":
            raise DallyOpsError(
                _("Ce dossier est annulé : aucun reçu ne peut être remis."),
                code="intake_cancelled", status=409)
        return shipment

    @api.model
    def _receptionnaire(self, shipment):
        """Qui a réceptionné, d'après le journal des gestes.

        L'auteur technique de l'enregistrement est un privilège serveur ; le
        journal Ops, lui, conserve l'opérateur réel.
        """
        evenement = self.env["dally.ops.audit.event"].sudo().search([
            ("company_id", "=", shipment.company_id.id),
            ("entity_model", "=", "dally.shipment"),
            ("entity_res_id", "=", shipment.id),
            ("action", "=", "intake_created"),
        ], order="created_at asc", limit=1)
        return evenement.operator_user_id.name or ""

    @staticmethod
    def _numero_facture(shipment):
        facture = shipment.sudo().invoice_id
        if not facture or facture.state != "posted":
            return ""
        return facture.name if facture.name and facture.name != "/" else ""

    @staticmethod
    def _lieu(consolidation, cote):
        ville = getattr(consolidation, "%s_city" % cote, "") or ""
        escale = getattr(consolidation, "%s_location" % cote, "") or ""
        return ville or escale

    @staticmethod
    def _adresse(partenaire):
        return " ".join((partenaire.sudo().contact_address or "").split())

    @staticmethod
    def _date(valeur):
        return valeur.isoformat() if valeur else ""

    @api.model
    def _maintenant(self):
        from odoo import fields as champs
        return champs.Datetime.now().isoformat(timespec="minutes")
