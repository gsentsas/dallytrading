# Photos Ops dans le CRM

Cette évolution expose en lecture seule les preuves photographiques Ops depuis
le formulaire `dally.shipment` du CRM.

Garanties :

- la photo originale reste l'unique `ir.attachment` ;
- la pièce jointe reste privée (`public = False`) ;
- aucun document portail n'est créé ;
- seuls les rôles internes DallyTrading disposant de `group_dally_readonly`
  peuvent lire `dally.ops.photo` ;
- une règle multi-société limite la lecture aux sociétés autorisées ;
- les photos retirées (`active = False`) restent conservées pour l'audit
  système, mais elles ne sont ni affichées ni recherchables par un lecteur CRM
  ordinaire, même avec `active_test=False`.
