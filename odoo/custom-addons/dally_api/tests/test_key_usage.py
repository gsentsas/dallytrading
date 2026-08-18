"""
La télémétrie d'usage : elle compte juste, et elle ne casse jamais rien.

Deux propriétés dominent ce fichier, et la seconde est la vraie raison d'être de
toute l'architecture :

* **l'exactitude** — un événement est compté une fois et une seule, même si deux
  agrégateurs tournent en même temps, même si une agrégation échoue en cours ;
* **l'isolation** — une panne de la télémétrie ne doit ni annuler, ni rejouer, ni
  faire échouer la transaction métier. C'est ce que vérifie
  `TestIsolationTelemetrie`, et c'est le test qui valide l'architecture.
"""

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally_api")
class TestTelemetrieUsage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Cle = cls.env["dally.api.key"]
        cls.Usage = cls.env["dally.api.key.usage"]
        cls.cle_a = cls.Cle.create({"name": "Essai télémétrie A", "scopes": "services:read"})
        cls.cle_b = cls.Cle.create({"name": "Essai télémétrie B", "scopes": "services:read"})

    def _evenements(self, cle=None, nombre=1, moment=None):
        """Crée des événements par l'ORM.

        Le chemin HTTP passe par `_dally_record`, qui ouvre son propre curseur —
        inutilisable dans un test transactionnel, puisque son commit échapperait
        au rollback de fin de test et polluerait la base. On teste donc
        l'agrégateur sur des événements posés par l'ORM, et le chemin
        `postcommit` séparément, là où il peut l'être.
        """
        cle = cle or self.cle_a
        valeurs = [{"api_key_id": cle.id, "delta": 1} for _ in range(nombre)]
        if moment:
            for v in valeurs:
                v["used_at"] = moment
        return self.Usage.create(valeurs)

    # ------------------------------------------------------------------
    # Le modèle
    # ------------------------------------------------------------------

    def test_le_modele_ne_porte_que_trois_informations(self):
        """Ce qui n'existe pas ne peut pas fuir.

        Un journal d'usage qui accumulerait URL, IP ou en-têtes deviendrait un
        journal de navigation. Le contrat est vérifié sur les champs réels, pas
        sur une intention écrite en commentaire.
        """
        champs = set(self.Usage._fields) - set(self.env["base"]._fields)
        champs -= {"create_uid", "write_uid", "create_date", "write_date",
                   "display_name", "id"}

        self.assertEqual(champs, {"api_key_id", "used_at", "delta"})
        for interdit in ("ip", "url", "path", "header", "payload", "token",
                         "key", "partner", "session", "user_agent"):
            fuites = [f for f in self.Usage._fields if interdit in f.lower()]
            # `api_key_id` est la référence à la clé, pas la clé : c'est le seul
            # champ dont le nom contient « key », et il ne porte qu'un
            # identifiant.
            self.assertEqual(
                [f for f in fuites if f != "api_key_id"], [],
                f"champ suspect contenant « {interdit} »",
            )

    def test_supprimer_une_cle_emporte_ses_evenements(self):
        cle = self.Cle.create({"name": "Éphémère", "scopes": "services:read"})
        self._evenements(cle, 3)
        self.assertEqual(self.Usage.search_count([("api_key_id", "=", cle.id)]), 3)

        cle.unlink()

        self.assertEqual(self.Usage.search_count([("api_key_id", "=", cle.id)]), 0)

    # ------------------------------------------------------------------
    # Agrégation
    # ------------------------------------------------------------------

    def test_agregation_exacte(self):
        avant = self.cle_a.request_count
        self._evenements(self.cle_a, 7)

        traites = self.Usage._dally_aggregate()

        self.assertEqual(traites, 7)
        self.cle_a.invalidate_recordset()
        self.assertEqual(self.cle_a.request_count, avant + 7)
        self.assertEqual(self.Usage.search_count([("api_key_id", "=", self.cle_a.id)]), 0)

    def test_agregation_par_cle(self):
        """Deux clés dans le même lot ne se mélangent pas."""
        a, b = self.cle_a.request_count, self.cle_b.request_count
        self._evenements(self.cle_a, 3)
        self._evenements(self.cle_b, 5)

        self.Usage._dally_aggregate()

        self.cle_a.invalidate_recordset()
        self.cle_b.invalidate_recordset()
        self.assertEqual(self.cle_a.request_count, a + 3)
        self.assertEqual(self.cle_b.request_count, b + 5)

    def test_last_used_at_avance_et_ne_recule_jamais(self):
        """`GREATEST` et non une affectation.

        Un lot peut contenir des événements plus anciens que le `last_used_at`
        déjà enregistré — par exemple après une agrégation qui a échoué et laissé
        des événements derrière elle. Écraser ferait reculer la date, et une clé
        activement utilisée paraîtrait dormante.
        """
        from datetime import datetime, timedelta
        recent = datetime(2026, 8, 18, 12, 0, 0)
        self.cle_a.sudo().write({"last_used_at": recent})

        self._evenements(self.cle_a, 1, moment=recent - timedelta(days=3))
        self.Usage._dally_aggregate()

        self.cle_a.invalidate_recordset()
        self.assertEqual(self.cle_a.last_used_at, recent)

        self._evenements(self.cle_a, 1, moment=recent + timedelta(days=1))
        self.Usage._dally_aggregate()

        self.cle_a.invalidate_recordset()
        self.assertEqual(self.cle_a.last_used_at, recent + timedelta(days=1))

    def test_rejouer_l_agregation_ne_compte_pas_deux_fois(self):
        self._evenements(self.cle_a, 4)
        self.Usage._dally_aggregate()
        self.cle_a.invalidate_recordset()
        apres = self.cle_a.request_count

        # Deuxième passage, sans nouvel événement.
        self.assertEqual(self.Usage._dally_aggregate(), 0)

        self.cle_a.invalidate_recordset()
        self.assertEqual(self.cle_a.request_count, apres)

    def test_lot_borne_et_reste_repris(self):
        """Le lot est borné, et ce qui dépasse n'est pas perdu."""
        avant = self.cle_a.request_count
        self._evenements(self.cle_a, 5)

        self.assertEqual(self.Usage._dally_aggregate(taille_lot=2), 2)
        self.assertEqual(self.Usage.search_count([("api_key_id", "=", self.cle_a.id)]), 3)

        self.Usage._dally_aggregate(taille_lot=2)
        self.Usage._dally_aggregate(taille_lot=2)

        self.cle_a.invalidate_recordset()
        self.assertEqual(self.cle_a.request_count, avant + 5)
        self.assertEqual(self.Usage.search_count([("api_key_id", "=", self.cle_a.id)]), 0)

    def test_lot_vide(self):
        self.assertEqual(self.Usage._dally_aggregate(), 0)

    def test_seuls_les_evenements_du_lot_sont_supprimes(self):
        """La suppression porte sur des identifiants relevés, pas sur une date.

        Entre la lecture du lot et sa suppression, de nouveaux événements
        arrivent. Un `DELETE WHERE used_at <= ...` les emporterait sans les
        avoir comptés — une perte silencieuse, impossible à remarquer après
        coup.
        """
        premiers = self._evenements(self.cle_a, 2)
        self.assertEqual(self.Usage._dally_aggregate(taille_lot=2), 2)
        self.assertFalse(premiers.exists())

        tardif = self._evenements(self.cle_a, 1)
        self.assertTrue(tardif.exists())


