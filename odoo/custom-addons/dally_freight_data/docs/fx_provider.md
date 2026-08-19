# Taux de change : ce qui manque avant toute tarification multidevise

Note technique. **Rien n'a été activé ni modifié** : ce document consigne un
chantier, il n'en ouvre pas.

## L'état mesuré en production

| Devise | Active | Taux enregistrés |
|---|---|---|
| XOF (devise de la société) | oui | 0 |
| USD | oui | 0 |
| EUR | non | 0 |
| CNY | non | 0 |
| AED | non | 0 |
| GBP | non | 0 |

Les six existent dans `res.currency`. Aucune ne porte le moindre
`res.currency.rate`.

## Pourquoi l'activation attend

Une devise active sans taux n'échoue pas : Odoo convertit au taux **1,0** et ne
signale rien. Un devis saisi en euros sortirait avec son montant lu en francs
CFA — un facteur 655 sur une facture, sans message d'erreur, sans ligne de
journal. C'est un mode de défaillance silencieux, et c'est la raison pour
laquelle activer EUR, CNY, AED ou GBP aujourd'hui serait plus dangereux que de
les laisser inactives : tant qu'elles le sont, personne ne peut les choisir par
mégarde dans un formulaire.

USD est déjà active et sans taux. Ce cycle n'y touche pas — le corriger suppose
de décider d'abord ce qui suit.

## Les décisions à prendre, dans l'ordre

1. **La source.** Odoo sait interroger plusieurs fournisseurs de taux depuis
   `res.company` (paramètre `currency_provider`), avec une cadence
   quotidienne. La BCEAO fixe la parité XOF/EUR ; les autres paires demandent
   un fournisseur. Le choix est autant contractuel que technique.
2. **La cadence et le fuseau.** Un taux quotidien récupéré à 6 h UTC n'est pas
   le taux du moment où la facture est émise. Il faut décider si l'écart est
   acceptable, et sinon à quelle date de référence les pièces sont converties.
3. **La date de conversion.** Devis, commande, facture et règlement peuvent
   tomber sur quatre taux différents. `dally.trade.opportunity` porte déjà
   `conversion_date` et `conversion_rate_source` : la règle du négoce existe,
   celle du fret n'a pas encore été écrite.
4. **L'écart de change.** Dès qu'une pièce se règle à un taux différent de son
   émission, la différence doit atterrir quelque part. C'est une décision
   comptable, pas un paramètre.

## Ce que ce chantier n'est pas

Il n'est pas un préalable au référentiel de fret : ports, compagnies et
itinéraires ne portent aucun montant. Il devient bloquant au moment exact où
une grille tarifaire multidevise apparaît — et il devra être terminé **avant**,
pas pendant.
