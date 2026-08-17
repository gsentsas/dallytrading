# -*- coding: utf-8 -*-
"""
Amorçage de la boutique, à l'installation et à chaque montée de version.

## Ce que fait ce hook, et ce qu'il refuse de faire

Il **complète** une configuration absente. Il ne corrige jamais une configuration
existante : le tarif, ses règles et la publication des produits sont des décisions
commerciales, et un hook qui les réécrirait à chaque déploiement les rendrait
impossibles à tenir.

D'où la règle unique de ce fichier : **écrire seulement ce qui est vide.**

## Ce qu'il ne fait jamais

* **sélectionner le tarif de la boutique** — même celui qu'il vient de créer.
  Sélectionner, c'est ouvrir la tarification, et un déploiement technique ne prend
  pas cette décision ;
* publier un produit — la vitrine reste fermée jusqu'à décision explicite ;
* créer une règle de prix — un montant inventé est pire qu'un montant absent ;
* créer une clé d'API — elle porte un secret, qui n'a rien à faire dans du code.

## L'ordre d'ouverture, quand le propriétaire le décidera

1. créer une règle de prix explicite ;
2. vérifier le prix calculé par Odoo ;
3. sélectionner « Boutique DallyTrading » dans les réglages ;
4. publier un produit pilote.

Dans cet ordre. Sélectionner avant d'avoir une règle ouvrirait une boutique dont
aucun produit n'est vendable ; publier avant de vérifier le prix exposerait un
montant que personne n'a relu.
"""

import logging

_logger = logging.getLogger(__name__)

#: Clé de configuration portant le tarif de la boutique.
#:
#: Dupliquée depuis `models/product_template.py` plutôt qu'importée : un hook
#: s'exécute avant que le registre ne soit complètement prêt, et une importation
#: croisée à ce moment est une source d'ennuis pour une constante de six mots.
CLE_TARIF = "dally_shop.pricelist_id"


def post_init_hook(env):
    """Amorce le tarif boutique sans jamais écraser une décision existante."""
    activer_devise_xof(env)
    regler_devise_du_tarif(env)
    _constater_selection(env)
    _verifier_aucune_publication(env)


def _tarif(env):
    """Le tarif créé par les données du module, ou un ensemble vide."""
    return env.ref("dally_shop.pricelist_dally_shop", raise_if_not_found=False)


def activer_devise_xof(env):
    """Active XOF si elle ne l'est pas.

    La **devise du tarif** est fixée par les données du module — `ref('base.XOF')`
    — et non ici : les données s'appliquent aussi aux montées de version, alors
    qu'un hook d'installation ne rejoue pas. Un premier essai réglait la devise
    dans ce hook, et le tarif ressortait en USD sur une base déjà installée.

    Reste ici la seule chose qu'une donnée ne doit pas faire : basculer l'`active`
    d'un enregistrement de `base`. Une devise inactive n'apparaît nulle part dans
    l'interface, et un tarif qui la porte serait impossible à lire pour le
    propriétaire.

    Appelée aussi par le script de migration, pour que le cas « déjà installé »
    soit couvert.
    """
    xof = env.ref("base.XOF", raise_if_not_found=False)
    if not xof:
        # Ne devrait pas arriver : `base` livre toutes les devises. On le note
        # plutôt que de lever — la boutique reste utilisable dans une autre devise.
        _logger.warning("Boutique : devise XOF introuvable sur cette base.")
        return
    if not xof.active:
        xof.active = True
        _logger.info("Boutique : devise XOF activee.")
    return xof


