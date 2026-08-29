import { z } from 'zod';
import { opsGet, opsPost } from '@/lib/auth/odoo-ops';

export const transferRequest = z.object({
  request_uuid: z.string().uuid(), to_actor: z.string().trim().min(1),
  transfer_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/), amount: z.number().positive(),
  currency_code: z.string().trim().min(1), payment_method: z.enum(['cash','wave','bank','other']),
  reason: z.string().trim().min(1).max(200), comment: z.string().trim().max(2000),
}).strict();
export const transfer = z.object({
  reference:z.string(), direction:z.enum(['outgoing','incoming']).optional(), transfer_date:z.string(),
  from_actor:z.string(), to_actor:z.string(), amount:z.number(), currency_code:z.string(),
  payment_method:z.string(), reason:z.string(), state:z.enum(['pending_receipt','received','cancelled']),
  acknowledged_at:z.string().nullable(),
}).strict();
const options = z.object({ from_actor:z.string(), recipients:z.array(z.object({actor:z.string()}).strict()), currencies:z.array(z.object({code:z.string(),name:z.string()}).strict()), payment_methods:z.array(z.object({code:z.string(),name:z.string()}).strict()) }).strict();
const list = z.object({ actor:z.string(), transfers:z.array(transfer), summary:z.array(z.object({direction:z.string(),currency_code:z.string(),amount:z.number()}).strict()) }).strict();
export type TransferRequest = z.infer<typeof transferRequest>; export type Transfer = z.infer<typeof transfer>;
export async function fetchTransferOptions(session:string,corr:string){ return options.parse(await opsGet('cash-transfer-options',session,corr)); }
export async function fetchTransfers(session:string,corr:string){ return list.parse(await opsGet('cash-transfers',session,corr)); }
export async function createTransfer(body:TransferRequest,session:string,corr:string){ return z.object({status:z.enum(['created','replayed']),transfer}).strict().parse(await opsPost('cash-transfers',body,session,corr)); }
export async function acknowledgeTransfer(reference:string,request_uuid:string,session:string,corr:string){ return z.object({status:z.enum(['acknowledged','replayed']),transfer}).strict().parse(await opsPost(`cash-transfers/${encodeURIComponent(reference)}/acknowledge`,{request_uuid},session,corr)); }
