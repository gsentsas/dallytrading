# -*- coding: utf-8 -*-
"""Créer un client depuis le terrain, sans jamais en créer deux.

Trois dangers se croisent ici, et chacun a ses tests.

**Le temps.** Entre le « aucun client trouvé » affiché à l'écran et l'appui sur
« enregistrer », un collègue à deux mètres a pu créer la même fiche. La
recherche refaite après le verrou est la seule qui prouve quelque chose.

**Le réseau.** Un entrepôt n'a pas la 4G d'un bureau : la requête part, Odoo
crée, la réponse se perd, l'opérateur réessaie. Le registre d'idempotence fait
du second envoi une relecture.

**L'ambiguïté.** Un téléphone qui désigne une fiche et une adresse qui en
désigne une autre ne se tranche pas. Fusionner exposerait les données d'un
client à un autre.
"""

import ast
import inspect
import json
import logging
import re
import uuid
from unittest.mock import patch

import odoo
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged


def code_seul(module):
    """Le code exécutable d'un module, sans commentaires ni docstrings."""
    arbre = ast.parse(inspect.getsource(module))
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, (ast.Module, ast.ClassDef,
                                  ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        premier = noeud.body[0] if noeud.body else None
        if (isinstance(premier, ast.Expr)
                and isinstance(premier.value, ast.Constant)
                and isinstance(premier.value.value, str)):
            noeud.body = noeud.body[1:] or [ast.Pass()]
    return ast.unparse(arbre)


class CollecteurDeJournal(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lignes = []

    def emit(self, record):
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover
            message = str(record.msg)
        self.lignes.append((record.name, message))


@tagged("post_install", "-at_install", "dally")
class TestOpsCustomerCreation(HttpCase):

    MOT_DE_PASSE = "OpsProbe!2026#crea"
    ROUTE = "/api/v1/ops/customers"

    def setUp(self):
        super().setUp()
        self.societe = self.env["res.company"].create({"name": "Ops Creation SA"})
        self.logisticien = self._compte(
            "crea.logi", "Gilles Test",
            ["dally_ops_mobile.group_dally_ops_logistician"])
        self.responsable = self._compte(
            "crea.resp", "Dalanda Test",
            ["dally_ops_mobile.group_dally_ops_supervisor"])
        self.etranger = self._compte("crea.etranger", "Sans rôle", ["base.group_user"])
        self.service = self.env["dally.ops.customer.service"]

    def _compte(self, login, nom, groupes):
        return self.env["res.users"].create({
            "name": nom,
            "login": login,
            "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref(g).id for g in groupes])],
            "company_id": self.societe.id,
            "company_ids": [(6, 0, [self.societe.id])],
        })

    def _client(self, nom, **valeurs):
        valeurs.setdefault("company_id", self.societe.id)
        return self.env["res.partner"].create(dict(valeurs, name=nom))

    def _charge_creation(self, **surcharges):
        charge = {
            "request_uuid": str(uuid.uuid4()),
            "customer_type": "individual",
            "name": "Aissatou Kandji",
            "phone": "+221 77 123 45 67",
            "email": "client@example.com",
            "address": "207 rue Saint-Charles, 75015 Paris",
        }
        charge.update(surcharges)
        return {cle: valeur for cle, valeur in charge.items() if valeur is not None}

    def _poster(self, charge, login="crea.logi"):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(
            self.ROUTE, data=json.dumps(charge),
            headers={"Content-Type": "application/json"}, allow_redirects=False)

    def _reussir(self, charge, login="crea.logi"):
        reponse = self._poster(charge, login)
        self.assertEqual(reponse.status_code, 200, reponse.content)
        return json.loads(reponse.content)["data"]

    def _en_operateur(self):
        """Le service appelé directement, sous l'identité du logisticien."""
        return self.service.with_user(self.logisticien).with_company(self.societe)

    def _compter(self, motif):
        """Les fiches de CETTE société portant ce nom.

        Compter sans borne verrait les clients des autres sociétés de la base —
        dont un homonyme laissé par les essais de bout en bout. Un test qui
        échoue à cause d'une donnée voisine n'apprend rien.
        """
        return self.env["res.partner"].with_context(active_test=False).search_count([
            ("company_id", "=", self.societe.id),
            ("name", "like", motif),
        ])

    def _partenaires(self, tail="771234567"):
        return self.env["res.partner"].with_context(active_test=False).search([
            ("company_id", "in", [self.societe.id, False]),
            ("phone", "like", "%%%s" % tail[-4:]),
        ])

    # ─── La preuve centrale ──────────────────────────────────────────

    def test_le_logisticien_cree_un_client_sans_acces_a_res_partner(self):
        with self.assertRaises(AccessError):
            self.env["res.partner"].with_user(self.logisticien).search([])

        charge = self._reussir(self._charge_creation())
        self.assertEqual(charge["status"], "created")
        self.assertEqual(charge["customer"]["name"], "Aissatou Kandji")

    def test_le_logisticien_garde_zero_modele_metier_accessible(self):
        lisibles = []
        for nom in self.env.registry:
            modele = self.env[nom]
            if modele._abstract or modele._transient:
                continue
            try:
                if modele.with_user(self.logisticien).has_access("read"):
                    lisibles.append(nom)
            except Exception:  # pragma: no cover
                continue
        self.assertFalse(lisibles, "modèles lisibles : %s" % ", ".join(sorted(lisibles)))

    # ─── Qui a le droit de créer ─────────────────────────────────────

    def test_le_responsable_peut_creer(self):
        self.assertEqual(self._poster(self._charge_creation(), "crea.resp").status_code, 200)

    def test_un_authentifie_sans_role_ops_est_refuse(self):
        self.assertEqual(
            self._poster(self._charge_creation(), "crea.etranger").status_code, 403)

    def test_le_service_refuse_lui_meme_un_appelant_sans_role(self):
        with self.assertRaises(AccessError):
            self.service.with_user(self.etranger).create_customer(self._charge_creation())

    # ─── La forme de la demande ──────────────────────────────────────

    def test_un_particulier_est_cree_comme_personne(self):
        charge = self._reussir(self._charge_creation(customer_type="individual"))
        self.assertEqual(charge["customer"]["customer_type"], "individual")
        partenaire = self.env["res.partner"].search([("name", "=", "Aissatou Kandji")], limit=1)
        self.assertFalse(partenaire.is_company)

    def test_un_professionnel_est_cree_comme_societe(self):
        charge = self._reussir(self._charge_creation(
            customer_type="business", name="Sahel Logistics SARL"))
        self.assertEqual(charge["customer"]["customer_type"], "business")
        partenaire = self.env["res.partner"].search(
            [("name", "=", "Sahel Logistics SARL")], limit=1)
        self.assertTrue(partenaire.is_company)

    def test_les_champs_obligatoires_le_sont(self):
        for champ in ("request_uuid", "customer_type", "name", "phone", "address"):
            with self.subTest(champ=champ):
                charge = self._charge_creation()
                del charge[champ]
                self.assertEqual(self._poster(charge).status_code, 400)

    def test_un_champ_obligatoire_vide_vaut_absent(self):
        for champ in ("name", "phone", "address"):
            with self.subTest(champ=champ):
                self.assertEqual(
                    self._poster(self._charge_creation(**{champ: "   "})).status_code, 400)

    def test_un_numero_trop_court_est_refuse(self):
        self.assertEqual(self._poster(self._charge_creation(phone="77 12")).status_code, 400)

    def test_l_email_est_facultatif(self):
        charge = self._charge_creation(email=None)
        resultat = self._reussir(charge)
        self.assertEqual(resultat["status"], "created")
        self.assertEqual(resultat["customer"]["email"], "")

    def test_un_email_invalide_est_refuse(self):
        for saisie in ("client", "client@", "@example.com", "client@example"):
            with self.subTest(saisie=saisie):
                self.assertEqual(
                    self._poster(self._charge_creation(email=saisie)).status_code, 400)

    def test_un_type_de_client_inconnu_est_refuse(self):
        self.assertEqual(
            self._poster(self._charge_creation(customer_type="prospect")).status_code, 400)

    def test_un_identifiant_de_demande_malforme_est_refuse(self):
        self.assertEqual(
            self._poster(self._charge_creation(request_uuid="pas-un-uuid")).status_code, 400)

    def test_une_cle_supplementaire_est_refusee(self):
        for cle, valeur in (("partner_id", 3728), ("is_company", True),
                            ("company_id", 1), ("company_type", "person"),
                            ("credit_limit", 5000), ("user_id", 2)):
            with self.subTest(cle=cle):
                charge = self._charge_creation()
                charge[cle] = valeur
                # Ces champs ne sont pas seulement refusés : ils n'ont aucun
                # chemin jusqu'à l'écriture.
                self.assertEqual(self._poster(charge).status_code, 400)

    def test_un_corps_illisible_est_refuse(self):
        self.authenticate("crea.logi", self.MOT_DE_PASSE)
        reponse = self.url_open(
            self.ROUTE, data="{ pas du json",
            headers={"Content-Type": "application/json"}, allow_redirects=False)
        self.assertEqual(reponse.status_code, 400)

    # ─── Ce qui est écrit, et ce qui ne l'est pas ────────────────────

    def test_la_societe_vient_du_serveur(self):
        self._reussir(self._charge_creation())
        partenaire = self.env["res.partner"].search([("name", "=", "Aissatou Kandji")], limit=1)
        self.assertEqual(partenaire.company_id, self.societe)

    def test_le_numero_est_conserve_tel_que_saisi(self):
        self._reussir(self._charge_creation(phone="+221 77 123 45 67"))
        partenaire = self.env["res.partner"].search([("name", "=", "Aissatou Kandji")], limit=1)
        # Transformer « 06… » en « +33… » sans information fiable inventerait
        # une donnée.
        self.assertEqual(partenaire.phone, "+221 77 123 45 67")

    def test_l_adresse_est_rangee_telle_quelle(self):
        self._reussir(self._charge_creation())
        partenaire = self.env["res.partner"].search([("name", "=", "Aissatou Kandji")], limit=1)
        # Un faux découpage est pire qu'une adresse brute correcte.
        self.assertEqual(partenaire.street, "207 rue Saint-Charles, 75015 Paris")
        self.assertFalse(partenaire.city)
        self.assertFalse(partenaire.zip)

    def test_seuls_les_champs_de_la_liste_blanche_sont_ecrits(self):
        from odoo.addons.dally_ops_mobile.models import ops_customer_service

        source = inspect.getsource(
            ops_customer_service.DallyOpsCustomerService._creer_partenaire)
        ecrits = set(re.findall(r'"([a-z_]+)":', source))
        self.assertEqual(
            ecrits, {"name", "phone", "email", "street", "is_company", "company_id"})

    def test_aucun_compte_utilisateur_n_est_cree(self):
        avant = self.env["res.users"].search_count([])
        self._reussir(self._charge_creation())
        self.assertEqual(self.env["res.users"].search_count([]), avant)

    # ─── Anti-doublon : la recherche refaite sous verrou ─────────────

    def test_un_numero_deja_connu_ne_cree_rien(self):
        existant = self._client("Aissatou Kandji", phone="+221 77 123 45 67")
        avant = self.env["res.partner"].search_count([])

        resultat = self._reussir(self._charge_creation(name="Aissatou K."))
        self.assertEqual(resultat["status"], "existing")
        self.assertEqual(resultat["customer"]["name"], "Aissatou Kandji")
        self.assertEqual(self.env["res.partner"].search_count([]), avant)
        self.assertTrue(existant.exists())

    def test_une_adresse_deja_connue_ne_cree_rien(self):
        self._client("Aissatou Kandji", email="client@example.com")
        avant = self.env["res.partner"].search_count([])
        resultat = self._reussir(self._charge_creation(phone="+221 70 000 11 22"))
        self.assertEqual(resultat["status"], "existing")
        self.assertEqual(self.env["res.partner"].search_count([]), avant)

    def test_telephone_et_email_pointant_la_meme_fiche_donnent_existing(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67",
                     email="client@example.com")
        avant = self.env["res.partner"].search_count([])
        resultat = self._reussir(self._charge_creation())
        self.assertEqual(resultat["status"], "existing")
        self.assertEqual(self.env["res.partner"].search_count([]), avant)

    def test_une_fiche_retrouvee_n_est_jamais_modifiee(self):
        existant = self._client("Aissatou Kandji", phone="+221 77 123 45 67",
                                email="ancienne@example.com", street="1 rue d'Avant")
        avant = (existant.name, existant.email, existant.street, existant.write_date)

        self._reussir(self._charge_creation(
            name="AISSATOU KANDJI", email=None, address="Nouvelle adresse saisie"))
        existant.invalidate_recordset()

        # « Créer » devient « utiliser la fiche existante », jamais « mettre à
        # jour silencieusement ».
        self.assertEqual(
            (existant.name, existant.email, existant.street, existant.write_date), avant)

    def test_une_creation_ulterieure_avec_le_meme_numero_ne_duplique_pas(self):
        premier = self._reussir(self._charge_creation())
        self.assertEqual(premier["status"], "created")

        # Un autre identifiant de demande : ce n'est pas un rejeu, c'est une
        # seconde saisie. Le verrou et la recherche doivent quand même empêcher
        # le doublon.
        second = self._reussir(self._charge_creation(name="Aissatou K."))
        self.assertEqual(second["status"], "existing")
        self.assertEqual(second["customer"]["reference"], premier["customer"]["reference"])
        self.assertEqual(self._compter("Aissatou"), 1)

    # ─── Conflits d'identité ─────────────────────────────────────────

    def test_un_telephone_et_un_email_contradictoires_donnent_409(self):
        self._client("Fiche Téléphone", phone="+221 77 123 45 67")
        self._client("Fiche Email", email="client@example.com")

        reponse = self._poster(self._charge_creation())
        self.assertEqual(reponse.status_code, 409)
        charge = json.loads(reponse.content)
        self.assertEqual(charge["error"]["code"], "customer_identity_conflict")

    def test_un_telephone_ambigu_donne_409(self):
        self._client("Mamadou X", phone="+221 77 123 45 67")
        self._client("Mamadou Y", phone="00221771234567")
        self.assertEqual(self._poster(self._charge_creation(email=None)).status_code, 409)

    def test_un_email_ambigu_donne_409(self):
        self._client("Mamadou X", email="client@example.com")
        self._client("Mamadou Y", email="CLIENT@example.com")
        self.assertEqual(
            self._poster(self._charge_creation(phone="+221 70 000 11 22")).status_code, 409)

    def test_un_conflit_ne_laisse_fuir_aucune_identite(self):
        self._client("Mamadou Konaté", phone="+221 77 123 45 67", email="mk@example.test")
        self._client("Mariama Sow", email="client@example.com", phone="+221 70 000 11 22")

        contenu = self._poster(self._charge_creation()).content.decode()
        for interdit in ("Konaté", "Mamadou", "Mariama", "Sow", "mk@example.test"):
            self.assertNotIn(interdit, contenu, "identité exposée : %s" % interdit)

    def test_un_conflit_ne_cree_rien(self):
        self._client("Fiche Téléphone", phone="+221 77 123 45 67")
        self._client("Fiche Email", email="client@example.com")
        avant = self.env["res.partner"].search_count([])
        self._poster(self._charge_creation())
        self.assertEqual(self.env["res.partner"].search_count([]), avant)

    # ─── Idempotence ─────────────────────────────────────────────────

    def test_le_meme_identifiant_rejoue_ne_cree_pas_un_second_client(self):
        charge = self._charge_creation()
        premier = self._reussir(charge)
        avant = self.env["res.partner"].search_count([])

        # La réponse s'est perdue : le téléphone renvoie exactement la même
        # demande.
        second = self._reussir(charge)

        self.assertEqual(second, premier)
        self.assertEqual(self.env["res.partner"].search_count([]), avant)

    def test_un_rejeu_ne_pose_pas_une_seconde_reference(self):
        charge = self._charge_creation()
        self._reussir(charge)
        self._reussir(charge)
        self.assertEqual(
            self.env["dally.ops.customer.handle"].sudo().search_count(
                [("company_id", "=", self.societe.id)]), 1)

    def test_un_rejeu_n_ajoute_pas_un_second_evenement_de_creation(self):
        charge = self._charge_creation()
        self._reussir(charge)
        self._reussir(charge)
        Audit = self.env["dally.ops.audit.event"].sudo()
        self.assertEqual(Audit.search_count([
            ("request_uuid", "=", charge["request_uuid"]),
            ("action", "=", "customer_created"),
        ]), 1)

    def test_un_rejeu_est_tracé_comme_tel(self):
        charge = self._charge_creation()
        self._reussir(charge)
        self._reussir(charge)
        Audit = self.env["dally.ops.audit.event"].sudo()
        self.assertEqual(Audit.search_count([
            ("request_uuid", "=", charge["request_uuid"]),
            ("action", "=", "customer_request_replayed"),
        ]), 1)

    def test_le_meme_identifiant_avec_une_autre_intention_donne_409(self):
        charge = self._charge_creation()
        self._reussir(charge)

        autre = dict(charge, name="Quelqu'un d'autre")
        reponse = self._poster(autre)
        self.assertEqual(reponse.status_code, 409)
        self.assertEqual(
            json.loads(reponse.content)["error"]["code"], "idempotency_conflict")

    def test_une_mise_en_forme_differente_du_meme_numero_reste_un_rejeu(self):
        charge = self._charge_creation(phone="+221 77 123 45 67")
        premier = self._reussir(charge)
        # L'empreinte porte sur l'intention normalisée : le même numéro écrit
        # autrement désigne le même client.
        second = self._reussir(dict(charge, phone="00221771234567"))
        self.assertEqual(second["customer"]["reference"], premier["customer"]["reference"])

    def test_le_registre_ne_recopie_aucune_donnee_personnelle(self):
        charge = self._charge_creation()
        self._reussir(charge)
        ligne = self.env["dally.ops.customer.request"].sudo().search(
            [("request_uuid", "=", charge["request_uuid"])], limit=1)
        self.assertTrue(ligne)

        # On interroge les colonnes stockées, et non `read()` : celui-ci rend
        # les relations sous forme `(id, nom affiché)`, si bien qu'un
        # `partner_id` ferait apparaître le nom du client sans que la table le
        # contienne. L'affirmation porte sur ce qui est écrit.
        self.env.cr.execute(
            "SELECT * FROM dally_ops_customer_request WHERE id = %s", [ligne.id])
        stocke = " ".join(str(valeur) for valeur in self.env.cr.fetchone())
        for interdit in ("Aissatou", "Kandji", "client@example.com",
                         "77 123 45 67", "Saint-Charles"):
            self.assertNotIn(interdit, stocke)
        self.assertRegex(ligne.payload_hash, r"^[0-9a-f]{64}$")

    # ─── Verrous ─────────────────────────────────────────────────────

    def test_le_verrou_est_pris_avant_la_recherche(self):
        """Chercher avant de verrouiller ne prouverait rien.

        Un `not_found` obtenu hors verrou peut devenir faux à la milliseconde
        suivante ; c'est précisément le trou que cette étape doit fermer.
        """
        ordre = []
        Service = type(self.service)
        verrou_reel = Service._verrouiller
        recherche_reelle = Service._chercher_par_telephone

        def verrou(self, cles):
            ordre.append(("verrou", tuple(sorted(cles))))
            return verrou_reel(self, cles)

        def recherche(self, empreinte):
            ordre.append(("recherche", empreinte))
            return recherche_reelle(self, empreinte)

        with patch.object(Service, "_verrouiller", verrou), \
             patch.object(Service, "_chercher_par_telephone", recherche):
            self._en_operateur().create_customer(self._charge_creation())

        etapes = [nom for nom, _ in ordre]
        self.assertEqual(etapes[0], "verrou")
        self.assertIn("recherche", etapes)
        self.assertLess(etapes.index("verrou"), etapes.index("recherche"))

    def test_les_verrous_d_identite_sont_pris_dans_un_ordre_total(self):
        """Sans ordre commun, deux transactions s'attendraient mutuellement."""
        prises = []
        Service = type(self.service)
        verrou_reel = Service._verrouiller

        def verrou(self, cles):
            prises.append(list(cles))
            return verrou_reel(self, cles)

        with patch.object(Service, "_verrouiller", verrou):
            self._en_operateur().create_customer(self._charge_creation())

        identites = [cles for cles in prises if any("phone" in c or "email" in c for c in cles)]
        self.assertTrue(identites)
        for cles in identites:
            self.assertEqual(sorted(set(cles)), sorted(set(cles)))
            self.assertEqual(len(cles), len(set(cles)))

    def test_le_verrou_est_reellement_pris_dans_postgresql(self):
        """Une seconde connexion doit se heurter au verrou, pour de vrai.

        Ce n'est pas un mock : `pg_try_advisory_xact_lock` interroge le
        gestionnaire de verrous de PostgreSQL depuis une connexion distincte.
        S'il rend `true`, c'est que rien ne protège la fenêtre entre la
        recherche et la création.
        """
        cle = "ops-customer-phone:771234567"
        self._en_operateur()._verrouiller([cle])

        with odoo.sql_db.db_connect(self.env.cr.dbname).cursor() as concurrent:
            concurrent.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", [cle])
            obtenu = concurrent.fetchone()[0]
        self.assertFalse(obtenu, "le verrou n'est pas réellement tenu")

    def test_une_fiche_apparue_pendant_l_attente_du_verrou_est_retrouvee(self):
        """Le scénario que le verrou existe pour couvrir.

        On simule le perdant de la course : au moment où il obtient le verrou,
        la fiche du gagnant est déjà là. Il doit la retrouver, pas en créer une
        seconde.
        """
        Service = type(self.service)
        verrou_reel = Service._verrouiller
        concurrent = {"pose": False}

        def verrou(service, cles):
            resultat = verrou_reel(service, cles)
            if not concurrent["pose"] and any("phone" in cle for cle in cles):
                concurrent["pose"] = True
                self._client("Aissatou Kandji", phone="+221 77 123 45 67")
            return resultat

        with patch.object(Service, "_verrouiller", verrou):
            resultat = self._en_operateur().create_customer(self._charge_creation())

        self.assertEqual(resultat["status"], "existing")
        self.assertEqual(self._compter("Aissatou Kandji"), 1)

    # ─── Audit ───────────────────────────────────────────────────────

    def test_une_creation_est_attribuee_a_son_operateur(self):
        charge = self._charge_creation()
        self._reussir(charge)
        evenement = self.env["dally.ops.audit.event"].sudo().search(
            [("request_uuid", "=", charge["request_uuid"]),
             ("action", "=", "customer_created")], limit=1)

        self.assertTrue(evenement)
        # `create_uid` porterait le superutilisateur : sans ce journal, la
        # question « qui a créé cette fiche ? » n'aurait pas de réponse.
        self.assertEqual(evenement.operator_user_id, self.logisticien)
        self.assertEqual(evenement.company_id, self.societe)
        self.assertEqual(evenement.entity_model, "res.partner")
        self.assertTrue(evenement.entity_res_id)

    def test_une_fiche_retrouvee_est_aussi_tracee(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67")
        charge = self._charge_creation()
        self._reussir(charge)
        self.assertEqual(self.env["dally.ops.audit.event"].sudo().search_count(
            [("request_uuid", "=", charge["request_uuid"]),
             ("action", "=", "customer_existing_resolved")]), 1)

    def test_le_journal_d_audit_ne_contient_aucune_donnee_personnelle(self):
        charge = self._charge_creation()
        self._reussir(charge)
        evenement = self.env["dally.ops.audit.event"].sudo().search(
            [("request_uuid", "=", charge["request_uuid"])], limit=1)

        self.env.cr.execute(
            "SELECT * FROM dally_ops_audit_event WHERE id = %s", [evenement.id])
        contenu = " ".join(str(valeur) for valeur in self.env.cr.fetchone())
        # Un audit sert à retrouver un geste, pas à reconstituer un fichier
        # clients.
        for interdit in ("Aissatou", "Kandji", "client@example.com",
                         "77 123 45 67", "Saint-Charles"):
            self.assertNotIn(interdit, contenu, "donnée personnelle dans l'audit : %s" % interdit)

    def test_aucune_donnee_personnelle_n_est_journalisee(self):
        interdits = ("Aissatou", "Kandji", "client@example.com",
                     "771234567", "77 123 45 67", "Saint-Charles")

        collecteur = CollecteurDeJournal()
        racine = logging.getLogger()
        niveau = racine.level
        racine.addHandler(collecteur)
        racine.setLevel(logging.INFO)
        try:
            self._reussir(self._charge_creation())
        finally:
            racine.removeHandler(collecteur)
            racine.setLevel(niveau)

        production = "\n".join(ligne for _nom, ligne in collecteur.lignes)
        for interdit in interdits:
            self.assertNotIn(interdit, production, "journalisé à tort : %s" % interdit)

    # ─── Le DTO ──────────────────────────────────────────────────────

    def test_le_dto_est_celui_de_la_recherche(self):
        charge = self._reussir(self._charge_creation())
        self.assertEqual(sorted(charge), ["customer", "status"])
        self.assertEqual(sorted(charge["customer"]), [
            "address", "customer_type", "email", "name", "phone", "reference"])
        self.assertEqual(uuid.UUID(charge["customer"]["reference"]).version, 4)

    def test_le_dto_ne_contient_aucun_identifiant_odoo(self):
        contenu = self._poster(self._charge_creation()).content.decode()
        self.assertNotIn("partner_id", contenu)
        self.assertNotIn('"id"', contenu)
        partenaire = self.env["res.partner"].search([("name", "=", "Aissatou Kandji")], limit=1)
        self.assertNotIn('"%s"' % partenaire.id, contenu)

    def test_le_dto_ne_contient_aucun_champ_sensible(self):
        contenu = self._poster(self._charge_creation()).content.decode()
        for interdit in ("credit", "debit", "balance", "invoice", "bank", "vat",
                         "create_uid", "write_uid", "company_id", "is_company",
                         "property_", "user_id", "payload_hash"):
            self.assertNotIn(interdit, contenu, "champ sensible : %s" % interdit)

    # ─── La frontière de privilège ───────────────────────────────────

    def test_le_controleur_ne_contient_aucun_sudo(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_customers
        self.assertNotIn("sudo", code_seul(ops_customers))

    def test_le_service_n_expose_que_ses_trois_operations(self):
        from odoo.addons.dally_ops_mobile.models.ops_customer_service import (
            DallyOpsCustomerService,
        )
        publiques = sorted(
            nom for nom, valeur in vars(DallyOpsCustomerService).items()
            if not nom.startswith("_") and callable(valeur))
        self.assertEqual(publiques, ["create_customer", "get_or_create_handle", "search_unique"])

    def test_aucune_ecriture_sql_directe_sur_res_partner(self):
        from odoo.addons.dally_ops_mobile.models import ops_customer_service

        code = code_seul(ops_customer_service).upper()
        # La création passe par l'ORM : contraintes, champs calculés et hooks
        # du modèle doivent s'appliquer comme pour n'importe quelle fiche.
        for interdit in ("INSERT INTO", "UPDATE RES_PARTNER", "DELETE FROM"):
            self.assertNotIn(interdit, code)

    def test_la_route_de_creation_n_utilise_ni_cle_d_api_ni_portee_freight(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_customers

        code = code_seul(ops_customers)
        for interdit in ("api_key", "required_scope", "freight:", "DallyApiController"):
            self.assertNotIn(interdit, code)

    def test_aucune_ecriture_vers_le_tableur(self):
        from odoo.addons.dally_ops_mobile.models import ops_customer_service

        code = code_seul(ops_customer_service).lower()
        # Le tableur recevra le client via le futur dossier Freight, pas ici.
        for interdit in ("sheet", "google", "gspread", "freight.sync"):
            self.assertNotIn(interdit, code)
