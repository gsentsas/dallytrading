/**
 * Le squelette commun des mutations d'articles.
 *
 * Origine, session, contrat, débit, traduction des refus : cinq contrôles que
 * deux routes doivent appliquer exactement de la même façon. Les écrire deux
 * fois, c'est accepter qu'un jour l'une des deux en oublie un.
 */

import { NextResponse } from 'next/server';
import type { z } from 'zod';

import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import type { OpsSession } from '@/lib/auth/session';
import { logger } from '@/lib/logger';
import {
  OPS_INTAKE_IP,
  OPS_INTAKE_SESSION,
  checkRateLimit,
  cleIntakeIp,
  cleIntakeSession,
  cleDemandeComptee,
  getClientIp,
  peekRateLimit,
} from '@/lib/rate-limit';

function erreur(status: number, message: string, code?: string, retryAfter = 0) {
  const reponse = NextResponse.json(
    code ? { success: false, error: message, code } : { success: false, error: message },
    { status },
  );
  if (retryAfter > 0) reponse.headers.set('Retry-After', String(retryAfter));
  reponse.headers.set('Cache-Control', 'no-store');
  return reponse;
}

interface Options<T extends z.ZodTypeAny> {
  readonly request: Request;
  readonly correlationId: string;
  readonly origineAcceptable: (requete: Request) => boolean;
  readonly lireSession: () => Promise<OpsSession | null>;
  readonly schema: T;
  readonly evenement: string;
  readonly executer: (demande: z.infer<T>, sessionId: string) => Promise<unknown>;
}

