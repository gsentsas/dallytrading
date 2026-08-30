# -*- coding: utf-8 -*-
"""Comment Dally Ops écrit un montant et un poids.

## Une seule règle, partagée

Le reçu client et le journal opérationnel affichent les mêmes grandeurs. Deux
formateurs finiraient par diverger sur un arrondi ou un séparateur, et le jour
où cela arrive, c'est un document déjà remis au client qui contredit l'écran de
l'opérateur.

Ces fonctions ont été écrites pour le reçu (étape 16) ; le journal les
réutilise plutôt que d'en réécrire une variante. Elles sont volontairement
sans dépendance à l'ORM : ce sont des règles d'écriture, pas des services.
"""

#: Le franc CFA ne se divise pas : écrire « 100 000,00 FCFA » annoncerait une
#: précision que la monnaie n'a pas. L'euro garde ses centimes — un reçu de
#: 67 € pour 67,50 € dus serait une erreur de caisse. Même règle que l'écran
#: (`features/depenses/format.ts`).
DECIMALES = {"XOF": 0}

SYMBOLES = {"EUR": "€", "XOF": "FCFA"}


def montant(valeur, devise):
    """Un montant tel qu'il se lit à l'écran comme au papier.

    Le séparateur de milliers est une espace, comme en français. `None` reste
    vide : un montant absent ne devient jamais zéro.
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
    """Un poids tel qu'il se lit — « 13,5 kg ».

    Écrit ici pour la même raison que les montants : le papier affichait
    « 13.5 kg » quand l'écran affichait « 13,5 kg ». Personne n'aurait relu le
    reçu du client pour vérifier un point décimal.
    """
    entier, _, fraction = ("%.3f" % (valeur or 0.0)).partition(".")
    fraction = fraction.rstrip("0")
    return "%s,%s kg" % (entier, fraction) if fraction else "%s kg" % entier


def nombre(valeur):
    """Un nombre décimal en écriture française, sans unité."""
    texte = ("%.3f" % float(valeur or 0)).rstrip("0").rstrip(".")
    return texte.replace(".", ",")
