# Contrat d'API

Deux surfaces distinctes, à ne pas confondre.

| Surface | Exposition | Authentification | Consommateur |
|---|---|---|---|
| `dallytrading.com/api/*` | **publique** | aucune (formulaires publics) | le navigateur |
| `crm.dallytrading.com/api/v1/*` | **privée** | clé API | le backend Next.js |

Le navigateur ne parle **jamais** à Odoo. Il appelle son propre backend en
même origine, qui détient seul la clé API (§2, §54).

```text
Navigateur → /api/leads (Next.js) → OdooGateway → /api/v1/leads (Odoo)
```

---

## 1. La passerelle `OdooGateway`

Tout accès à Odoo passe par une interface unique
([`gateway.ts`](../apps/web/src/services/odoo/gateway.ts)), avec trois
implémentations interchangeables (ADR-008) :

| Adaptateur | État | Rôle |
|---|---|---|
| `DallyApiAdapter` | ✅ **actif** | Endpoints `/api/v1/*` du module `dally_api` |
| `Json2Adapter` | ⛔ non implémenté | API JSON-2 d'Odoo 19, à valider en phase 3 |
| `LegacyRpcAdapter` | ⛔ non implémenté | Échappatoire XML-RPC / JSON-RPC, confinée (§39) |

Le choix se fait par `ODOO_GATEWAY_ADAPTER` dans `.env`. Aucun code applicatif ne
change.

Les deux adaptateurs non implémentés **lèvent une erreur explicite** plutôt que de
contenir une implémentation plausible mais non vérifiée. Pour `Json2Adapter`, la
raison est documentée dans le fichier : la disponibilité de JSON-2 sur une
installation Odoo 19 Community auto-hébergée n'a pas été vérifiée, faute
d'instance. Écrire du code contre une API non testée produirait quelque chose qui
paraît terminé, passe la revue, et échoue en production.

### Règles imposées aux implémentations

1. Toute méthode retourne le type documenté ou lève `OdooGatewayError`. Aucune
   exception spécifique à un protocole ne doit remonter.
2. `createLead` **doit** être idempotente sur `idempotencyKey`.
3. Aucun retour ne contient d'identifiant de base de données (§42).

---

## 2. `POST /api/leads` — endpoint public

Appelé par le formulaire de devis. Même origine, pas d'authentification.

### Requête

```http
POST /api/leads
Content-Type: application/json
```

```json
{
  "requestUuid": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
  "serviceCode": "freight_sea",
  "lastName": "Ndiaye",
  "firstName": "Aliou",
  "companyName": "Ndiaye Import Export",
  "email": "aliou@example.com",
  "phone": "+221 77 123 45 67",
  "whatsapp": "+221 77 123 45 67",
  "city": "Dakar",
  "countryCode": "SN",
  "message": "Devis pour un conteneur 40 pieds depuis Le Havre.",
  "sourceUrl": "https://dallytrading.com/fret-maritime",
  "utmSource": "google",
  "utmMedium": "cpc",
  "utmCampaign": "fret-2026"
}
```

| Champ | Obligatoire | Contrainte |
|---|---|---|
| `requestUuid` | ✅ | UUID. Généré par le navigateur, **réutilisé tel quel en cas de retry** |
| `serviceCode` | ✅ | `^[a-z0-9_]+$`, max 50 |
| `lastName` | ✅ | 1–100 caractères |
| `email` ou `phone` | ✅ | au moins l'un des deux |
| `countryCode` | — | ISO 3166-1 alpha-2 |
| `message` | — | max 20 000 caractères |
| `website` | — | **honeypot** : champ masqué, ne jamais remplir |

### Réponses

**201 — créé**

```json
{
  "success": true,
  "data": { "reference": "DT-2026-000124", "serviceCode": "freight_sea", "status": "received" },
  "requestId": "e255722a-71f0-4aa2-a408-b8d12afd03c6"
}
```

**422 — validation**, avec le détail par champ pour que le formulaire surligne les
bons inputs :

```json
{
  "success": false,
  "error": {
    "code": "validation_error",
    "message": "Certains champs sont invalides.",
    "fields": {
      "serviceCode": "Veuillez sélectionner un service",
      "lastName": "Le nom est obligatoire"
    }
  },
  "requestId": "30a5014e-4584-414d-a651-d7e0792abbb4"
}
```

**429 — trop de requêtes** — deux niveaux distincts (vérifiés en test) :

| Niveau | Limite | Compte |
|---|---|---|
| Requêtes | 20 / min / IP | toutes, y compris les échecs de validation |
| Soumissions | 5 / min / IP | uniquement celles qui atteignent Odoo |

