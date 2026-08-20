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

export const shippingAddressSchema = z
  .object({
    name: z.string().trim().max(128).optional(),
    phone: z.string().trim().max(32).optional(),
    street: z.string().trim().max(200).optional(),
    street2: z.string().trim().max(200).optional(),
    city: z.string().trim().max(100).optional(),
    zip: z.string().trim().max(20).optional(),
    country_code: z
      .string()
      .trim()
      .toUpperCase()
      .regex(/^[A-Z]{2}$/)
      .optional(),
  })
  .strict();

export type ShippingAddress = z.infer<typeof shippingAddressSchema>;
