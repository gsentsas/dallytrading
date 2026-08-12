/**
 * Service catalogue used by the quote form.
 *
 * ## Why this is duplicated here, and when it stops being
 *
 * The authoritative catalogue lives in Odoo (`dally.service.type`, seeded by
 * `dally_core`). There is no `/api/v1/services` endpoint yet — it is phase 6 work
 * — so the form carries its own copy for now.
 *
 * That is a deliberate, bounded duplication rather than an oversight:
 *
 * * the **codes** are contractual and stable; Odoo validates every incoming code
 *   and rejects an unknown one, so a divergence fails loudly at submission rather
 *   than silently creating a mislabelled lead;
 * * only the labels and the two "does this service need a route / cargo details"
 *   flags are copied — never pricing or business rules;
 * * when the endpoint exists, `listServiceTypes()` on the gateway replaces this
 *   file and the form keeps working unchanged, because it already reads the same
 *   shape.
 *
 * Keep the codes in step with `dally_core/data/dally_service_type_data.xml`.
 */

export interface QuoteService {
  /** Must match a `dally.service.type.code` in Odoo. */
  readonly code: string;
  readonly label: string;
  readonly description: string;
  /** Ask for origin and destination. */
  readonly requiresRoute: boolean;
  /** Ask for goods, weight, volume, packages. */
  readonly requiresCargo: boolean;
}

export const QUOTE_SERVICES: ReadonlyArray<QuoteService> = [
  {
    code: 'import_export',
    label: 'Import & Export',
    description: 'Accompagnement complet de vos opérations internationales.',
    requiresRoute: true,
    requiresCargo: true,
  },
  {
    code: 'freight_sea',
    label: 'Fret maritime',
    description: 'Conteneur complet, groupage ou fret conventionnel.',
    requiresRoute: true,
    requiresCargo: true,
  },
  {
    code: 'freight_air',
    label: 'Fret aérien',
    description: 'Solution rapide pour les expéditions urgentes.',
    requiresRoute: true,
    requiresCargo: true,
  },
  {
    code: 'freight_vehicle',
    label: 'Transport de véhicules',
    description: 'Voitures, utilitaires et engins.',
    requiresRoute: true,
    requiresCargo: true,
  },
  {
    code: 'freight_groupage',
    label: 'Groupage',
    description: 'Partage de conteneur pour les petits volumes.',
    requiresRoute: true,
    requiresCargo: true,
  },
  {
    code: 'logistics',
    label: 'Logistique & Transport',
    description: 'Transport, entreposage et distribution.',
    requiresRoute: true,
    requiresCargo: true,
  },
  {
    code: 'sourcing',
    label: 'Sourcing international',
    description: 'Recherche de fournisseurs et de produits.',
    requiresRoute: false,
    requiresCargo: true,
  },
  {
    code: 'trade',
    label: 'Commerce & Trading',
    description: 'Négoce, courtage et représentation commerciale.',
    requiresRoute: false,
    requiresCargo: true,
  },
  {
    code: 'agrobusiness',
    label: 'Agrobusiness',
    description: 'Produits agricoles : sourcing, conditionnement, export.',
    requiresRoute: false,
    requiresCargo: true,
  },
  {
    code: 'ecommerce',
    label: 'E-commerce',
    description: 'Vente en ligne et traitement des commandes.',
    requiresRoute: false,
    requiresCargo: false,
  },
  {
    code: 'business_solutions',
    label: 'Solutions entreprises',
    description: 'Recherche de partenaires, représentation, accompagnement.',
    requiresRoute: false,
    requiresCargo: false,
  },
  {
    code: 'other',
    label: 'Autre demande',
    description: 'Votre besoin ne figure pas dans la liste.',
    requiresRoute: false,
    requiresCargo: false,
  },
];

export function findService(code: string): QuoteService | undefined {
  return QUOTE_SERVICES.find((service) => service.code === code);
}

/**
 * Steps shown for a given service (§36, §79).
 *
 * Only relevant steps are presented: asking a sourcing prospect for a port of
 * loading is how a form gets abandoned. `route` and `cargo` are dropped when the
 * chosen service does not need them.
 */
export type QuoteStepId = 'service' | 'route' | 'cargo' | 'contact' | 'confirm';

export function stepsForService(code: string | null): ReadonlyArray<QuoteStepId> {
  const service = code ? findService(code) : undefined;
  const steps: QuoteStepId[] = ['service'];
  if (service?.requiresRoute) {
    steps.push('route');
  }
  if (service?.requiresCargo) {
    steps.push('cargo');
  }
  steps.push('contact', 'confirm');
  return steps;
}

export const STEP_LABELS: Readonly<Record<QuoteStepId, string>> = {
  service: 'Service',
  route: 'Trajet',
  cargo: 'Marchandise',
  contact: 'Coordonnées',
  confirm: 'Confirmation',
};