Cette séparation est délibérée : un client qui se trompe plusieurs fois dans un
formulaire multi-étapes ne doit pas être bloqué. Seule l'opération d'écriture est
étroitement limitée.

**503 — ERP indisponible.** Le message est actionnable et ne révèle rien de
technique ; le détail part dans les journaux serveur avec le `requestId`.

| Statut | Code | Signification |
|---|---|---|
| 201 | — | lead créé |
| 400 | `invalid_json` | corps illisible |
| 405 | `method_not_allowed` | méthode autre que POST |
| 413 | `payload_too_large` | > 256 Kio |
| 422 | `validation_error` | champs invalides |
| 429 | `rate_limited` | limite atteinte, voir `Retry-After` |
| 503 | `service_unavailable` | Odoo injoignable ou en erreur |
| 500 | `internal_error` | anomalie ; citer `requestId` au support |

> Un honeypot rempli reçoit un **201 d'apparence normale** avec la référence
> `DT-0000-000000`, et rien n'est écrit dans le CRM. Répondre par une erreur
> donnerait au robot le signal nécessaire pour s'adapter.

---

## 3. `POST /api/v1/leads` — endpoint Odoo privé

### Authentification

```http
POST /api/v1/leads
Content-Type: application/json
X-API-Key: <clé>
```

Propriétés de la clé :

- seul un **SHA-256** est stocké ; la clé en clair n'existe qu'une fois, à la
  génération ;
- **périmètres explicites** — `leads:write` est requis ici ;
- **restriction par IP** — `127.0.0.1` par défaut, ce qui rend une clé exfiltrée
  inutilisable depuis l'extérieur ;
- **utilisateur d'exécution dédié** — l'API n'agit jamais en superutilisateur, les
  ACL et record rules s'appliquent ;
- **expiration** optionnelle.

Périmètres disponibles : `leads:write`, `quotes:write`, `sourcing:write`,
`trading:write`, `shipments:read`, `tracking:read`, `customers:read`.

Toutes les causes d'échec d'authentification renvoient **le même** message —
clé inconnue, révoquée, expirée ou IP refusée sont indistinguables, pour ne pas
confirmer l'existence d'une clé.

### Idempotence (§41)

Deux garanties superposées :

1. `crm.lead.dally_request_uuid` porte une **contrainte UNIQUE** en base. Deux
   retries simultanés ne peuvent pas tous deux passer un test applicatif
   « existe-t-il déjà ? ».
2. `dally.api.request` conserve la réponse et la **rejoue à l'identique** sur
   `(request_uuid, endpoint)`.

Un rejeu renvoie **200** (et non 201) avec la référence d'origine, et ne consomme
pas de nouveau numéro de séquence.

Seuls les appels **réussis** sont rejoués : un échec transitoire doit pouvoir être
réessayé, sinon une erreur passagère serait mise en cache définitivement et le
client ne pourrait plus jamais soumettre.

### Génération d'une clé

1. Odoo → **DallyTrading → Configuration → API → Clés API** → Nouveau
2. Nommer d'après le consommateur (« Next.js production »), une clé par
   consommateur pour pouvoir en révoquer une sans tout casser
3. Périmètre : `leads:write`
4. `allowed_ips` : `127.0.0.1` en déploiement Plesk ; vide sur VPS avec isolation
   réseau Docker (voir [VPS-MIGRATION.md](VPS-MIGRATION.md))
5. Copier la clé **immédiatement** : elle n'est affichée qu'une fois
6. La placer dans `ODOO_API_KEY` du `.env`, jamais dans Git

Révocation : décocher **Actif**. L'effet est immédiat. Une clé possédant un
historique de requêtes ne peut pas être supprimée — un journal d'audit qui
référence une clé disparue n'est plus un journal d'audit.

### `GET /api/v1/health`

Authentifié, périmètre `customers:read`. Un endpoint de santé ouvert renseignerait
gratuitement un attaquant sur la présence d'Odoo et le nom de la base.

---

## 3 bis. `GET /api/v1/tracking/{reference}` — suivi public

Périmètre `tracking:read`. Consommé par la page `/tracking` du site.

```http
GET /api/v1/tracking/DT-SHP-2026-000124
X-API-Key: <clé>
```

**200** — la charge utile est **exhaustivement** définie par `PUBLIC_PAYLOAD_KEYS`
dans `dally_tracking` :

