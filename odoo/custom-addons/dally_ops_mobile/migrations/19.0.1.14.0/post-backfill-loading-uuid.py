# -*- coding: utf-8 -*-
"""Attribue une identité de chargement aux colis déjà en base.

## Pourquoi en SQL et non par l'ORM

Un `write()` de l'ORM touche `write_date`. Or `write_date` d'un colis est une
donnée d'exploitation : elle dit quand la marchandise a été corrigée pour la
dernière fois, et les contrôles de non-régression des étapes précédentes s'y
appuient pour prouver qu'une consultation n'a rien modifié.

Poser une identité technique n'est pas une correction métier. Cette migration
écrit donc la seule colonne concernée, en laissant `write_date`, `write_uid`
et tous les champs métier exactement où ils étaient.

## Ce qu'elle garantit

Un UUID par colis, tiré par PostgreSQL, sans collision — la contrainte
d'unicité du modèle refuserait le contraire. Les colis créés après la mise à
jour reçoivent le leur à la création ; celle-ci ne concerne que l'existant, et
ne repasse jamais sur un colis déjà pourvu.
"""


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT count(*) FROM dally_shipment_package
         WHERE ops_loading_uuid IS NULL
    """)
    manquants = cr.fetchone()[0]
    if not manquants:
        return

    # `gen_random_uuid()` est fourni par pgcrypto, présent en standard depuis
    # PostgreSQL 13. Le repli Python reste possible si l'extension manque.
    cr.execute("SELECT 1 FROM pg_proc WHERE proname = 'gen_random_uuid' LIMIT 1")
    if cr.fetchone():
        cr.execute("""
            UPDATE dally_shipment_package
               SET ops_loading_uuid = gen_random_uuid()::text
             WHERE ops_loading_uuid IS NULL
        """)
    else:
        import uuid
        cr.execute("SELECT id FROM dally_shipment_package WHERE ops_loading_uuid IS NULL")
        for (package_id,) in cr.fetchall():
            cr.execute(
                "UPDATE dally_shipment_package SET ops_loading_uuid = %s WHERE id = %s",
                [str(uuid.uuid4()), package_id],
            )
