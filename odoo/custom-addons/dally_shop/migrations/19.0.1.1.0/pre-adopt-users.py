# -*- coding: utf-8 -*-
"""
Adopte les utilisateurs d'intégration créés à la main, avant le chargement des
données du module.

## Le défaut que ce script répare, mesuré avant déploiement

La production porte déjà `dally_api_shop_read` et `dally_api_shop_checkout`, créés
à la main pendant la mise en service. Les données du module déclarent les mêmes
logins sous des xmlid. Sans ce script, Odoo ne reconnaît aucun lien entre les deux
et tente de **créer** deux utilisateurs supplémentaires.

Reproduit à l'identique sur la pile de développement — utilisateurs présents,
xmlid retirés, module ramené en 19.0.1.0.0 :

    ERROR odoo.registry: Failed to load registry
    CRITICAL Failed to initialize database
    You can not have two users with the same login!
    code de sortie 255

Ce n'est donc pas un doublon discret : c'est le **chargement du registre entier
qui échoue**. Un `-u dally_shop` en production aurait mis Odoo à terre.

## Comment il répare

Il crée la ligne `ir.model.data` qui manque, c'est-à-dire le lien entre le xmlid
attendu et l'utilisateur qui existe déjà. Le chargement des données trouve alors un
enregistrement connu au lieu d'un nouveau.

Combiné au `noupdate="1"` du fichier de données, cela signifie que l'utilisateur
existant n'est même pas modifié : ni ses groupes, ni son état, ni rien. Ses clés
d'API — qui pointent sur son `id` — restent valides, ce qui est la propriété la
plus importante ici : les rompre couperait la boutique.

## Ce qu'il ne fait jamais

* écraser un xmlid qui existe déjà, même s'il désigne un autre utilisateur ;
* créer un utilisateur — c'est le travail des données du module ;
* toucher un mot de passe ou une clé d'API.

## Pourquoi un script `pre-`

Odoo exécute les scripts `pre-` **avant** de charger les données du module. C'est
la seule fenêtre où le lien peut être posé à temps ; un `post-` arriverait après
l'échec.
"""

import logging

_logger = logging.getLogger(__name__)

#: Les identités attendues : xmlid → login.
#:
#: Dupliqué depuis `data/dally_shop_integration_users.xml` faute de mieux : un
#: script de migration s'exécute avant que le module ne soit chargé, et ne peut pas
#: lire ses propres données. Un test vérifie que les deux listes concordent, pour
#: qu'un ajout d'identité ne laisse pas ce script en arrière.
IDENTITES = (
    ("user_dally_shop_read", "dally_api_shop_read"),
    ("user_dally_shop_checkout", "dally_api_shop_checkout"),
)

MODULE = "dally_shop"


def migrate(cr, version):
    """Pose les liens manquants. Idempotent : rejouable sans effet."""
    for nom_xmlid, login in IDENTITES:
        cr.execute(
            "SELECT res_id FROM ir_model_data "
            "WHERE module = %s AND name = %s AND model = 'res.users'",
            (MODULE, nom_xmlid),
        )
        deja = cr.fetchone()
        if deja:
            _logger.info(
                "Boutique : %s.%s pointe deja sur l'utilisateur %s, inchange.",
                MODULE, nom_xmlid, deja[0],
            )
            continue

        # `active_test` n'existe pas en SQL : on cherche sans filtre, parce qu'un
        # compte désactivé porte quand même son login et provoquerait la même
        # collision.
        cr.execute("SELECT id FROM res_users WHERE login = %s", (login,))
        existant = cr.fetchone()
        if not existant:
            _logger.info(
                "Boutique : aucun utilisateur « %s » a adopter ; les donnees du "
                "module le creeront.", login,
            )
            continue

        cr.execute(
            "INSERT INTO ir_model_data (module, name, model, res_id, noupdate) "
            "VALUES (%s, %s, 'res.users', %s, TRUE)",
            (MODULE, nom_xmlid, existant[0]),
        )
        _logger.info(
            "Boutique : utilisateur « %s » (id=%s) adopte sous %s.%s. Ses groupes, "
            "son etat et ses cles d'API restent intacts.",
            login, existant[0], MODULE, nom_xmlid,
        )
