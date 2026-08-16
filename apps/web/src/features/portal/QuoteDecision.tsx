'use client';

import { useReducer, type FormEvent } from 'react';

import {
  portalQuoteDetailSchema,
  portalQuoteDecisionSchema,
  type PortalQuoteDecision as Decision,
  type PortalQuoteDetail,
} from '@/lib/portal/dto';
import { StatusBadge } from './ui';

type Panel = 'idle' | 'accept' | 'reject';

export interface QuoteDecisionState {
  readonly quote: PortalQuoteDetail;
  readonly panel: Panel;
  readonly reason: string;
  readonly busy: boolean;
  readonly error: string;
  readonly success: string;
}

export type QuoteDecisionAction =
  | { readonly type: 'open'; readonly panel: Exclude<Panel, 'idle'> }
  | { readonly type: 'cancel' }
  | { readonly type: 'reason'; readonly value: string }
  | { readonly type: 'submitting' }
  | { readonly type: 'succeeded'; readonly quote: PortalQuoteDetail; readonly message: string }
  | { readonly type: 'failed'; readonly message: string };

export function initialQuoteDecisionState(
  quote: PortalQuoteDetail,
): QuoteDecisionState {
  return {
    quote,
    panel: 'idle',
    reason: '',
    busy: false,
    error: '',
    success: '',
  };
}

export function quoteDecisionReducer(
  state: QuoteDecisionState,
  action: QuoteDecisionAction,
): QuoteDecisionState {
  switch (action.type) {
    case 'open':
      return {
        ...state,
        panel: action.panel,
        reason: '',
        error: '',
        success: '',
      };
    case 'cancel':
      return { ...state, panel: 'idle', reason: '', error: '', busy: false };
    case 'reason':
      return { ...state, reason: action.value };
    case 'submitting':
      return { ...state, busy: true, error: '', success: '' };
    case 'succeeded':
      return {
        ...state,
        quote: action.quote,
        panel: 'idle',
        reason: '',
        busy: false,
        error: '',
        success: action.message,
      };
    case 'failed':
      return { ...state, busy: false, error: action.message, success: '' };
  }
}

export class QuoteDecisionRequestError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'QuoteDecisionRequestError';
  }
}

export async function sendQuoteDecision(
  reference: string,
  input: Decision,
  fetcher: typeof fetch = fetch,
): Promise<PortalQuoteDetail> {
  const parsedInput = portalQuoteDecisionSchema.safeParse(input);
  if (!parsedInput.success) {
    throw new QuoteDecisionRequestError(400, 'La décision transmise est invalide.');
  }

  const response = await fetcher(
    `/api/portal/quotes/${encodeURIComponent(reference)}/decision`,
    {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(parsedInput.data),
      cache: 'no-store',
    },
  );

  let envelope: {
    success?: boolean;
    data?: unknown;
    error?: { message?: string };
  };
  try {
    envelope = await response.json() as typeof envelope;
  } catch {
    throw new QuoteDecisionRequestError(
      response.status || 503,
      'La réponse du service est invalide. Merci de réessayer.',
    );
  }

  if (!response.ok || !envelope.success) {
    throw new QuoteDecisionRequestError(
      response.status,
      envelope.error?.message
        ?? 'La décision n’a pas pu être enregistrée. Merci de réessayer.',
    );
  }

  const confirmed = portalQuoteDetailSchema.safeParse(envelope.data);
  if (!confirmed.success) {
    throw new QuoteDecisionRequestError(
      503,
      'La réponse du service est invalide. Merci de réessayer.',
    );
  }
  return confirmed.data;
}

const STATUS_LABELS: Readonly<Record<string, string>> = {
  new: 'Nouveau',
  qualified: 'Qualifié',
  quoted: 'Devis transmis',
  won: 'Accepté',
  lost: 'Refusé',
  spam: 'Indésirable',
};

