# Portail client et tracking

L'espace client est une frontière d'autorisation, pas une simple collection de pages privées.

## Architecture d'authentification

```text
Navigateur
   │ cookie dt_portal_session
   ▼
Next.js BFF
   │ session Odoo transportée côté serveur
   ▼
/api/v1/portal/*
   │
   ▼
ACL → record rules → groups= → projection publique
```

Le cookie ne contient pas de `partner_id`, de groupe ou de droit métier à utiliser comme autorisation.

## Règle principale

> La présence du cookie ne prouve pas l'autorisation.

Chaque accès privé doit laisser Odoo vérifier la session réelle et appliquer ses droits.

## Deux passerelles distinctes

| Passerelle | Identité | Usage |
|---|---|---|
| `DallyApiAdapter` | utilisateur d'intégration | formulaires et APIs serveur-à-serveur |
| `PortalOdooGateway` | client connecté | espace client |

Le portail n'a pas de repli vers une clé de service.

## Cookie portail

Le cookie de session DallyTrading est :

- `HttpOnly` ;
- `Secure` en production ;
- `SameSite=Lax` ;
- scellé/chiffré côté serveur.

`PORTAL_SESSION_SECRET` reste uniquement côté serveur.

Une rotation de cette valeur invalide toutes les sessions DallyTrading ouvertes.

## Contenu du portail

Le portail expose uniquement les projections autorisées pour le client connecté, par exemple :

- devis ;
- sourcing ;
- trading ;
- expéditions ;
- événements publiés ;
- documents autorisés ;
- commandes boutique ;
- profil selon les capacités déployées.

## Tracking public

Le suivi public repose sur une référence ou un jeton DallyTrading prévu pour cet usage. Il ne doit pas exposer une référence séquentielle interne d'un module tiers.

La timeline publique doit rester limitée à :

- statut client ;
- date/heure pertinente ;
- lieu public si applicable ;
- message explicitement publiable.

## Confidentialité

Ne jamais exposer dans les DTO portail :

- coûts ;
- marges ;
- commissions ;
- notes internes ;
- identifiants ORM inutiles ;
- références techniques d'intégration ;
- données d'autres sociétés ou clients.

## État fonctionnel

Le portail en lecture est la base stable. Toute nouvelle mutation client doit passer par :

1. méthode métier dédiée ;
2. validation Odoo ;
3. tests d'isolation multi-client ;
4. protection CSRF/origine selon le canal ;
5. projection minimale.

## Références

- [Portail — frontière d'authentification](https://github.com/gsentsas/dallytrading/blob/main/docs/PORTAL.md)
- [API](https://github.com/gsentsas/dallytrading/blob/main/docs/API.md)
