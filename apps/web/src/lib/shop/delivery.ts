import { z } from 'zod';

export const deliveryMethodCodeSchema = z
  .string()
  .min(1)
  .max(64)
  .regex(/^[a-z0-9]+(?:[-_][a-z0-9]+)*$/);

export const deliveryMethodSchema = z
  .object({
    code: deliveryMethodCodeSchema,
    name: z.string().min(1).max(128),
    kind: z.enum(['pickup', 'delivery']),
    requiresAddress: z.boolean(),
    feePolicy: z.enum(['free', 'fixed', 'quote']),
    feeAmount: z.number().nonnegative().nullable(),
    currency: z.string().min(1).max(8),
    help: z.string().max(300),
  })
  .strict();

export const deliveryMethodsEnvelopeSchema = z
  .object({ methods: z.array(deliveryMethodSchema).max(20) })
  .strict();

export type DeliveryMethod = z.infer<typeof deliveryMethodSchema>;
export type DeliveryMethodCode = z.infer<typeof deliveryMethodCodeSchema>;

const optionalText = (max: number) =>
  z
    .string()
    .trim()
    .max(max)
    .transform((value) => (value === '' ? undefined : value))
    .optional();

export const shippingAddressSchema = z
  .object({
    name: optionalText(128),
    phone: optionalText(32),
    street: optionalText(200),
    street2: optionalText(200),
    city: optionalText(100),
    zip: optionalText(20),
    country_code: z
      .string()
      .trim()
      .toUpperCase()
      .refine((value) => value === '' || /^[A-Z]{2}$/.test(value), {
        message: 'Le code pays doit comporter deux lettres.',
      })
      .transform((value) => (value === '' ? undefined : value))
      .optional(),
  })
  .strict();

export type ShippingAddress = z.infer<typeof shippingAddressSchema>;