@tagged("post_install", "-at_install", "dally_api")
class TestIsolationTelemetrie(TransactionCase):
    """Le test qui valide l'architecture : la panne de télémétrie est inoffensive.

    Il ne mesure pas un comptage, il mesure une **absence de conséquence**.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cle = cls.env["dally.api.key"].create(
            {"name": "Essai isolation", "scopes": "services:read"}
        )

    def test_register_use_n_ecrit_rien_dans_la_transaction(self):
        """Le chemin HTTP ne touche plus la ligne de la clé.

        C'est la propriété qui supprime la contention : ce qui n'est pas écrit ne
        peut pas entrer en conflit. Mesurée sur le compteur avant tout commit.
        """
        avant = self.cle.request_count

        self.cle._register_use()
        self.env.cr.flush()

        self.cle.invalidate_recordset()
        self.assertEqual(
            self.cle.request_count, avant,
            "la transaction métier ne doit plus incrémenter le compteur",
        )

    def test_register_use_enregistre_un_callback_postcommit(self):
        """Contrôle positif : sans lui, « rien n'est écrit » serait vrai de rien.

        Un `_register_use` devenu inopérant passerait le test précédent tout en
        perdant toute la télémétrie.
        """
        avant = len(self.env.cr.postcommit)

        self.cle._register_use()

        self.assertEqual(len(self.env.cr.postcommit), avant + 1)

    def test_un_rollback_annule_la_telemetrie(self):
        """Une transaction annulée ne compte aucun usage.

        `Cursor.rollback()` appelle `postcommit.clear()` : la sémantique vient du
        cœur d'Odoo, on ne la reconstruit pas. Elle vaut aussi pour chaque
        tentative d'une requête retentée — sinon une requête retentée cinq fois
        compterait cinq usages.

        Le test ouvre **son propre curseur** : `TransactionCase` interdit
        `rollback()` sur celui du test, et un `savepoint` ne prouverait rien ici
        puisqu'il ne passe pas par `Cursor.rollback()`. C'est donc la vraie
        primitive qui est exercée, sur une transaction dont ce test est seul
        propriétaire.
        """
        with self.registry.cursor() as cr:
            cr.postcommit.add(lambda: None)
            self.assertEqual(len(cr.postcommit), 1)

            cr.rollback()

            self.assertEqual(len(cr.postcommit), 0)

    def test_une_ecriture_de_telemetrie_qui_echoue_ne_leve_pas(self):
        """LE test. Si celui-ci passe, la promesse tient.

        `_dally_record` est appelé après le commit métier, depuis
        `Callbacks.run()` — qui **n'attrape aucune exception**. Une erreur qui
        s'en échapperait produirait un 500 sur une requête dont les données sont
        déjà enregistrées : le client verrait un échec, la base un succès.

        On casse donc volontairement l'écriture, et on vérifie que rien ne
        remonte.
        """
        Usage = self.env["dally.api.key.usage"]

        with patch.object(
            type(Usage), "_dally_record", side_effect=RuntimeError("base indisponible")
        ):
            # L'appel direct lève, forcément : c'est le mock.
            with self.assertRaises(RuntimeError):
                Usage._dally_record(self.cle.id, self.env.cr.dbname)

        # Et maintenant le vrai chemin, avec une base injoignable : il avale.
        try:
            Usage._dally_record(self.cle.id, "base_qui_n_existe_pas_du_tout")
        except Exception as exc:  # noqa: BLE001
            self.fail(
                f"_dally_record a laissé remonter {type(exc).__name__} : une "
                f"requête déjà commitée retournerait 500"
            )

    def test_un_registre_injoignable_ne_perturbe_pas_la_transaction(self):
        """Après l'échec de la télémétrie, la transaction métier reste utilisable.

        Une exception mal contenue laisserait le curseur en état d'erreur, et
        toute requête suivante échouerait avec un message sans rapport.
        """
        self.env["dally.api.key.usage"]._dally_record(
            self.cle.id, "base_qui_n_existe_pas_du_tout"
        )

        # Le curseur répond encore.
        self.assertTrue(self.env["dally.api.key"].search_count([]) >= 1)