def regler_devise_du_tarif(env):
    """Met le tarif boutique en XOF, **uniquement s'il est encore vierge**.

    ## Pourquoi ce détour est nécessaire

    Les données du module portent `ref('base.XOF')`, mais elles sont en
    `noupdate="1"` : sur une base où le tarif existe déjà, Odoo ne réécrit aucun
    champ. Mesuré — après montée de version, le tarif restait en USD alors que la
    donnée demandait XOF. Le `noupdate` fait exactement son travail, et c'est ce
    travail qui bloque la correction.

    ## Pourquoi la condition est étroite

    « Vierge » veut dire : aucune règle de prix. Dès qu'une règle existe, le
    propriétaire a décidé de quelque chose, et changer la devise sous une règle de
    prix fixe changerait le prix — c'est exactement ce qu'on ne fait jamais. Dans
    ce cas on se contente de le signaler.
    """
    tarif = _tarif(env)
    xof = env.ref("base.XOF", raise_if_not_found=False)
    if not tarif or not xof or tarif.currency_id == xof:
        return
    if tarif.item_ids:
        _logger.warning(
            "Boutique : le tarif « %s » est en %s et porte %s regle(s) de prix. "
            "La devise n'est PAS modifiee — changer la devise sous une regle "
            "changerait les prix. A corriger a la main si necessaire.",
            tarif.display_name, tarif.currency_id.name, len(tarif.item_ids),
        )
        return
    ancienne = tarif.currency_id.name
    tarif.currency_id = xof
    _logger.info(
        "Boutique : tarif « %s » passe de %s a XOF (aucune regle, donc aucun prix "
        "modifie).", tarif.display_name, ancienne,
    )


def _constater_selection(env):
    """Constate l'état de la sélection du tarif. **N'en choisit jamais un.**

    ## Pourquoi le code ne sélectionne pas, même le tarif qu'il vient de créer

    Sélectionner un tarif, c'est ouvrir la tarification : à partir de cet instant
    le catalogue cesse de répondre « boutique en préparation » et se met à servir
    des prix. C'est une décision commerciale, et un déploiement technique ne doit
    pas la prendre — surtout pas en silence, et surtout pas au premier `-u`.

    Une version précédente sélectionnait automatiquement le tarif créé par le
    module. C'était commode et faux : la boutique se serait ouverte d'elle-même au
    déploiement, avec un tarif sans règle, donc avec des produits invendables et un
    écran qui ne dirait plus la vérité sur son état.

    Le code crée donc l'outil et laisse la décision. Ce qu'il fait ici est
    uniquement écrire dans le journal ce qui manque encore.

    Une sélection existante n'est jamais touchée non plus : quelqu'un l'a faite.
    """
    parametre = env["ir.config_parameter"].sudo()
    actuel = (parametre.get_param(CLE_TARIF) or "").strip()
    tarif = _tarif(env)

    if actuel:
        _logger.info(
            "Boutique : un tarif est deja selectionne (%s=%s). Inchange.",
            CLE_TARIF, actuel,
        )
        return

    _logger.info(
        "Boutique : AUCUN tarif selectionne — la boutique reste fermee, et c'est "
        "l'etat attendu. Le tarif « %s » existe et ne porte aucune regle de prix. "
        "Pour ouvrir, dans l'ordre : (1) creer une regle de prix explicite, "
        "(2) verifier le prix calcule par Odoo, (3) selectionner ce tarif dans "
        "%s, (4) publier un produit pilote.",
        tarif.display_name if tarif else "(introuvable)", CLE_TARIF,
    )


def _verifier_aucune_publication(env):
    """Trace le nombre de produits publiés, et alerte si l'installation en a créé.

    Un contrôle plutôt qu'une action : si ce compteur n'est pas nul sur une base
    neuve, quelque chose publie des produits tout seul, et il faut le voir tout de
    suite. Sur une base existante, le nombre est celui qu'il était.
    """
    publies = env["product.template"].sudo().search_count(
        [("dally_published", "=", True)]
    )
    if publies:
        _logger.warning(
            "Boutique : %s produit(s) publie(s) apres installation. La publication "
            "est censee rester une decision explicite du proprietaire.", publies,
        )
    else:
        _logger.info("Boutique : aucun produit publie, vitrine fermee.")
