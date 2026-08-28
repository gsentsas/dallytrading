# -*- coding: utf-8 -*-
"""Retrouver un client sans pouvoir feuilleter le fichier clients.

Deux propriétés se jouent ici, et elles ne se voient pas dans le code sans
test.

La première est celle de l'étape précédente : un compte à **zéro modèle
accessible** obtient une réponse. La seconde lui est propre — **deux
correspondances valent refus**, jamais choix. Renvoyer la première fiche de
deux, ce serait montrer le nom, le téléphone et l'adresse de quelqu'un qui
n'est pas devant le comptoir.
"""

import ast
import inspect
import json
import logging
import re
import uuid
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
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
    """Retient tout ce qui est journalisé, pour vérifier ce qui ne l'est pas."""

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
class TestOpsCustomers(HttpCase):

    MOT_DE_PASSE = "OpsProbe!2026#cust"
    ROUTE = "/api/v1/ops/customers/search"

    def setUp(self):
        super().setUp()
        # Société dédiée : les tests ne doivent dépendre ni des clients déjà
        # présents en base, ni de ceux qu'une autre campagne y laisserait.
        self.societe = self.env["res.company"].create({"name": "Ops Clients SA"})
        self.logisticien = self._compte(
            "cust.logi", "Gilles Test",
            ["dally_ops_mobile.group_dally_ops_logistician"])
        self.responsable = self._compte(
            "cust.resp", "Dalanda Test",
            ["dally_ops_mobile.group_dally_ops_supervisor"])
        self.etranger = self._compte("cust.etranger", "Sans rôle", ["base.group_user"])
        self.senegal = self.env.ref("base.sn")

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

    def _chercher(self, corps, login="cust.logi"):
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open(
            self.ROUTE,
            data=json.dumps(corps),
            headers={"Content-Type": "application/json"},
            allow_redirects=False,
        )

    def _charge(self, corps, login="cust.logi"):
        reponse = self._chercher(corps, login)
        self.assertEqual(reponse.status_code, 200, reponse.content)
        return json.loads(reponse.content)["data"]

    # ─── La preuve centrale ──────────────────────────────────────────

    def test_le_logisticien_ne_lit_pas_res_partner_mais_retrouve_son_client(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67")

        with self.assertRaises(AccessError):
            self.env["res.partner"].with_user(self.logisticien).search([])

        charge = self._charge({"phone": "+221 77 123 45 67"})
        self.assertEqual(charge["status"], "match")
        self.assertEqual(charge["customer"]["name"], "Aissatou Kandji")

    def test_le_logisticien_garde_zero_modele_metier_accessible(self):
        self.assertFalse(
            self.env["res.partner"].with_user(self.logisticien).has_access("read"))
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

    # ─── Qui a le droit de chercher ──────────────────────────────────

    def test_le_logisticien_est_autorise(self):
        self.assertEqual(self._chercher({"phone": "771234567"}).status_code, 200)

    def test_le_responsable_est_autorise(self):
        self.assertEqual(
            self._chercher({"phone": "771234567"}, "cust.resp").status_code, 200)

    def test_un_authentifie_sans_role_ops_est_refuse(self):
        reponse = self._chercher({"phone": "771234567"}, "cust.etranger")
        self.assertEqual(reponse.status_code, 403)

    def test_le_service_refuse_lui_meme_un_appelant_sans_role(self):
        service = self.env["dally.ops.customer.service"].with_user(self.etranger)
        with self.assertRaises(AccessError):
            service.search_unique({"phone": "771234567"})

    # ─── Le téléphone, dans toutes ses écritures ─────────────────────

    def test_un_numero_senegalais_se_retrouve_quelle_que_soit_sa_forme(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67")
        for saisie in ("+221 77 123 45 67", "00221771234567", "221771234567",
                       "77 123 45 67", "771234567"):
            with self.subTest(saisie=saisie):
                charge = self._charge({"phone": saisie})
                self.assertEqual(charge["status"], "match")
                self.assertEqual(charge["customer"]["name"], "Aissatou Kandji")

    def test_un_numero_francais_se_retrouve_quelle_que_soit_sa_forme(self):
        self._client("Mamadou Diallo", phone="+33 6 12 34 56 78")
        for saisie in ("+33 6 12 34 56 78", "06 12 34 56 78", "0612345678", "612345678"):
            with self.subTest(saisie=saisie):
                charge = self._charge({"phone": saisie})
                self.assertEqual(charge["status"], "match")

    def test_un_numero_whatsapp_est_aussi_comparé(self):
        self._client("Fatou Sow", phone=False, dally_whatsapp="+221 76 111 22 33")
        self.assertEqual(self._charge({"phone": "761112233"})["status"], "match")

    def test_un_numero_trop_court_est_refuse(self):
        for saisie in ("77", "0612", "77123456", ""):
            with self.subTest(saisie=saisie):
                reponse = self._chercher({"phone": saisie})
                self.assertEqual(reponse.status_code, 400)

    def test_un_numero_trop_court_ne_touche_jamais_la_base(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67")
        # « 77 » rapprocherait la moitié du fichier : la demande doit être
        # refusée avant même d'être une recherche.
        self.assertEqual(self._chercher({"phone": "77"}).status_code, 400)

    # ─── L'adresse électronique ──────────────────────────────────────

    def test_une_adresse_exacte_retrouve_le_client(self):
        self._client("Aissatou Kandji", email="client@example.com")
        self.assertEqual(self._charge({"email": "client@example.com"})["status"], "match")

    def test_la_casse_de_l_adresse_n_a_pas_d_importance(self):
        self._client("Aissatou Kandji", email="CLIENT@EXAMPLE.COM")
        charge = self._charge({"email": "  Client@Example.com  "})
        self.assertEqual(charge["status"], "match")

    def test_une_adresse_partielle_ne_trouve_rien(self):
        self._client("Aissatou Kandji", email="client@example.com")
        for saisie in ("client", "client@", "example.com", "@example.com"):
            with self.subTest(saisie=saisie):
                reponse = self._chercher({"email": saisie})
                # Soit la requête est refusée, soit elle ne trouve rien : dans
                # les deux cas, aucune fiche ne sort.
                if reponse.status_code == 200:
                    self.assertEqual(
                        json.loads(reponse.content)["data"]["status"], "not_found")
                else:
                    self.assertEqual(reponse.status_code, 400)

    def test_un_numero_corrige_dans_la_meme_transaction_est_vu(self):
        """Le SQL brut ne connaît que la base, et l'ORM diffère ses écritures.

        Mesuré : un `create` atteint la table immédiatement, un `write` non.
        Sans vidage du tampon, un numéro corrigé quelques lignes plus haut
        serait invisible et la recherche conclurait « aucun client » à tort.
        """
        partenaire = self._client("Aissatou Kandji", phone="+221 70 000 00 00")
        partenaire.phone = "+221 77 123 45 67"
        charge = self._charge({"phone": "771234567"})
        self.assertEqual(charge["status"], "match")
        self.assertEqual(charge["customer"]["name"], "Aissatou Kandji")

    def test_un_joker_sql_ne_ramene_pas_tout_un_domaine(self):
        self._client("Aissatou Kandji", email="client@example.com")
        self._client("Mamadou Diallo", email="autre@example.com")
        # `ilike` interpréterait `%` comme un joker et ramènerait les deux.
        charge = self._charge({"email": "%@example.com"})
        self.assertEqual(charge["status"], "not_found")

    # ─── Zéro, un, plusieurs ─────────────────────────────────────────

    def test_aucune_correspondance_n_est_pas_une_erreur(self):
        charge = self._charge({"phone": "+221 77 999 88 77"})
        self.assertEqual(charge, {"status": "not_found", "customer": None})

    def test_une_seule_correspondance_est_renvoyee(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67")
        self.assertEqual(self._charge({"phone": "771234567"})["status"], "match")

    def test_deux_numeros_identiques_donnent_une_ambiguite(self):
        self._client("Mamadou Diallo", phone="+221 77 123 45 67")
        self._client("Mamadou Diallo", phone="00221771234567")
        charge = self._charge({"phone": "771234567"})
        self.assertEqual(charge, {"status": "ambiguous", "customer": None})

    def test_deux_adresses_identiques_donnent_une_ambiguite(self):
        self._client("Mamadou X", email="client@example.com")
        self._client("Mamadou Y", email="CLIENT@example.com")
        self.assertEqual(self._charge({"email": "client@example.com"})["status"], "ambiguous")

    def test_une_ambiguite_ne_laisse_fuir_aucune_donnee_personnelle(self):
        self._client("Mamadou Konaté", phone="+221 77 123 45 67",
                     email="konate@example.com", street="12 rue des Manguiers")
        self._client("Mariama Konaté", phone="221771234567",
                     email="mariama@example.com", street="8 avenue Blaise Diagne")

        contenu = self._chercher({"phone": "771234567"}).content.decode()
        for interdit in ("Konaté", "Mamadou", "Mariama", "konate@example.com",
                         "mariama@example.com", "Manguiers", "Blaise Diagne"):
            self.assertNotIn(interdit, contenu, "donnée personnelle exposée : %s" % interdit)

    # ─── Le périmètre ────────────────────────────────────────────────

    def test_un_client_archive_est_invisible(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67", active=False)
        self.assertEqual(self._charge({"phone": "771234567"})["status"], "not_found")

    def test_un_client_d_une_autre_societe_est_invisible(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67",
                     company_id=self.env.company.id)
        self.assertEqual(self._charge({"phone": "771234567"})["status"], "not_found")

    def test_un_client_global_est_visible(self):
        # `company_id = False` : un partenaire partagé par toutes les sociétés.
        self._client("Aissatou Kandji", phone="+221 77 123 45 67", company_id=False)
        self.assertEqual(self._charge({"phone": "771234567"})["status"], "match")

    def test_le_navigateur_ne_choisit_jamais_la_societe(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67",
                     company_id=self.env.company.id)
        reponse = self._chercher({"phone": "771234567", "company_id": self.env.company.id})
        # Une clé inconnue fait échouer la demande plutôt que de l'élargir.
        self.assertEqual(reponse.status_code, 400)

    # ─── La forme de la demande ──────────────────────────────────────

    def test_la_recherche_par_nom_n_existe_pas(self):
        self._client("Mamadou Diallo", phone="+221 77 123 45 67")
        reponse = self._chercher({"name": "Mamadou"})
        self.assertEqual(reponse.status_code, 400)
        self.assertNotIn("Mamadou Diallo", reponse.content.decode())

    def test_il_faut_exactement_un_critere(self):
        for corps in ({}, {"phone": "771234567", "email": "client@example.com"},
                      {"phone": ""}, {"phone": None}):
            with self.subTest(corps=corps):
                self.assertEqual(self._chercher(corps).status_code, 400)

    def test_un_critere_qui_n_est_pas_une_chaine_est_refuse(self):
        self.assertEqual(self._chercher({"phone": 771234567}).status_code, 400)

    def test_un_corps_illisible_est_refuse(self):
        self.authenticate("cust.logi", self.MOT_DE_PASSE)
        reponse = self.url_open(
            self.ROUTE, data="{ pas du json",
            headers={"Content-Type": "application/json"}, allow_redirects=False)
        self.assertEqual(reponse.status_code, 400)

    def test_le_refus_de_forme_ne_decrit_jamais_la_base(self):
        contenu = self._chercher({"name": "Mamadou"}).content.decode()
        for indice in ("res.partner", "SELECT", "Traceback", "res_partner", "group_"):
            self.assertNotIn(indice, contenu)

    # ─── Le contrat du DTO ───────────────────────────────────────────

    def test_le_dto_a_exactement_les_champs_prevus(self):
        self._client("Aissatou Kandji", phone="+33 6 12 34 56 78",
                     email="client@example.com", street="207 rue Saint-Charles",
                     zip="75015", city="Paris",
                     country_id=self.env.ref("base.fr").id)
        client = self._charge({"email": "client@example.com"})["customer"]
        self.assertEqual(sorted(client), [
            "address", "customer_type", "email", "name", "phone", "reference"])
        self.assertEqual(client["address"], "207 rue Saint-Charles, 75015 Paris, France")
        self.assertEqual(client["customer_type"], "individual")

    def test_une_societe_est_annoncee_comme_telle(self):
        self._client("Sahel Logistics SARL", email="contact@sahel.test", is_company=True)
        client = self._charge({"email": "contact@sahel.test"})["customer"]
        self.assertEqual(client["customer_type"], "business")

    def test_une_coordonnee_absente_vaut_vide_et_n_est_jamais_inventee(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67", email=False)
        client = self._charge({"phone": "771234567"})["customer"]
        self.assertEqual(client["email"], "")
        self.assertEqual(client["address"], "")

    def test_le_dto_ne_contient_aucun_identifiant_odoo(self):
        partenaire = self._client("Aissatou Kandji", phone="+221 77 123 45 67")
        contenu = self._chercher({"phone": "771234567"}).content.decode()
        self.assertNotIn("partner_id", contenu)
        self.assertNotIn('"id"', contenu)
        self.assertNotIn(str(partenaire.id), contenu)

    def test_le_dto_ne_contient_aucun_champ_sensible(self):
        partenaire = self._client(
            "Aissatou Kandji", phone="+221 77 123 45 67",
            email="client@example.com", comment="Note interne réservée",
            ref="CODE-INTERNE-42", website="https://exemple.test")
        self.assertTrue(partenaire.comment)
        contenu = self._chercher({"phone": "771234567"}).content.decode()
        for interdit in ("Note interne", "CODE-INTERNE-42", "exemple.test",
                         "credit", "debit", "balance", "invoice", "bank",
                         "category_id", "user_id", "create_uid", "write_uid",
                         "company_id", "property_", "comment", "ref\"", "vat",
                         "parent_id", "child_ids", "sourcing", "trade"):
            self.assertNotIn(interdit, contenu, "champ ou valeur sensible : %s" % interdit)

    # ─── La référence opaque ─────────────────────────────────────────

    def test_la_reference_est_un_uuid_et_non_un_compteur(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67")
        reference = self._charge({"phone": "771234567"})["customer"]["reference"]
        # Un UUID v4 : tiré au hasard, sans ordre, sans information sur la base.
        jeton = uuid.UUID(reference)
        self.assertEqual(jeton.version, 4)

    def test_la_reference_est_stable_d_une_recherche_a_l_autre(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67",
                     email="client@example.com")
        par_telephone = self._charge({"phone": "771234567"})["customer"]["reference"]
        par_email = self._charge({"email": "client@example.com"})["customer"]["reference"]
        self.assertEqual(par_telephone, par_email)

    def test_deux_clients_ont_deux_references_sans_rapport(self):
        self._client("Aissatou Kandji", email="a@example.com")
        self._client("Mamadou Diallo", email="b@example.com")
        premiere = self._charge({"email": "a@example.com"})["customer"]["reference"]
        seconde = self._charge({"email": "b@example.com"})["customer"]["reference"]
        self.assertNotEqual(premiere, seconde)

    def test_une_course_de_creation_relit_la_reference_de_l_autre(self):
        """Deux téléphones cherchent le même client à la même seconde.

        On simule le perdant : au moment où il regarde, la référence n'existe
        pas encore ; au moment où il écrit, elle existe déjà. Il doit relire,
        pas échouer — une course ne devient jamais une erreur 500 devant un
        client qui attend.
        """
        partenaire = self._client("Aissatou Kandji", phone="+221 77 123 45 67")
        service = self.env["dally.ops.customer.service"]
        with patch.object(type(self.env["res.users"]), "_dally_ops_role",
                          return_value="logistician"):
            attendu = service.get_or_create_handle(partenaire)

            Handle = type(self.env["dally.ops.customer.handle"])
            recherche_reelle = Handle.search
            appels = {"n": 0}

            def recherche_aveugle(self, domaine, *args, **kwargs):
                appels["n"] += 1
                if appels["n"] == 1:
                    return self.browse()
                return recherche_reelle(self, domaine, *args, **kwargs)

            with patch.object(Handle, "search", recherche_aveugle):
                obtenu = service.get_or_create_handle(partenaire)

        self.assertEqual(obtenu, attendu)
        self.assertEqual(
            self.env["dally.ops.customer.handle"].sudo().search_count(
                [("partner_id", "=", partenaire.id)]), 1)

    def test_la_contrainte_interdit_deux_references_pour_un_client(self):
        partenaire = self._client("Aissatou Kandji", email="a@example.com")
        Handle = self.env["dally.ops.customer.handle"].sudo()
        Handle.create({"partner_id": partenaire.id, "company_id": self.societe.id})
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                Handle.create({"partner_id": partenaire.id, "company_id": self.societe.id})

    # ─── La lecture ne modifie rien ──────────────────────────────────

    def test_la_recherche_ne_corrige_jamais_la_fiche(self):
        partenaire = self._client("Aissatou Kandji", email="CLIENT@EXAMPLE.COM",
                                  phone="00221 77 123 45 67")
        avant = (partenaire.email, partenaire.phone, partenaire.write_date)

        self._charge({"email": "client@example.com"})
        partenaire.invalidate_recordset()

        # « Corriger » au passage transformerait une lecture en modification
        # silencieuse du fichier clients par un téléphone.
        self.assertEqual((partenaire.email, partenaire.phone, partenaire.write_date), avant)

    # ─── Les journaux ────────────────────────────────────────────────

    def test_aucune_donnee_personnelle_n_est_journalisee(self):
        self._client("Aissatou Kandji", phone="+221 77 123 45 67",
                     email="client@example.com", street="207 rue Saint-Charles")

        interdits = ("Aissatou", "Kandji", "client@example.com",
                     "771234567", "77 123 45 67", "Saint-Charles")

        # Deux captures, deux affirmations distinctes.
        #
        # À DEBUG, Odoo journalise chaque requête SQL **et ses paramètres** :
        # une empreinte téléphonique y apparaît forcément, et ce n'est pas notre
        # code qui l'écrit. On vérifie donc séparément ce que la production
        # écrit vraiment (INFO), puis ce que notre module écrit à n'importe quel
        # niveau — le seul des deux que nous maîtrisons.
        production = self._capturer(logging.INFO, {"phone": "+221 77 123 45 67"})
        for interdit in interdits:
            self.assertNotIn(interdit, production, "journalisé à tort : %s" % interdit)

        notre_module = "\n".join(
            ligne for nom, ligne in self._capturer_par_source(
                logging.DEBUG, {"phone": "+221 77 123 45 67"})
            if nom.startswith("odoo.addons.dally_ops_mobile"))
        for interdit in interdits:
            self.assertNotIn(interdit, notre_module, "journalisé à tort : %s" % interdit)

    def _capturer(self, niveau_capture, corps):
        return "\n".join(
            ligne for _nom, ligne in self._capturer_par_source(niveau_capture, corps))

    def _capturer_par_source(self, niveau_capture, corps):
        collecteur = CollecteurDeJournal()
        racine = logging.getLogger()
        niveau = racine.level
        racine.addHandler(collecteur)
        racine.setLevel(niveau_capture)
        try:
            self._charge(corps)
        finally:
            racine.removeHandler(collecteur)
            racine.setLevel(niveau)
        return collecteur.lignes

    # ─── La frontière de privilège ───────────────────────────────────

    def test_le_controleur_ne_contient_aucun_sudo(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_customers
        self.assertNotIn("sudo", code_seul(ops_customers))

    def test_le_service_n_expose_que_ses_operations_declarees(self):
        from odoo.addons.dally_ops_mobile.models.ops_customer_service import (
            DallyOpsCustomerService,
        )
        publiques = sorted(
            nom for nom, valeur in vars(DallyOpsCustomerService).items()
            if not nom.startswith("_") and callable(valeur))
        self.assertEqual(
            publiques, ["create_customer", "get_or_create_handle", "search_unique"])

    def test_le_service_ne_privilegie_que_les_modeles_declares(self):
        from odoo.addons.dally_ops_mobile.models import ops_customer_service

        # `ast.unparse` normalise les guillemets : on compare sans eux.
        code = code_seul(ops_customer_service).replace("'", '"')

        # La liste, et rien qu'elle : le fichier client sous privilège, la
        # référence opaque, le registre d'idempotence et le journal d'audit.
        # Un modèle de plus ici, c'est une surface de plus qu'aucune ACL ne
        # borne.
        prives = set(re.findall(r'self\.env\["([^"]+)"\]\.sudo\(\)', code))
        self.assertEqual(prives, {
            "res.partner",
            "dally.ops.customer.handle",
            "dally.ops.customer.request",
            "dally.ops.audit.event",
        })

        # Le SQL brut est un privilège plus large qu'un `sudo` : il ne doit
        # toucher qu'une seule table, et jamais une jointure ouverte.
        tables = set(re.findall(r"FROM\s+([a-z_]+)", code))
        self.assertEqual(tables, {"res_partner"})
        # Sans `.upper()` : les mots-clés SQL sont en majuscules dans ce
        # fichier, alors que `", ".join(...)` de Python est en minuscules.
        self.assertNotIn("JOIN", code)

    def test_aucune_methode_generique_de_privilege(self):
        from odoo.addons.dally_ops_mobile.models import ops_customer_service

        code = code_seul(ops_customer_service)
        for interdit in ("sudo_search", "ops_sudo", "def search_model"):
            self.assertNotIn(interdit, code)

    def test_la_route_n_utilise_ni_cle_d_api_ni_portee_freight(self):
        from odoo.addons.dally_ops_mobile.controllers import ops_customers

        code = code_seul(ops_customers)
        for interdit in ("api_key", "required_scope", "freight:", "DallyApiController"):
            self.assertNotIn(interdit, code)
        declaration = inspect.getsource(ops_customers)
        self.assertIn('auth="user"', declaration)
        self.assertIn('methods=["POST"]', declaration)

    def test_la_route_refuse_la_methode_GET(self):
        """Un numéro dans une URL finit dans les journaux d'un proxy."""
        self.authenticate("cust.logi", self.MOT_DE_PASSE)
        reponse = self.url_open(self.ROUTE + "?phone=771234567", allow_redirects=False)
        self.assertNotEqual(reponse.status_code, 200)
