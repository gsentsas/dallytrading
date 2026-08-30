import { z } from 'zod';

import { opsGet, opsPost } from '@/lib/auth/odoo-ops';

const dimension = z.number().positive().nullable();

export const demandeIntake = z
  .object({
    request_uuid: z.string().uuid(),
    consolidation_reference: z.string().trim().min(1).max(120),
    customer_reference: z.string().uuid(),
    received_on: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    line: z
      .object({
        line_uuid: z.string().uuid(),
        package_type: z.enum([
          'parcel', 'pallet', 'crate', 'bag', 'drum', 'other',
        ]),
        goods_category: z.string().trim().min(1).max(200),
        description: z.string().trim().min(1).max(500),
        quantity: z.number().int().positive(),
        announced_weight_kg: z.number().nonnegative().nullable(),
        exact_weight_kg: z.number().positive(),
        length_cm: dimension,
        width_cm: dimension,
        height_cm: dimension,
        billing_method: z.enum(['real', 'volumetric', 'quote']),
        tariff_family_code: z.string().trim().min(1).max(80),
        customs_value_xof: z.number().positive(),
      })
      .strict(),
  })
  .strict()
  .superRefine((demande, contexte) => {
    const dimensions = [
      demande.line.length_cm,
      demande.line.width_cm,
      demande.line.height_cm,
    ];
    const presentes = dimensions.filter(
      (valeur) => valeur !== null,
    ).length;
    if (presentes !== 0 && presentes !== 3) {
      contexte.addIssue({
        code: 'custom',
        message: 'dimensions incomplètes',
        path: ['line', 'length_cm'],
      });
    }
    if (
      demande.line.billing_method === 'volumetric'
      && presentes !== 3
    ) {
      contexte.addIssue({
        code: 'custom',
        message: 'dimensions obligatoires',
        path: ['line', 'billing_method'],
      });
    }
  });

export type DemandeIntake = z.infer<typeof demandeIntake>;

const ligneIntake = z
  .object({
    reference: z.string().uuid(),
    description: z.string(),
    goods_category: z.string(),
    quantity: z.number().int().positive(),
    exact_weight_kg: z.number().positive(),
    volume_cbm: z.number().nonnegative(),
    billing_method: z.enum(['real', 'volumetric', 'quote']),
    tariff_family_code: z.string(),
    customs_value_xof: z.number().positive(),
    pricing_status: z.enum([
      'automatic', 'manual_required', 'quote',
    ]),
    billable_weight_kg: z.number().nonnegative(),
    applied_unit_price_eur: z.number().nonnegative().nullable(),
    transport_amount_eur: z.number().nonnegative().nullable(),
  })
  .strict();

const resultatIntake = z
  .object({
    status: z.enum(['created', 'replayed']),
    intake: z
      .object({
        reference: z.string().min(1),
        local_reference: z.string().regex(/^A\d{3,}$/),
        consolidation_reference: z.string().min(1),
        state: z.literal('goods_received'),
        received_on: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
        line: ligneIntake,
        totals: z
          .object({
            weight_kg: z.number().positive(),
            volume_cbm: z.number().nonnegative(),
            transport_amount_eur: z.number().nonnegative().nullable(),
          })
          .strict(),
      })
      .strict(),
  })
  .strict();

export type ResultatIntake = z.infer<typeof resultatIntake>;

export async function createIntake(
  demande: DemandeIntake,
  sessionId: string,
  correlationId: string,
): Promise<ResultatIntake> {
  const brut = await opsPost<unknown>(
    'intakes', demande, sessionId, correlationId,
  );
  return resultatIntake.parse(brut);
}

const familleTarifaire = z
  .object({
    code: z.string().min(1),
    name: z.string().min(1),
  })
  .strict();

const listeFamilles = z
  .object({
    tariff_families: z.array(familleTarifaire),
  })
  .strict();

export type FamilleTarifaire = z.infer<typeof familleTarifaire>;

export async function fetchTariffFamilies(
  sessionId: string,
  correlationId: string,
): Promise<FamilleTarifaire[]> {
  const brut = await opsGet<unknown>(
    'tariff-families', sessionId, correlationId,
  );
  return listeFamilles.parse(brut).tariff_families;
}

