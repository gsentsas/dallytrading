import { beforeEach, describe, expect, it, vi } from 'vitest';
import { z } from 'zod';

import { reponseMutation, type BudgetMutation } from '@/lib/ops/mutation-http';
import {
  checkRateLimit,
  cleDemandeComptee,
  peekRateLimit,
  resetRateLimits,
} from '@/lib/rate-limit';

const UUID = '11111111-1111-4111-8111-111111111111';
const FENETRE = 60_000;
const cleSession = (session: string) => `test:mutation:session:${session}`;
const cleIp = (ip: string) => `test:mutation:ip:${ip}`;

const budgetHistorique: BudgetMutation = {
  session: { limite: 2, fenetreMs: FENETRE },
  ip: { limite: 2, fenetreMs: FENETRE },
  cleSession,
  cleIp,
};

beforeEach(() => resetRateLimits());

describe('le namespace de demande reste rétrocompatible', () => {
  it('un budget sans cleDemande utilise encore cleDemandeComptee', async () => {
    checkRateLimit(cleDemandeComptee(UUID), 1, FENETRE);
    const executer = vi.fn(async () => ({ ok: true }));

    const reponse = await reponseMutation({
      request: new Request('https://ops.test/mutation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_uuid: UUID }),
      }),
      correlationId: 'correlation',
      origineAcceptable: () => true,
      lireSession: async () => ({ odooSessionId: 'session', issuedAt: 1 }),
      schema: z.object({ request_uuid: z.string() }),
      evenement: 'test.mutation',
      executer,
      budget: budgetHistorique,
    });

    expect(reponse.status).toBe(200);
    expect(executer).toHaveBeenCalledOnce();
    expect(peekRateLimit(cleSession('session'), 2).remaining).toBe(2);
  });
});
