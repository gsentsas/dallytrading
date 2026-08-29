# -*- coding: utf-8 -*-
"""L'invariant de sécurité de Dally Ops, défini une seule fois.

## Ce qu'il dit exactement

Zéro modèle **métier** accessible directement. Une liste blanche technique,
explicite, qui contient aujourd'hui `res.currency` et rien d'autre.

## Pourquoi une égalité et non une appartenance

Écrire `"res.currency" in lisibles` laisserait passer le deuxième modèle, puis
le troisième. La comparaison porte donc sur l'ensemble entier : le jour où une
ACL de plus est ajoutée, tous les tests qui s'appuient sur ce module tombent,
et quelqu'un doit décider de l'élargissement au lieu de le subir.

## Pourquoi `res.currency` y figure

Enregistrer une réception écrit des montants. À la sortie d'un point de
sauvegarde, Odoo vide tous les environnements de la transaction — celui de
l'opérateur compris — et convertir un champ monétaire y appelle
`currency.round()`. Voir `security/README.md`.
"""

#: Les modèles que le compte Ops peut lire directement. Techniques, jamais
#: métier. Toute addition ici est une décision, pas un détail.
MODELES_TECHNIQUES_LISIBLES = frozenset({"res.currency"})

#: Des modèles métier nommément vérifiés fermés. La liste blanche ci-dessus
#: suffit en théorie ; ceux-ci disent à la lecture ce qui est en jeu.
MODELES_METIER_FERMES = (
    "res.partner",
    "dally.shipment",
    "dally.shipment.package",
    "dally.freight.consolidation",
    "dally.freight.tariff.rule",
    "account.move",
    "account.payment",
    "res.currency.rate",
    "res.company",
    "ir.model",
    "ir.attachment",
    "calendar.event",
    "calendar.attendee",
    "dally.ops.appointment.request",
)


def modeles_lisibles(env, utilisateur):
    """Les modèles que cet utilisateur peut lire, en interrogeant le registre.

    On énumère plutôt que de relire le fichier d'ACL : c'est le comportement
    effectif qui compte, y compris ce qu'un groupe impliqué apporterait sans
    qu'aucune ligne de ce module ne le mentionne.
    """
    lisibles = set()
    for nom in env.registry:
        modele = env[nom]
        if modele._abstract or modele._transient:
            continue
        try:
            if modele.with_user(utilisateur).has_access("read"):
                lisibles.add(nom)
        except Exception:  # pragma: no cover - modèle non instanciable
            continue
    return lisibles
