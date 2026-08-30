# -*- coding: utf-8 -*-
"""Le vocabulaire de la caisse de terrain, défini une seule fois.

## Pourquoi ce fichier plutôt qu'une constante par service

Les dépenses ont ouvert la liste des modes de paiement ; les transferts la
reprennent à l'identique. Deux copies divergeraient au premier ajout — un
écran offrirait « chèque » et l'autre le refuserait, et c'est l'opérateur qui
découvrirait l'écart, au comptoir.

## Pourquoi ces modes et pas les canaux d'encaissement

`dally.freight.payment.channel` porte un journal comptable et une ligne de
méthode : il sert à encaisser un client, ce qui produit une écriture. Une
dépense de terrain et une remise de caisse n'en produisent aucune — elles
disent seulement par quel moyen l'argent a bougé. Réutiliser les canaux
attacherait un journal à des mouvements qui n'en ont pas.

## Pourquoi cette liste de devises

Mesuré sur la base de production : les mouvements de caisse — dix dépenses et
un transfert — sont **tous en francs CFA**. L'euro est actif et sert déjà à la
tarification du fret ainsi qu'à l'écran des dépenses. Le dollar est actif lui
aussi, mais **aucun mouvement de caisse ne l'a jamais porté** : l'offrir
inviterait une devise que la caisse n'a jamais détenue.

La liste est donc courte et explicite, et se recoupe à l'exécution avec ce que
la base a réellement d'actif — une devise désactivée ne doit pas être proposée
sous prétexte qu'elle figure ici.
"""

#: Par quel moyen l'argent a bougé. Jamais un journal comptable.
MODES_PAIEMENT = ("cash", "wave", "bank", "other")

#: Ce que l'opérateur lit à la place du code.
LIBELLES_MODE = {
    "cash": "Espèces",
    "wave": "Wave",
    "bank": "Virement",
    "other": "Autre",
}

#: Les devises que la caisse de terrain détient réellement.
DEVISES_CAISSE = ("XOF", "EUR")
