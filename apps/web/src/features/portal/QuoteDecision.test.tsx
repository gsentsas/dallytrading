import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import type { PortalQuoteDetail } from '@/lib/portal/dto';
import {
  initialQuoteDecisionState,
  QuoteDecision,
  QuoteDecisionRequestError,
  quoteDecisionReducer,
  sendQuoteDecision,
} from './QuoteDecision';

const DECIDABLE: PortalQuoteDetail = {
  reference: 'DT-2026-000888',
  service: 'freight_sea',
  status: 'quoted',
  createdOn: '2026-08-16',
  origin: 'Dakar',
  destination: 'Abidjan',
  goodsDescription: 'Marchandise synthétique',
  quantity: '2 conteneurs',
  canDecide: true,
  customerDecisionAt: null,
};

function response(quote: PortalQuoteDetail, status = 200): Response {
  return new Response(JSON.stringify({
    success: status < 400,
    ...(status < 400
      ? { data: quote }
      : { error: { message: status === 409 ? 'Conflit métier.' : 'Introuvable.' } }),
  }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('QuoteDecision', () => {
  it('affiche les deux actions uniquement quand Odoo dit le devis décidable', () => {
    const markup = renderToStaticMarkup(<QuoteDecision initialQuote={DECIDABLE} />);
    expect(markup).toContain('Accepter le devis');
    expect(markup).toContain('Refuser le devis');

    const finalMarkup = renderToStaticMarkup(
      <QuoteDecision
        initialQuote={{
          ...DECIDABLE,
          status: 'won',
          canDecide: false,
          customerDecisionAt: '2026-08-16 12:00:00',
        }}
      />,
    );
    expect(finalMarkup).not.toContain('Accepter le devis');
    expect(finalMarkup).not.toContain('Refuser le devis');
    expect(finalMarkup).toContain('Accepté le');
  });

  it('passe en loading puis remplace uniquement par la réponse confirmée', () => {
    const initial = initialQuoteDecisionState(DECIDABLE);
    const opened = quoteDecisionReducer(initial, { type: 'open', panel: 'accept' });
    const loading = quoteDecisionReducer(opened, { type: 'submitting' });
    expect(loading.busy).toBe(true);
    expect(loading.quote).toBe(DECIDABLE);

    const confirmed = {
      ...DECIDABLE,
      status: 'won',
      canDecide: false,
      customerDecisionAt: '2026-08-16 12:00:00',
    };
    const succeeded = quoteDecisionReducer(loading, {
      type: 'succeeded',
      quote: confirmed,
      message: 'Acceptation enregistrée.',
    });
    expect(succeeded.busy).toBe(false);
    expect(succeeded.quote).toEqual(confirmed);
    expect(succeeded.panel).toBe('idle');
    expect(succeeded.success).toContain('enregistrée');
  });

  it('conserve le devis confirmé précédent en cas d’erreur', () => {
    const loading = quoteDecisionReducer(
      initialQuoteDecisionState(DECIDABLE),
      { type: 'submitting' },
    );
    const failed = quoteDecisionReducer(loading, {
      type: 'failed',
      message: 'Conflit métier.',
    });
    expect(failed.busy).toBe(false);
    expect(failed.quote).toBe(DECIDABLE);
    expect(failed.error).toBe('Conflit métier.');
  });

  it.each([
    [{ decision: 'accept' } as const, 'won'],
    [{ decision: 'reject', reason: '  Non adapté  ' } as const, 'lost'],
  ])('utilise la réponse Odoo pour le succès %j', async (decision, status) => {
    const confirmed = {
      ...DECIDABLE,
      status,
      canDecide: false,
      customerDecisionAt: '2026-08-16 12:00:00',
    };
    const fetcher = vi.fn().mockResolvedValue(response(confirmed));

    await expect(
      sendQuoteDecision(DECIDABLE.reference, decision, fetcher),
    ).resolves.toEqual(confirmed);

    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(encodeURIComponent(DECIDABLE.reference));
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('same-origin');
    expect(init.cache).toBe('no-store');
    expect(JSON.parse(String(init.body))).toEqual(
      decision.decision === 'accept'
        ? { decision: 'accept' }
        : { decision: 'reject', reason: 'Non adapté' },
    );
  });

  it.each([
    [409, 'Conflit métier.'],
    [404, 'Introuvable.'],
  ])('rapporte explicitement l’erreur HTTP %i', async (status, message) => {
    const fetcher = vi.fn().mockResolvedValue(response(DECIDABLE, status));
    await expect(
      sendQuoteDecision(DECIDABLE.reference, { decision: 'accept' }, fetcher),
    ).rejects.toMatchObject({
      status,
      message,
    } satisfies Partial<QuoteDecisionRequestError>);
  });

  it('refuse localement le mass assignment sans appeler fetch', async () => {
    const fetcher = vi.fn();
    await expect(sendQuoteDecision(
      DECIDABLE.reference,
      { decision: 'accept', state: 'won' } as never,
      fetcher,
    )).rejects.toMatchObject({ status: 400 });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('refuse une réponse élargie par un canari interne', async () => {
    const fetcher = vi.fn().mockResolvedValue(response({
      ...DECIDABLE,
      margin: 9000,
    } as PortalQuoteDetail));
    await expect(
      sendQuoteDecision(DECIDABLE.reference, { decision: 'accept' }, fetcher),
    ).rejects.toMatchObject({ status: 503 });
  });
});
