# -*- coding: utf-8 -*-
"""Retrouver un client sans pouvoir parcourir le fichier clients.

## Pourquoi pas de recherche par nom

Le CRM tient déjà cette règle et l'explique : « a first name and last name are
never matched on: homonyms are common and a false positive would attach one
person's request to another's file ». Elle vaut ici pour une raison de plus —
une recherche par nom, même honnête, est aussi un moyen de feuilleter le
fichier clients depuis un téléphone d'entrepôt. « Diop » suffirait.

Le geste de terrain n'en a pas besoin : « quel est votre numéro de téléphone ? »
est ce qu'on demande au comptoir, et c'est exactement ce que cette recherche
accepte.

## Pourquoi jamais la première correspondance

`_dally_find_existing` renvoie *une* correspondance — la meilleure selon son
ordre de fiabilité. C'est le bon comportement quand il s'agit de **rattacher**
une demande à un dossier : au pire on se trompe de fiche et un humain corrige.

Ici, ce n'est pas ce qui se joue. Renvoyer la première fiche de deux, c'est
montrer le nom, le téléphone et l'adresse de quelqu'un qui n'est pas devant le
comptoir. Alors deux correspondances valent **refus**, jamais choix. C'est la
même prudence que le repli téléphonique de Freight, qui ne relie que lorsqu'il
existe exactement une correspondance.

## Portée du privilège

- **Pourquoi** : le compte Ops n'a volontairement aucune ACL métier.
- **Sur quoi** : `res.partner` en lecture seule, `dally.ops.customer.handle`
  en lecture et création.
- **Opérations** : une recherche exacte par empreinte téléphonique ou par
  adresse électronique ; la lecture de six champs ; la pose d'un jeton.
- **Domaine** : partenaire actif, société courante ou partenaire global.

Aucune écriture sur `res.partner`. Si la fiche porte `CLIENT@EXAMPLE.COM` et
qu'on cherche `client@example.com`, on la trouve et on ne la corrige pas :
« corriger » au passage transformerait une lecture en modification silencieuse
du fichier clients par un téléphone.
"""

import hashlib
import json
import logging
import re
import uuid as uuid_module

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.dally_crm.models.res_partner import (
    PHONE_SIGNIFICANT_DIGITS,
    normalize_email,
    normalize_phone,
)

_logger = logging.getLogger(__name__)

#: Les seuls critères acceptés. Tout autre champ fait échouer la requête.
CRITERES = ("phone", "email")

#: Les seuls champs acceptés à la création. Tout autre fait échouer la demande.
CHAMPS_CREATION = ("request_uuid", "customer_type", "name", "phone", "email", "address")

#: Ceux dont l'absence rend la fiche inutilisable au comptoir.
CHAMPS_OBLIGATOIRES = ("request_uuid", "customer_type", "name", "phone", "address")

TYPES_CLIENT = {"individual": False, "business": True}

#: L'opération inscrite au registre d'idempotence.
OPERATION_CREATION = "customer.create"

#: Validation d'adresse volontairement modeste : on refuse « client », pas on
#: ne prétend pas décider si une adresse existe.
EMAIL_ACCEPTABLE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

LONGUEUR_NOM = 200
LONGUEUR_ADRESSE = 500


class DallyOpsInvalide(UserError):
    """La *forme* de la demande est refusée. Jamais son contenu."""

    code = "invalid_request"


