# -*- coding: utf-8 -*-
"""
Les événements d'usage des clés d'API, et leur agrégation.

## Le problème que ce modèle résout

`request_count` était incrémenté par un `UPDATE` de la ligne de la clé, à chaque
requête, **dans la transaction métier**. Mesuré en production : dix requêtes
image simultanées produisaient **cinq `SerializationFailure`** — Odoo impose
`REPEATABLE READ`, et deux transactions qui écrivent la même ligne ne
s'attendent pas, elles échouent.

Aucune requête n'échouait pour autant, parce qu'Odoo retente jusqu'à cinq fois.
Mais une retentative rejoue **tout le gestionnaire** : ré-authentification,
résolution du produit, calcul du prix, décodage de l'image. La moitié des
requêtes faisait donc le travail deux fois — pour tenir à jour un compteur qui
n'est affiché que dans deux vues du back-office.

## Pourquoi des événements plutôt qu'un compteur

Deux `INSERT` de lignes différentes ne se conflictent jamais. Le chemin chaud
n'écrit donc plus jamais la ligne partagée ; il ajoute une ligne à lui. Le
compteur, lui, est recalculé hors ligne par un cron, là où la contention n'a
plus d'importance parce qu'un seul agrégateur travaille à la fois.

## Ce que ce modèle ne contient pas

Ni clé, ni jeton, ni charge utile, ni adresse IP, ni URL, ni en-tête, ni
partenaire, ni session. Trois colonnes : quelle clé, quand, combien. Un journal
d'usage qui accumulerait des URL deviendrait un journal de navigation, avec les
obligations qui vont avec — et `dally.api.request` existe déjà pour ce qui doit
être tracé finement.
"""

import logging

import odoo
from odoo import SUPERUSER_ID, api, fields, models

_logger = logging.getLogger(__name__)

#: Clé du verrou consultatif PostgreSQL de l'agrégateur.
#:
#: Valeur arbitraire mais **stable** : deux processus doivent demander le même
#: entier pour se voir. Choisie hors des plages qu'Odoo utilise lui-même pour
#: ses propres verrous consultatifs (crons, mise à jour de base).
VERROU_AGREGATION = 0x0DA11_5A01

#: Nombre d'événements traités par passage.
#:
#: Borné pour que la transaction d'agrégation reste courte : elle verrouille les
#: lignes de `dally.api.key` qu'elle met à jour, et une transaction longue
#: rendrait à l'agrégateur le défaut qu'on vient de retirer au chemin HTTP.
TAILLE_LOT = 5000