```json
{
  "success": true,
  "data": {
    "reference": "DT-SHP-2026-000124",
    "transportMode": "sea",
    "transportModeLabel": "Fret maritime",
    "origin": "Le Havre, France",
    "destination": "Dakar, Sénégal",
    "status": "in_transit",
    "statusLabel": "En transit",
    "departureDate": "2026-08-01",
    "estimatedArrival": "2026-08-25",
    "actualArrival": null,
    "lastUpdate": "2026-08-03T09:12:00",
    "carrierTrackingNumber": "MSCU1234567",
    "containerNumber": "MSCU7654321",
    "goodsDescription": "Pièces automobiles",
    "packagesCount": 12,
    "timeline": [
      {
        "date": "2026-08-01T14:00:00",
        "status": "departed",
        "statusLabel": "Parti",
        "location": "Le Havre",
        "description": "Marchandise chargée, navire parti."
      }
    ]
  }
}
```

**404** — référence inconnue, mal formée, archivée ou appartenant à une autre
société : **une seule et même réponse**, pour que l'endpoint ne puisse pas être
sondé.

### Ce qui ne peut structurellement pas sortir

Trois couches indépendantes, et non une seule :

| Couche | Mécanisme | Ce qu'elle empêche |
|---|---|---|
| 1 | `groups=` sur `supplier_cost`, `margin`, `internal_notes` | L'ORM ne charge jamais ces colonnes pour l'utilisateur d'API |
| 2 | Record rule sur `dally.shipment.event` | Même une recherche sans domaine ne retourne que `visible_to_customer = True` |
| 3 | Liste blanche `_dally_public_payload` | Un champ ajouté demain n'apparaît pas par accident |

`sudo()` n'est **volontairement pas utilisé** dans ce chemin : il contournerait les
couches 1 et 2 et ne laisserait que la troisième.

Une **deuxième clé et un deuxième utilisateur d'intégration** sont requis :
`user_dally_api_tracking`, membre d'aucun groupe métier DallyTrading. Réutiliser
la clé des leads fonctionnerait, mais son utilisateur porte
`group_dally_commercial`, qui implique `group_dally_readonly` — précisément le
groupe qui garde `internal_notes`.

Ne sortent jamais : identité du client, valeur déclarée, coût fournisseur, marge,
notes internes (dossier **et** événement), devis, facture, responsable, pièces
jointes, et tout identifiant de base.

### Énumération des références — compromis assumé

Les références `DT-SHP-YYYY-NNNNNN` sont séquentielles et le §44 demande une
recherche par référence seule : la série est donc parcourable. Accepté en
connaissance de cause, sur deux fondements :

- la charge utile ne contient rien de confidentiel ; le pire cas est d'apprendre
  qu'une expédition existe et vers où elle va ;
- limitation de débit à **10 recherches/min/IP** sur la page `/tracking`, plus le
  proxy.

Durcissement possible si DallyTrading le juge nécessaire : exiger un second
facteur (nom du client, ou jeton dans les liens de notification). C'est une
décision produit — elle change ce que le client doit saisir — signalée ici plutôt
qu'implémentée en silence.

> ⚠️ La limitation `limit_req` de nginx exige un `limit_req_zone` dans le bloc
> `http`, inaccessible depuis le champ « directives additionnelles » de Plesk qui
> écrit dans le bloc `server`. Elle nécessite un fichier dans
> `/etc/nginx/conf.d/`, à créer par l'administrateur. **Non appliqué à ce jour.**

---

## 4. Ce que l'API ne fait pas — et ne fera pas

- **Aucun accès générique aux modèles.** Il n'existe aucun moyen de nommer un
  modèle ou une méthode depuis l'extérieur (§40). Chaque endpoint est une
  opération métier.
- **Aucun identifiant de base exposé.** Les enregistrements sont désignés par leur
  référence métier. Un id séquentiel ne doit jamais devenir un jeton
  d'autorisation (§42).
- **Aucun champ hors liste blanche.** Les payloads sont filtrés champ par champ :
  un appelant ne peut pas positionner `user_id`, `stage_id` ou
  `expected_revenue` — vérifié par test.
- **Aucune donnée interne dans les réponses publiques.** Marges, coûts
  fournisseurs et notes internes sont filtrés côté Odoo, pas côté site (§44).

---

## 5. Endpoints à venir

| Endpoint | Phase | Périmètre |
|---|---|---|
| `GET /api/v1/services` | 6 | `customers:read` |
| `POST /api/v1/quotes` | 6 | `quotes:write` |
| `GET /api/v1/tracking/{reference}` | 7 | `tracking:read` |
| `GET /api/v1/shipments` | 7 | `shipments:read` |
| `POST /api/v1/sourcing` | 10 | `sourcing:write` |
| `POST /api/v1/trading` | 10 | `trading:write` |
| `GET /api/v1/customers/me` | 9 | `customers:read` |

Le versionnement est dans le chemin. Une évolution incompatible crée
`/api/v2/...` ; `v1` reste servi le temps que le site migre.
