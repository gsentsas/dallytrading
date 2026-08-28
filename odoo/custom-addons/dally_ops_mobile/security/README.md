# Droits d'accès de Dally Ops

Une seule ligne, et elle demande une explication.

## `res.currency`, en lecture seule

Dally Ops deliberately grants read-only access to `res.currency` because Odoo
flushes all environments at savepoint boundaries while monetary fields may need
currency rounding/conversion.

This is a technical reference-model exception. It does not grant access to any
DallyTrading business model.

Concrètement : enregistrer une réception écrit des montants. À la sortie d'un
point de sauvegarde, Odoo vide **tous** les environnements de la transaction —
y compris celui de l'opérateur — et convertir un champ monétaire y appelle
`currency.round()`, donc une lecture de `res.currency`. Sans ce droit, la route
`/api/v1/ops/intakes` échoue en HTTP alors que le même service réussit en
shell, où un environnement superutilisateur vide en premier et masque le
problème.

## L'invariant, tel qu'il se lit maintenant

Zéro modèle **métier** accessible directement, avec une liste blanche technique
explicite qui contient exactement `res.currency`, en lecture. Les tests de
dérive comparent l'ensemble des modèles lisibles à cette liste par égalité :
un second modèle qui deviendrait lisible les fait tomber immédiatement.

`res.currency.rate` n'est **pas** ouvert : les taux sont une donnée
commerciale, l'arrondi ne l'est pas.
