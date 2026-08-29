import { z } from 'zod';

export const RECEPTION_AGENDA_KEY = 'dally-ops:appointment-reception';

export const preparedReceptionSchema = z.object({
  customer_reference: z.string().uuid(),
  customer_name: z.string(),
  consolidation_reference: z.string().nullable(),
}).strict();

export type PreparedReception = z.infer<typeof preparedReceptionSchema>;