class DallyOpsConflit(UserError):
    """Deux vérités incompatibles : on refuse plutôt que de trancher."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class DallyOpsCustomerService(models.AbstractModel):
    """Service de recherche client, sans table ni ACL."""

    _name = "dally.ops.customer.service"
    _description = "Dally Ops — recherche client"

    # ------------------------------------------------------------------
    # Entrée publique
    # ------------------------------------------------------------------

    @api.model
    def search_unique(self, criteres):
        """Résout un critère unique en zéro, un, ou « plusieurs ».

        Renvoie un dictionnaire, jamais un enregistrement : le contrôleur n'a
        donc rien sur quoi rebondir pour lire un champ de plus.
        """
        self._exiger_role_ops()
        champ, valeur = self._critere_unique(criteres)

        partenaires = (
            self._chercher_par_telephone(valeur) if champ == "phone"
            else self._chercher_par_email(valeur)
        )

        if len(partenaires) == 0:
            return {"status": "not_found", "customer": None}
        if len(partenaires) > 1:
            # Aucune donnée du client : deux fiches veulent dire qu'on ignore
            # laquelle est devant le comptoir.
            return {"status": "ambiguous", "customer": None}
        return {"status": "match", "customer": self._en_dto(partenaires)}

    # ------------------------------------------------------------------
    # Validation de la demande
    # ------------------------------------------------------------------

    @api.model
    def _critere_unique(self, criteres):
        """Exactement un critère connu, sinon la requête est invalide.

        Refuser les clés inconnues n'est pas du pédantisme : accepter
        silencieusement `{"name": "Mamadou"}` laisserait croire à l'appelant
        qu'il a cherché par nom, alors qu'il aurait cherché sur rien.
        """
        if not isinstance(criteres, dict):
            raise DallyOpsInvalide(_("Requête de recherche invalide."))

        inconnus = set(criteres) - set(CRITERES)
        if inconnus:
            raise DallyOpsInvalide(_("Critère de recherche non pris en charge."))

        fournis = [champ for champ in CRITERES if criteres.get(champ)]
        if len(fournis) != 1:
            raise DallyOpsInvalide(_("Fournissez exactement un critère de recherche."))

        champ = fournis[0]
        brut = criteres[champ]
        if not isinstance(brut, str):
            raise DallyOpsInvalide(_("Critère de recherche invalide."))

        if champ == "phone":
            valeur = normalize_phone(brut)
            if not valeur:
                # Moins de neuf chiffres : « 77 » rapprocherait la moitié du
                # fichier. Mieux vaut refuser que répondre n'importe quoi.
                raise DallyOpsInvalide(
                    _("Numéro de téléphone incomplet : %(n)s chiffres au minimum.",
                      n=PHONE_SIGNIFICANT_DIGITS))
        else:
            valeur = normalize_email(brut)
            if not valeur or "@" not in valeur:
                raise DallyOpsInvalide(_("Adresse électronique invalide."))

        return champ, valeur

    @api.model
    def _exiger_role_ops(self):
        """Le service décide lui-même pour qui il travaille."""
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))

    # ------------------------------------------------------------------
    # Les recherches privilégiées
    # ------------------------------------------------------------------

    @api.model
    def _chercher_par_telephone(self, empreinte):
        """Les partenaires dont le numéro se termine par cette empreinte.

        La comparaison se fait en SQL sur les chiffres du champ brut, comme le
        fait déjà le repli téléphonique de Freight, et pour la même raison :
        `phone_sanitized` est vide sur les fiches anciennes, et une recherche
        qui dépend de lui rate silencieusement les clients de longue date.

        `LIMIT 3` suffit à distinguer les trois cas — aucun, un seul,
        plusieurs. Ramener davantage ne servirait qu'à charger en mémoire des
        fiches qu'on a justement décidé de ne pas montrer.
        """
        # Vider le tampon de l'ORM avant de lire la table.
        #
        # Mesuré sur Odoo 19 : un `create` atteint la table tout de suite, mais
        # un `write` reste en attente. Un numéro corrigé plus tôt dans la même
        # transaction serait donc invisible au SQL brut, qui ne connaît que la
        # base — et la recherche conclurait « aucun client » à tort.
        #
        # Ce service n'écrit jamais sur `res.partner` ; la ligne protège contre
        # ce qu'un appelant aura fait avant lui.
        # Le SQL ne lit que quatre colonnes de res.partner. Les vider
        # explicitement évite qu'une écriture sans rapport soit envoyée à la
        # base par un flush global.
        self.env["res.partner"].flush_model([
            "phone", "dally_whatsapp", "active", "company_id",
        ])
        self.env.cr.execute(
            """
            SELECT id
              FROM res_partner
             WHERE active IS TRUE
               AND (company_id IS NULL OR company_id = %s)
               AND (
                    RIGHT(regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g'), %s) = %s
                 OR RIGHT(regexp_replace(COALESCE(dally_whatsapp, ''), '[^0-9]', '', 'g'), %s) = %s
               )
             ORDER BY id
             LIMIT 3
            """,
            [self.env.company.id,
             PHONE_SIGNIFICANT_DIGITS, empreinte,
             PHONE_SIGNIFICANT_DIGITS, empreinte],
        )
        return self.env["res.partner"].sudo().browse(
            [ligne[0] for ligne in self.env.cr.fetchall()])

    @api.model
    def _chercher_par_email(self, email):
        """Les partenaires dont l'adresse est exactement celle-ci.

        `lower(email) = %s` et non `ilike` : l'opérateur `ilike` d'Odoo
        interprète `%` et `_` comme des jokers, si bien qu'une recherche sur
        `a%@example.com` ramènerait tout un domaine. Une comparaison d'égalité
        n'a pas de jokers à échapper.
        """
        # Vider le tampon de l'ORM avant de lire la table.
        #
        # Mesuré sur Odoo 19 : un `create` atteint la table tout de suite, mais
        # un `write` reste en attente. Un numéro corrigé plus tôt dans la même
        # transaction serait donc invisible au SQL brut, qui ne connaît que la
        # base — et la recherche conclurait « aucun client » à tort.
        #
        # Ce service n'écrit jamais sur `res.partner` ; la ligne protège contre
        # ce qu'un appelant aura fait avant lui.
        self.env["res.partner"].flush_model(["email", "active", "company_id"])
        self.env.cr.execute(
            """
            SELECT id
              FROM res_partner
             WHERE active IS TRUE
               AND (company_id IS NULL OR company_id = %s)
               AND lower(email) = %s
             ORDER BY id
             LIMIT 3
            """,
            [self.env.company.id, email],
        )
        return self.env["res.partner"].sudo().browse(
            [ligne[0] for ligne in self.env.cr.fetchall()])

    # ------------------------------------------------------------------
    # La référence opaque
    # ------------------------------------------------------------------

    @api.model
    def get_or_create_handle(self, partenaire):
        """Le jeton du client, posé une seule fois.

        Deux téléphones peuvent chercher le même client à la même seconde. La
        contrainte d'unicité rend la course inoffensive : on tente la création
        dans un point de sauvegarde, et si la base refuse, on relit ce que
        l'autre vient d'écrire. Une course de création ne doit jamais devenir
        une erreur 500 devant un client qui attend.
        """
        Handle = self.env["dally.ops.customer.handle"].sudo()
        societe = self.env.company

        existant = Handle.search(
            [("partner_id", "=", partenaire.id), ("company_id", "=", societe.id)], limit=1)
        if existant:
            return existant.token

        try:
            with self.env.cr.savepoint():
                return Handle.create({
                    "partner_id": partenaire.id,
                    "company_id": societe.id,
                }).token
        except Exception:
            # Le point de sauvegarde a annulé notre insertion ; la ligne de
            # l'autre transaction, elle, tient.
            _logger.info("Reference client Ops deja posee par une transaction concurrente.")

        rattrapage = Handle.search(
            [("partner_id", "=", partenaire.id), ("company_id", "=", societe.id)], limit=1)
        if not rattrapage:
            raise DallyOpsInvalide(_("Impossible de préparer la référence client."))
        return rattrapage.token

    # ------------------------------------------------------------------
    # Mise en forme
    # ------------------------------------------------------------------

    @api.model
    def _en_dto(self, partenaire):
        """Six champs, et pas un de plus.

        Ni solde, ni factures, ni étiquettes, ni commercial, ni notes : rien de
        tout cela n'aide à savoir si la personne devant le comptoir est bien
        celle de la fiche.
        """
        return {
            "reference": self.get_or_create_handle(partenaire),
            "name": partenaire.name or "",
            "phone": partenaire.phone or "",
            "email": partenaire.email or "",
            "address": self._en_adresse(partenaire),
            "customer_type": "business" if partenaire.is_company else "individual",
        }

    @staticmethod
    def _en_adresse(partenaire):
        """Une seule chaîne, lisible à voix haute.

        Rendre `street`, `street2`, `zip`, `city` séparément exposerait la
        structure interne de `res.partner` sans rien apporter : l'opérateur lit
        l'adresse pour la confirmer avec le client, il ne la saisit pas.
        """
        rue = ", ".join(part for part in (partenaire.street, partenaire.street2) if part)
        ville = " ".join(part for part in (partenaire.zip, partenaire.city) if part)
        pays = partenaire.country_id.name or ""
        return ", ".join(part for part in (rue, ville, pays) if part)

    # ------------------------------------------------------------------
    # Création
    # ------------------------------------------------------------------

    @api.model
    def create_customer(self, charge):
        """Crée un client, ou retrouve celui qui existait déjà.

        L'ordre des étapes est la sécurité de cette méthode :

        1. valider la forme, sans toucher à la base ;
        2. verrouiller la demande, puis les identités, **triées** ;
        3. relire le registre d'idempotence ;
        4. **refaire la recherche** ;
        5. créer seulement si personne ne correspond.

        L'étape 4 n'est pas une redite de l'écran précédent. Entre le moment où
        le logisticien a lu « aucun client trouvé » et celui où il appuie sur
        « enregistrer », un collègue à deux mètres a pu créer la même fiche.
        Le `not_found` d'il y a trente secondes ne prouve rien ; seule une
        recherche faite **après** le verrou prouve quelque chose.
        """
        self._exiger_role_ops()
        donnees = self._valider_creation(charge)

        # Le verrou de la demande d'abord : il sérialise les tentatives d'un
        # même téléphone. Les verrous d'identité ensuite, triés. Deux
        # transactions portant des identifiants différents ne se disputent
        # jamais le premier, et prennent les seconds dans le même ordre : il
        # n'existe donc pas de cycle d'attente.
        self._verrouiller([self._cle_demande(donnees["request_uuid"])])
        self._verrouiller(self._cles_identite(donnees))

        rejeu = self._rejeu(donnees)
        if rejeu is not None:
            return rejeu

        existant = self._resoudre_avant_creation(donnees)
        if existant:
            # Aucune écriture. Le logisticien vient peut-être de saisir une
            # nouvelle adresse ou une autre orthographe : corriger la fiche au
            # passage serait une modification silencieuse du fichier clients,
            # décidée par personne. La correction est un geste à part.
            return self._conclure(donnees, existant, "existing")

        partenaire = self._creer_partenaire(donnees)
        return self._conclure(donnees, partenaire, "created")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @api.model
    def _valider_creation(self, charge):
        """La charge, réduite à sa forme canonique.

        Rien de ce que le navigateur envoie n'atteint `res.partner`
        directement : cette méthode reconstruit un dictionnaire à partir de
        champs nommés un par un. `is_company`, `company_id`, `partner_id` ne
        sont pas seulement refusés — ils n'ont aucun chemin jusqu'à l'écriture.
        """
        if not isinstance(charge, dict):
            raise DallyOpsInvalide(_("Demande de création invalide."))

        inconnus = set(charge) - set(CHAMPS_CREATION)
        if inconnus:
            raise DallyOpsInvalide(_("Champ non pris en charge dans la demande."))

        for champ in CHAMPS_OBLIGATOIRES:
            valeur = charge.get(champ)
            if not isinstance(valeur, str) or not valeur.strip():
                raise DallyOpsInvalide(_("Champ obligatoire manquant : %(champ)s.", champ=champ))

        identifiant = charge["request_uuid"].strip()
        try:
            # La version n'est pas imposée : un UUID v7 est aussi unique qu'un
            # v4, et le refuser coupleraient l'API à la bibliothèque du client.
            uuid_module.UUID(identifiant)
        except ValueError:
            raise DallyOpsInvalide(_("Identifiant de demande invalide."))

        type_client = charge["customer_type"].strip()
        if type_client not in TYPES_CLIENT:
            raise DallyOpsInvalide(_("Type de client inconnu."))

        nom = charge["name"].strip()[:LONGUEUR_NOM]
        adresse = charge["address"].strip()[:LONGUEUR_ADRESSE]

        telephone = charge["phone"].strip()
        empreinte = normalize_phone(telephone)
        if not empreinte:
            raise DallyOpsInvalide(
                _("Numéro de téléphone incomplet : %(n)s chiffres au minimum.",
                  n=PHONE_SIGNIFICANT_DIGITS))

        brut_email = charge.get("email")
        email = normalize_email(brut_email) if isinstance(brut_email, str) else None
        if email and not EMAIL_ACCEPTABLE.match(email):
            raise DallyOpsInvalide(_("Adresse électronique invalide."))

        return {
            "request_uuid": identifiant,
            "customer_type": type_client,
            "name": nom,
            # Conservé tel que saisi : transformer « 06… » en « +33… » sans
            # information fiable inventerait une donnée.
            "phone": telephone,
            "phone_tail": empreinte,
            "email": brut_email.strip() if isinstance(brut_email, str) and email else "",
            "email_normalise": email or "",
            "address": adresse,
        }

    @staticmethod
    def _empreinte(donnees):
        """SHA-256 de l'intention, jamais de la charge brute.

        Les valeurs entrent sous leur forme normalisée : c'est elle qui décide
        du résultat, et deux écritures qui aboutissent à la même fiche ne
        doivent pas être vues comme deux intentions différentes.
        """
        canonique = json.dumps({
            "customer_type": donnees["customer_type"],
            "name": donnees["name"],
            "phone": donnees["phone_tail"],
            "email": donnees["email_normalise"],
            "address": donnees["address"],
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonique.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Verrous
    # ------------------------------------------------------------------

    @staticmethod
    def _cle_demande(identifiant):
        return "ops-customer-request:%s" % identifiant

    @staticmethod
    def _cles_identite(donnees):
        cles = ["ops-customer-phone:%s" % donnees["phone_tail"]]
        if donnees["email_normalise"]:
            cles.append("ops-customer-email:%s" % donnees["email_normalise"])
        return cles

    @api.model
    def _verrouiller(self, cles):
        """Verrous consultatifs, pris dans un ordre total.

        `sorted` n'est pas cosmétique. Deux transactions qui prendraient le
        verrou du téléphone et celui de l'adresse dans des ordres opposés
        s'attendraient mutuellement, et PostgreSQL en tuerait une. Trier donne
        à tout le monde le même ordre, donc aucun cycle possible.

        `xact` : les verrous tombent avec la transaction, réussie ou non. Rien
        à libérer à la main, rien à oublier dans un chemin d'erreur.
        """
        for cle in sorted(set(cles)):
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [cle])

    # ------------------------------------------------------------------
    # Idempotence
    # ------------------------------------------------------------------

    @api.model
    def _rejeu(self, donnees):
        """Le résultat déjà obtenu, si cette demande a déjà été traitée."""
        Registre = self.env["dally.ops.customer.request"].sudo()
        ligne = Registre.search([
            ("company_id", "=", self.env.company.id),
            ("operation", "=", OPERATION_CREATION),
            ("request_uuid", "=", donnees["request_uuid"]),
        ], limit=1)
        if not ligne:
            return None

        if ligne.payload_hash != self._empreinte(donnees):
            # Même identifiant, autre intention. Renvoyer le premier résultat
            # ferait croire à l'opérateur qu'il a enregistré ce qu'il vient de
            # taper.
            raise DallyOpsConflit(
                "idempotency_conflict",
                _("Cette demande a déjà été traitée avec des informations différentes."))

        self._journaliser("customer_request_replayed", ligne.partner_id, donnees["request_uuid"])
        return {
            "status": ligne.state,
            "customer": self._en_dto(ligne.partner_id),
        }

    # ------------------------------------------------------------------
    # Résolution et création
    # ------------------------------------------------------------------

    @api.model
    def _resoudre_avant_creation(self, donnees):
        """Qui correspond à ces coordonnées, une fois les verrous tenus.

        Deux identités, deux réponses possibles, et un refus quand elles se
        contredisent : un téléphone qui désigne une fiche et une adresse qui en
        désigne une autre ne se tranche pas automatiquement. Fusionner serait
        exposer les données d'un client à un autre.
        """
        par_telephone = self._chercher_par_telephone(donnees["phone_tail"])
        par_email = (
            self._chercher_par_email(donnees["email_normalise"])
            if donnees["email_normalise"] else self.env["res.partner"].sudo().browse()
        )

        if len(par_telephone) > 1 or len(par_email) > 1:
            raise DallyOpsConflit("customer_identity_conflict", self._message_conflit())
        if par_telephone and par_email and par_telephone.id != par_email.id:
            raise DallyOpsConflit("customer_identity_conflict", self._message_conflit())

        return par_telephone or par_email

    @staticmethod
    def _message_conflit():
        """Le même message pour toutes les contradictions d'identité.

        Il ne dit ni combien de fiches, ni lesquelles, ni ce qui a divergé du
        téléphone ou de l'adresse : décrire le conflit reviendrait à décrire
        des fiches qu'on a justement décidé de ne pas montrer.
        """
        return _("Ces coordonnées correspondent à plusieurs fiches clients. "
                 "Demandez une vérification au responsable.")

    @api.model
    def _creer_partenaire(self, donnees):
        """Un contact, et rien de plus.

        Les valeurs sont construites champ par champ. Passer la charge reçue à
        `create` laisserait le navigateur écrire n'importe quelle colonne de
        `res.partner` — un utilisateur portail, un compte bancaire, une limite
        de crédit.

        `company_id` vient du serveur : une fiche créée depuis le terrain
        appartient à la société de l'opérateur, jamais à celle qu'un corps de
        requête aurait nommée.
        """
        valeurs = {
            "name": donnees["name"],
            "phone": donnees["phone"],
            "email": donnees["email"] or False,
            "street": donnees["address"],
            "is_company": TYPES_CLIENT[donnees["customer_type"]],
            "company_id": self.env.company.id,
        }
        # L'ORM et non un INSERT : contraintes, champs calculés et hooks du
        # modèle doivent s'appliquer comme pour n'importe quelle fiche.
        return self.env["res.partner"].sudo().create(valeurs)

    @api.model
    def _conclure(self, donnees, partenaire, etat):
        """Inscrit la demande au registre, journalise, et rend le DTO."""
        dto = self._en_dto(partenaire)
        Handle = self.env["dally.ops.customer.handle"].sudo()
        handle = Handle.search([
            ("partner_id", "=", partenaire.id),
            ("company_id", "=", self.env.company.id),
        ], limit=1)

        self.env["dally.ops.customer.request"].sudo().create({
            "request_uuid": donnees["request_uuid"],
            "company_id": self.env.company.id,
            "operation": OPERATION_CREATION,
            "payload_hash": self._empreinte(donnees),
            "state": etat,
            "partner_id": partenaire.id,
            "customer_handle_id": handle.id or False,
            "operator_user_id": self.env.uid,
        })

        self._journaliser(
            "customer_created" if etat == "created" else "customer_existing_resolved",
            partenaire, donnees["request_uuid"])
        return {"status": etat, "customer": dto}

    @api.model
    def _journaliser(self, action, partenaire, request_uuid):
        """Le geste, son auteur, son horodatage. Aucune donnée personnelle.

        `create_uid` porterait le superutilisateur, puisque l'écriture passe
        par un privilège : sans ce journal, la question « qui a créé cette
        fiche ? » n'aurait pas de réponse.
        """
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": action,
            "entity_model": "res.partner",
            "entity_res_id": partenaire.id,
            "request_uuid": request_uuid,
            "created_at": fields.Datetime.now(),
        })