class DallyApiKeyUsage(models.Model):
    _name = "dally.api.key.usage"
    _description = "DallyTrading API Key Usage Event"
    # Croissant : l'agrégateur prend toujours les plus anciens d'abord, ce qui
    # rend le lot déterministe et le traitement équitable entre les clés.
    _order = "id"

    api_key_id = fields.Many2one(
        comodel_name="dally.api.key",
        string="API Key",
        required=True,
        # Indexé pour la clé étrangère : sans lui, supprimer une clé impose à
        # PostgreSQL un balayage complet de la table d'événements pour trouver
        # les lignes à emporter en cascade.
        index=True,
        # Supprimer une clé emporte ses événements. `restrict` obligerait à
        # vider le journal d'usage avant de retirer une clé compromise, ce qui
        # est exactement le moment où l'on ne veut pas d'obstacle.
        ondelete="cascade",
    )
    used_at = fields.Datetime(
        string="Used At",
        required=True,
        default=fields.Datetime.now,
        # Pas d'index, et c'est une décision mesurée. `EXPLAIN` sur la requête
        # de l'agrégateur — `ORDER BY id LIMIT n` — ne le regarde pas : le tri
        # se fait sur la clé primaire, et la suppression porte sur des `id`.
        # Aucune requête n'interroge `used_at`. L'indexer coûterait une écriture
        # d'index à chaque événement, c'est-à-dire sur le chemin même que ce
        # modèle existe pour alléger.
    )
    delta = fields.Integer(
        string="Requests",
        default=1,
        required=True,
        help="Nombre de requêtes représentées par cet événement. Vaut 1 "
             "aujourd'hui ; le champ existe pour qu'un regroupement en mémoire "
             "puisse plus tard poser un seul événement pour N requêtes sans "
             "changer le schéma ni l'agrégateur.",
    )

    # ------------------------------------------------------------------
    # Enregistrement
    # ------------------------------------------------------------------

    @api.model
    def _dally_record(self, api_key_id, dbname, used_at=None):
        """Écrit un événement dans une transaction **séparée**, sans jamais lever.

        Appelé depuis un callback `postcommit`, donc après que la transaction
        métier a été validée. Trois propriétés du cœur d'Odoo 19, vérifiées dans
        le source et non supposées, dictent cette forme :

        * `Cursor.commit()` exécute `postcommit.run()` **après** `_cnx.commit()`
          (`odoo/sql_db.py`) : le métier est déjà durable quand on arrive ici ;
        * `Cursor._close()` appelle `rollback()` : tout ce qu'on écrirait sur le
          curseur de la requête après son commit serait **perdu**. D'où un
          curseur à nous, validé tout de suite ;
        * `Callbacks.run()` **n'attrape aucune exception**, et `retrying()`
          appelle `commit()` **hors** de sa boucle de retentative
          (`odoo/service/model.py`). Une exception ici ne pourrait donc ni
          annuler ni rejouer le métier — mais elle produirait un **500** sur une
          requête déjà commitée. Le `except` qui suit n'est pas de la prudence
          décorative : c'est lui qui tient la promesse « la télémétrie ne casse
          jamais une requête ».
        """
        try:
            registre = odoo.modules.registry.Registry(dbname)
            with registre.cursor() as cr:
                cr.execute(
                    """
                    INSERT INTO dally_api_key_usage
                        (api_key_id, used_at, delta, create_uid, write_uid,
                         create_date, write_date)
                    VALUES (%s, %s, 1, %s, %s, now() AT TIME ZONE 'UTC',
                            now() AT TIME ZONE 'UTC')
                    """,
                    (api_key_id, used_at or fields.Datetime.now(),
                     SUPERUSER_ID, SUPERUSER_ID),
                )
        except Exception:  # noqa: BLE001
            # Volontairement muet au niveau `debug` : ce chemin s'emprunte à
            # chaque requête, et une base momentanément indisponible remplirait
            # les journaux d'un bruit qui n'apprend rien de plus que
            # l'indisponibilité elle-même, déjà signalée ailleurs.
            _logger.debug(
                "Telemetrie d'usage non enregistree pour la cle %s.",
                api_key_id, exc_info=True,
            )

    # ------------------------------------------------------------------
    # Agrégation
    # ------------------------------------------------------------------

    @api.model
    def _dally_aggregate(self, taille_lot=TAILLE_LOT):
        """Replie les événements dans les compteurs de la clé, en une transaction.

        ## Un seul agrégateur à la fois

        `pg_try_advisory_xact_lock` plutôt qu'un drapeau en base ou un
        `SELECT ... FOR UPDATE` :

        * **non bloquant** — un second passage rend `False` immédiatement et
          sort proprement, au lieu d'attendre derrière le premier et de faire
          traîner un worker de cron ;
        * **porté par la transaction** — il est relâché au `COMMIT` comme au
          `ROLLBACK`, et *aussi* si le processus meurt. Un drapeau en base
          resterait levé après un `kill -9` et bloquerait l'agrégation jusqu'à
          une intervention manuelle ;
        * **sans table** — rien à créer, rien à purger, rien à migrer.

        ## Pourquoi tout tient dans une transaction

        Lire le lot, additionner, mettre à jour les clés et supprimer **ces**
        événements-là forment une seule opération indivisible. Un échec ramène
        les événements : ils seront repris au passage suivant. C'est ce qui rend
        le double comptage impossible — un événement n'est supprimé que dans la
        transaction qui l'a compté.

        La suppression porte sur des identifiants **explicitement relevés**, pas
        sur un critère de date : entre la lecture et la suppression, de nouveaux
        événements arrivent en continu, et un `DELETE WHERE used_at <= ...`
        emporterait des lignes jamais comptées.
        """
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s)", (VERROU_AGREGATION,)
        )
        if not self.env.cr.fetchone()[0]:
            _logger.info(
                "Agregation de la telemetrie deja en cours ailleurs : passage ignore."
            )
            return 0

        self.env.cr.execute(
            """
            SELECT id, api_key_id, delta, used_at
              FROM dally_api_key_usage
             ORDER BY id
             LIMIT %s
            """,
            (taille_lot,),
        )
        evenements = self.env.cr.fetchall()
        if not evenements:
            return 0

        cumuls = {}
        ids = []
        for identifiant, cle, delta, moment in evenements:
            ids.append(identifiant)
            total, dernier = cumuls.get(cle, (0, None))
            cumuls[cle] = (
                total + (delta or 0),
                moment if dernier is None or moment > dernier else dernier,
            )

        for cle, (total, dernier) in cumuls.items():
            # SQL direct plutôt que l'ORM : `request_count = request_count + N`
            # se lit et s'écrit en une seule instruction, sans relire la valeur
            # dans une variable Python. Passer par l'ORM ferait un SELECT puis un
            # UPDATE, et rouvrirait — dans l'agrégateur cette fois — la fenêtre
            # de perte que tout ce modèle existe pour fermer.
            self.env.cr.execute(
                """
                UPDATE dally_api_key
                   SET request_count = COALESCE(request_count, 0) + %s,
                       last_used_at  = GREATEST(
                           COALESCE(last_used_at, %s), %s
                       )
                 WHERE id = %s
                """,
                (total, dernier, dernier, cle),
            )

        self.env.cr.execute(
            "DELETE FROM dally_api_key_usage WHERE id IN %s", (tuple(ids),)
        )
        # Le cache de l'ORM ignore ces écritures faites en SQL : sans
        # invalidation, une lecture ultérieure dans la même transaction rendrait
        # l'ancien compteur.
        self.env.invalidate_all()

        _logger.info(
            "Telemetrie agregee : %s evenement(s) sur %s cle(s).",
            len(ids), len(cumuls),
        )
        return len(ids)