function decisionDate(value: string): string {
  const parsed = new Date(`${value.replace(' ', 'T')}Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat('fr-FR', {
    dateStyle: 'long',
    timeStyle: 'short',
    timeZone: 'UTC',
  }).format(parsed);
}

export function QuoteDecision({
  initialQuote,
}: {
  readonly initialQuote: PortalQuoteDetail;
}) {
  const [state, dispatch] = useReducer(
    quoteDecisionReducer,
    initialQuote,
    initialQuoteDecisionState,
  );
  const { quote, panel, reason, busy, error, success } = state;

  async function submit(decision: Decision['decision']) {
    dispatch({ type: 'submitting' });
    try {
      const confirmed = await sendQuoteDecision(
        quote.reference,
        decision === 'accept'
          ? { decision }
          : { decision, ...(reason.trim() ? { reason: reason.trim() } : {}) },
      );
      dispatch({
        type: 'succeeded',
        quote: confirmed,
        message: decision === 'accept'
          ? 'Votre acceptation a été enregistrée.'
          : 'Votre refus a été enregistré.',
      });
    } catch (cause) {
      dispatch({
        type: 'failed',
        message: cause instanceof QuoteDecisionRequestError
          ? cause.message
          : 'Le service est momentanément indisponible. Merci de réessayer.',
      });
    }
  }

  function reject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit('reject');
  }

  const finalLabel =
    quote.status === 'won' ? 'Accepté'
      : quote.status === 'lost' ? 'Refusé'
        : null;

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <StatusBadge label={STATUS_LABELS[quote.status] ?? quote.status} />
        <span className="text-sm text-mist-600">
          Déposée le {quote.createdOn ?? '—'}
        </span>
      </div>

      {success && (
        <p
          role="status"
          className="mb-4 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-900"
        >
          {success}
        </p>
      )}

      {error && (
        <p
          role="alert"
          className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          {error}
        </p>
      )}

      {quote.customerDecisionAt && finalLabel && (
        <p className="mb-4 text-sm font-medium text-navy-800">
          {finalLabel} le {decisionDate(quote.customerDecisionAt)} UTC
        </p>
      )}

      {quote.canDecide && panel === 'idle' && (
        <div className="mb-6 flex flex-wrap gap-3 border-b border-mist-200 pb-6">
          <button
            type="button"
            onClick={() => dispatch({ type: 'open', panel: 'accept' })}
            className="rounded-lg bg-green-700 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-green-800"
          >
            Accepter le devis
          </button>
          <button
            type="button"
            onClick={() => dispatch({ type: 'open', panel: 'reject' })}
            className="rounded-lg border border-red-300 px-5 py-2.5 text-sm font-semibold text-red-800 transition hover:bg-red-50"
          >
            Refuser le devis
          </button>
        </div>
      )}

      {quote.canDecide && panel === 'accept' && (
        <div
          role="group"
          aria-label="Confirmer l’acceptation"
          className="mb-6 rounded-lg border border-green-200 bg-green-50 p-4"
        >
          <p className="font-medium text-green-950">
            Confirmez-vous l’acceptation de ce devis ?
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => void submit('accept')}
              className="rounded-lg bg-green-700 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
            >
              {busy ? 'Enregistrement…' : 'Confirmer l’acceptation'}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => dispatch({ type: 'cancel' })}
              className="rounded-lg border border-mist-300 px-5 py-2.5 text-sm font-medium text-navy-800 disabled:opacity-60"
            >
              Annuler
            </button>
          </div>
        </div>
      )}

      {quote.canDecide && panel === 'reject' && (
        <form
          onSubmit={reject}
          className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4"
        >
          <label className="block text-sm font-medium text-red-950">
            Motif du refus (facultatif)
            <textarea
              value={reason}
              maxLength={500}
              rows={4}
              disabled={busy}
              onChange={(event) => dispatch({
                type: 'reason',
                value: event.target.value,
              })}
              className="mt-2 w-full rounded-lg border border-red-200 bg-white px-3 py-2 text-navy-900 outline-none focus:border-red-500 disabled:opacity-60"
            />
          </label>
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-red-700 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
            >
              {busy ? 'Enregistrement…' : 'Confirmer le refus'}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => dispatch({ type: 'cancel' })}
              className="rounded-lg border border-mist-300 px-5 py-2.5 text-sm font-medium text-navy-800 disabled:opacity-60"
            >
              Annuler
            </button>
          </div>
        </form>
      )}
    </>
  );
}