export async function reponseMutation<T extends z.ZodTypeAny>(
  options: Options<T>,
): Promise<NextResponse> {
  const { request, correlationId, evenement } = options;
  const depart = Date.now();

  if (!options.origineAcceptable(request)) return erreur(403, 'Requête refusée.');
  if (!(request.headers.get('content-type') ?? '').includes('application/json')) {
    return erreur(415, 'Requête refusée.');
  }

  const session = await options.lireSession();
  if (!session) return erreur(401, 'Session expirée.');

  let corps: unknown;
  try {
    corps = await request.json();
  } catch {
    return erreur(400, 'Requête invalide.');
  }

  const analyse = options.schema.safeParse(corps);
  if (!analyse.success) {
    // Le motif décrirait le corps soumis : on ne le renvoie pas.
    return erreur(400, 'Vérifiez les informations saisies.');
  }
  const demande = analyse.data as { request_uuid: string };

  const cleSession = cleIntakeSession(session.odooSessionId);
  const cleIp = cleIntakeIp(getClientIp(request.headers));
  for (const [cle, budget, portee] of [
    [cleSession, OPS_INTAKE_SESSION, 'session'],
    [cleIp, OPS_INTAKE_IP, 'ip'],
  ] as const) {
    const etat = peekRateLimit(cle, budget.limite);
    if (!etat.allowed) {
      logger.warn(`${evenement}.throttled`, { correlationId, scope: portee });
      return erreur(429, 'Trop d’opérations. Réessayez dans quelques minutes.',
                    undefined, etat.retryAfterSeconds);
    }
  }
  // Les tentatives réseau d'une même demande ne comptent qu'une fois.
  const premiere = checkRateLimit(
    cleDemandeComptee(demande.request_uuid), 1, OPS_INTAKE_SESSION.fenetreMs);
  if (premiere.allowed) {
    checkRateLimit(cleSession, OPS_INTAKE_SESSION.limite, OPS_INTAKE_SESSION.fenetreMs);
    checkRateLimit(cleIp, OPS_INTAKE_IP.limite, OPS_INTAKE_IP.fenetreMs);
  }

  try {
    const data = await options.executer(analyse.data, session.odooSessionId);
    logger.info(evenement, { correlationId, durationMs: Date.now() - depart });
    return NextResponse.json(
      { success: true, data },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (e) {
    const code = e instanceof OpsGatewayError ? e.code : 'error';
    if (code === 'forbidden') return erreur(401, 'Session expirée.');
    if (code === 'not_found') return erreur(404, 'Dossier ou article introuvable.');
    if (code === 'invalid_request') return erreur(400, 'Vérifiez les informations saisies.');
    if (code === 'unprocessable') {
      const refus = (e as OpsGatewayError).conflictCode ?? 'default';
      logger.warn(`${evenement}.rejected`, { correlationId, code: refus });
      return erreur(422, MESSAGES_REFUS[refus] ?? MESSAGES_REFUS['default'] ?? '', refus);
    }
    if (code === 'conflict') {
      const conflit = (e as OpsGatewayError).conflictCode ?? 'conflict';
      logger.warn(`${evenement}.conflict`, { correlationId, code: conflit });
      const message = MESSAGES_CONFLIT[conflit] ?? MESSAGES_CONFLIT['default'] ?? '';
      return erreur(409, message, conflit);
    }
    logger.error(`${evenement}.error`, { correlationId, code });
    return erreur(503, 'Service momentanément indisponible.');
  }
}

/**
 * Ce que l'opérateur lit selon le conflit.
 *
 * Chaque cas appelle un geste différent : recharger, appeler un responsable,
 * ou simplement constater que la collecte est close. Un message unique
 * laisserait le terrain sans savoir quoi faire.
 */
const MESSAGES_REFUS: Record<string, string> = {
  invalid_payment_date: 'La date du paiement n’est pas valide.',
  invalid_expense_date:
    'La date de la dépense n’est pas valide : elle ne peut pas être dans le futur.',
  invalid_paid_at:
    'La date d’encaissement n’est pas valide : elle ne peut pas être dans le futur.',
  invalid_wave_reference:
    'Cette référence Wave n’a pas un format valide. Recopiez-la depuis Wave, ou laissez le champ vide.',
  payment_channel_not_available: 'Ce moyen de paiement n’est pas disponible.',
  payment_method_not_allowed: 'Ce mode de paiement n’est pas accepté.',
  currency_not_available: 'Cette devise n’est pas disponible.',
  receipt_missing: 'Aucune photo n’a été reçue.',
  receipt_empty: 'La photo reçue est vide. Reprenez-la.',
  receipt_too_large: 'La photo dépasse 10 Mo. Reprenez-la en qualité réduite.',
  receipt_type_not_allowed:
    'Seules les photos JPEG, PNG, WebP ou HEIC sont acceptées comme justificatif.',
  default: 'Vérifiez les informations saisies.',
};

const MESSAGES_CONFLIT: Record<string, string> = {
  stale_line:
    'Cet article a été modifié depuis son affichage. Rechargez le dossier avant de poursuivre.',
  billing_locked:
    'Ce dossier est déjà engagé dans la facturation. Les articles ne peuvent plus être modifiés.',
  consolidation_not_open: 'Ce départ n’est plus ouvert à la réception.',
  intake_not_editable: 'Ce dossier n’est plus modifiable.',
  line_reference_conflict: 'Cet article existe déjà dans ce dossier.',
  idempotency_conflict:
    'Cette demande a déjà été traitée avec d’autres informations.',
  cash_actor_not_configured:
    'Votre compte n’est pas encore configuré pour la caisse. Demandez à un responsable.',
  cash_actor_configuration_conflict:
    'La configuration des acteurs de caisse est ambiguë. Un responsable doit la corriger.',
  wave_beneficiary_not_configured:
    'Le bénéficiaire des encaissements Wave n’est pas configuré. Demandez à un responsable.',
  wave_reference_already_used:
    'Cette référence Wave a déjà été enregistrée sur un autre encaissement. Vérifiez le numéro.',
  intake_cancelled: 'Ce dossier est annulé : il ne peut plus être encaissé.',
  receipt_already_attached:
    'Cette dépense a déjà un justificatif. Il ne peut pas être remplacé depuis le terrain.',
  // L'avancement d'état. Chaque refus appelle un geste différent : recharger la
  // fiche, compléter le dossier, ou constater que l'étape n'existe pas ici.
  state_changed:
    'Le dossier a changé depuis son affichage.',
  state_transition_blocked:
    'Ce dossier n’est pas encore complet pour cette étape. '
    + 'Vérifiez les articles, les poids et la tarification.',
  state_transition_not_allowed:
    'Cette étape n’est pas accessible depuis l’état actuel.',
  state_target_not_allowed:
    'Cette étape ne peut pas être demandée depuis Dally Ops.',
  // Le retrait d'une preuve photographique. L'ajout, lui, est multipart et
  // porte ses propres messages : il n'emprunte pas ce squelette.
  photo_already_deleted: 'Cette photo a déjà été retirée.',
  photo_delete_not_allowed:
    'Vous ne pouvez pas retirer cette photo. Demandez à un responsable.',
  default: 'Cette opération n’est plus possible.',
};
