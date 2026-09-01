/**
 * `GET|POST /api/intakes/<reference>/photos` — les preuves d'un dossier.
 *
 * ## Pourquoi cette route n'emprunte pas `reponseMutation`
 *
 * Le squelette commun lit du JSON et valide par zod. Un envoi de photo est
 * multipart : il n'a ni corps parsable en JSON, ni schéma applicable avant
 * d'avoir borné les octets. Les cinq contrôles sont donc réappliqués ici, dans
 * le même ordre, et le débit dispose de son propre budget.
 *
 * ## Le corps est borné avant d'être parsé
 *
 * C'est la différence avec le justificatif de caisse, qui appelle
 * `request.formData()` sur un corps de taille inconnue. Un envoi annoncé à
 * zéro octet et long de cent mébioctets — ou simplement chunked — se
 * retrouverait entièrement en mémoire avant d'être refusé. Ici, l'annonce est
 * vérifiée quand elle existe, puis le flux est lu avec un compteur qui coupe
 * net : la mémoire est bornée que l'annonce soit honnête ou non.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import { logger, newCorrelationId } from '@/lib/logger';
import {
  addPhoto,
  fetchPhotos,
  natureCliche,
  TAILLE_MAXIMALE_PHOTO,
  TYPES_PHOTO,
} from '@/lib/ops/photos';
import {
  OPS_PHOTO_IP,
  OPS_PHOTO_REPLAY,
  OPS_PHOTO_SESSION,
  checkRateLimit,
  clePhotoAdmise,
  clePhotoIp,
  clePhotoRejeu,
  clePhotoSession,
  getClientIp,
  peekRateLimit,
} from '@/lib/rate-limit';

export const dynamic = 'force-dynamic';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** L'enveloppe multipart et deux champs de texte : quelques centaines d'octets. */
const MARGE_MULTIPART = 64 * 1024;
const PLAFOND_CORPS = TAILLE_MAXIMALE_PHOTO + MARGE_MULTIPART;

const MESSAGES: Record<string, string> = {
  photo_missing: 'Aucune photo n’a été reçue.',
  photo_empty: 'La photo reçue est vide. Reprenez-la.',
  photo_too_large: 'La photo dépasse 10 Mo. Reprenez-la en qualité réduite.',
  photo_type_not_allowed:
    'Seules les photos JPEG, PNG, WebP ou HEIC sont acceptées.',
  photo_kind_invalid: 'Cette nature de photo n’existe pas.',
  photo_dimensions_unreadable:
    'Cette image n’a pas pu être vérifiée. Reprenez la photo.',
  photo_dimensions_too_large:
    'Cette image est trop grande. Reprenez-la en qualité réduite.',
  photo_state_not_allowed: 'Ce dossier n’accepte plus de photo.',
  photo_quota_active: 'Ce dossier a atteint son nombre de photos.',
  photo_quota_retained: 'Ce dossier a atteint son nombre de photos conservées.',
  photo_quota_bytes: 'Ce dossier a atteint son volume de photos conservées.',
  idempotency_conflict: 'Cet envoi a déjà été traité avec une autre photo.',
  default: 'La photo n’a pas pu être enregistrée.',
};

function erreur(status: number, message: string, code?: string, retryAfter = 0) {
  const reponse = NextResponse.json(
    code ? { success: false, error: message, code } : { success: false, error: message },
    { status },
  );
  if (retryAfter > 0) reponse.headers.set('Retry-After', String(retryAfter));
  reponse.headers.set('Cache-Control', 'no-store');
  return reponse;
}

/**
 * Le corps, lu jusqu'à un plafond et pas au-delà.
 *
 * Rend `null` dès que le plafond est franchi, après avoir annulé la source :
 * l'émetteur cesse d'être écouté au lieu d'être poliment absorbé jusqu'au
 * bout.
 */
async function corpsBorne(
  requete: Request, plafond: number,
): Promise<Blob | null> {
  if (!requete.body) return new Blob([]);
  const lecteur = requete.body.getReader();
  const morceaux: BlobPart[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await lecteur.read();
    if (done) break;
    if (!value) continue;
    total += value.byteLength;
    if (total > plafond) {
      await lecteur.cancel('corps trop volumineux').catch(() => undefined);
      return null;
    }
    morceaux.push(value);
  }
  return new Blob(morceaux);
}

export async function GET(
  request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference } = await contexte.params;
  const session = await readOpsSession();
  if (!session) return erreur(401, 'Session expirée.');
  try {
    const data = await fetchPhotos(
      decodeURIComponent(reference), session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (e) {
    const code = e instanceof OpsGatewayError ? e.code : 'error';
    if (code === 'forbidden') return erreur(401, 'Session expirée.');
    if (code === 'not_found') return erreur(404, 'Dossier introuvable.');
    logger.error('ops.photos.list.error', { correlationId, code });
    return erreur(503, 'Service momentanément indisponible.');
  }
}

export async function POST(
  request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference } = await contexte.params;
  const depart = Date.now();

  if (!origineAcceptable(request)) return erreur(403, 'Requête refusée.');
  const typeAnnonce = request.headers.get('content-type') ?? '';
  if (!typeAnnonce.includes('multipart/form-data')) {
    return erreur(415, 'Requête refusée.');
  }

  const session = await readOpsSession();
  if (!session) return erreur(401, 'Session expirée.');

  // Première garde : l'annonce, quand elle existe. Inutile de lire cent
  // mébioctets pour les refuser ensuite.
  const annonce = Number(request.headers.get('content-length') ?? '');
  if (Number.isFinite(annonce) && annonce > PLAFOND_CORPS) {
    return erreur(422, MESSAGES['photo_too_large'] ?? '', 'photo_too_large');
  }

  // Seconde garde : le flux réel, compté. Elle seule protège d'une annonce
  // absente, fausse, ou d'un envoi chunked.
  const corps = await corpsBorne(request, PLAFOND_CORPS);
  if (corps === null) {
    return erreur(422, MESSAGES['photo_too_large'] ?? '', 'photo_too_large');
  }

  let formulaire: FormData;
  try {
    formulaire = await new Request('https://ops.local/photos', {
      method: 'POST',
      headers: { 'content-type': typeAnnonce },
      body: corps,
    }).formData();
  } catch {
    return erreur(400, 'Requête invalide.');
  }

  const requestUuid = formulaire.get('request_uuid');
  if (typeof requestUuid !== 'string' || !UUID.test(requestUuid)) {
    return erreur(400, 'Requête invalide.');
  }
  const nature = natureCliche.safeParse(formulaire.get('kind'));
  if (!nature.success) {
    return erreur(422, MESSAGES['photo_kind_invalid'] ?? '', 'photo_kind_invalid');
  }
  const fichier = formulaire.get('photo');
  if (!(fichier instanceof File) || fichier.size === 0) {
    return erreur(422, MESSAGES['photo_missing'] ?? '', 'photo_missing');
  }
  if (fichier.size > TAILLE_MAXIMALE_PHOTO) {
    return erreur(422, MESSAGES['photo_too_large'] ?? '', 'photo_too_large');
  }
  // Le type annoncé n'est qu'un premier tri : Odoo tranche sur les octets.
  if (!(TYPES_PHOTO as readonly string[]).includes(fichier.type)) {
    return erreur(422, MESSAGES['photo_type_not_allowed'] ?? '',
                  'photo_type_not_allowed');
  }

  // ── Débit ────────────────────────────────────────────────────────
  //
  // La clé d'admission ne dit pas « déjà vu » : elle dit « déjà traité avec
  // succès par Odoo ». Elle n'est écrite qu'après une réponse réussie, et sa
  // lecture ici ne l'écrit pas. Un envoi refusé — par le débit, par une
  // validation, par une panne — ne laisse donc aucune trace derrière lui, et
  // ne peut pas se transformer en laissez-passer.
  const cleSession = clePhotoSession(session.odooSessionId);
  const cleIp = clePhotoIp(getClientIp(request.headers));
  const cleAdmise = clePhotoAdmise(requestUuid);
  const admis = !peekRateLimit(cleAdmise, 1).allowed;

  if (admis) {
    // Une reprise garde sa place quand le budget de session s'est rempli
    // entre-temps. Bornée tout de même : cinq reprises couvrent un réseau
    // d'entrepôt ; au-delà ce n'est plus une reprise.
    const reprise = checkRateLimit(
      clePhotoRejeu(requestUuid), OPS_PHOTO_REPLAY.limite, OPS_PHOTO_REPLAY.fenetreMs);
    if (!reprise.allowed) {
      logger.warn('ops.photos.throttled', { correlationId, scope: 'replay' });
      return erreur(429, 'Trop de reprises pour cet envoi. Reprenez la photo.',
                    undefined, reprise.retryAfterSeconds);
    }
  } else {
    for (const [cle, budget, portee] of [
      [cleSession, OPS_PHOTO_SESSION, 'session'],
      [cleIp, OPS_PHOTO_IP, 'ip'],
    ] as const) {
      const etat = peekRateLimit(cle, budget.limite);
      if (!etat.allowed) {
        logger.warn('ops.photos.throttled', { correlationId, scope: portee });
        return erreur(429, 'Trop d’envois. Réessayez dans quelques minutes.',
                      undefined, etat.retryAfterSeconds);
      }
    }
    checkRateLimit(cleSession, OPS_PHOTO_SESSION.limite, OPS_PHOTO_SESSION.fenetreMs);
    checkRateLimit(cleIp, OPS_PHOTO_IP.limite, OPS_PHOTO_IP.fenetreMs);
  }

  try {
    const data = await addPhoto(
      decodeURIComponent(reference),
      requestUuid,
      nature.data,
      { nom: fichier.name, type: fichier.type, contenu: fichier },
      session.odooSessionId,
      correlationId,
    );
    // Le geste est admis : à partir d'ici, et seulement à partir d'ici, une
    // reprise pourra passer sans reprendre du budget de session.
    checkRateLimit(cleAdmise, 1, OPS_PHOTO_SESSION.fenetreMs);
    // Ni le nom du fichier, ni sa taille, ni son type : une preuve de terrain
    // n'est pas une ligne de journal applicatif.
    logger.info('ops.photos.added', { correlationId, durationMs: Date.now() - depart });
    return NextResponse.json(
      { success: true, data },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (e) {
    const code = e instanceof OpsGatewayError ? e.code : 'error';
    const refus = e instanceof OpsGatewayError ? (e.conflictCode ?? 'default') : 'default';
    if (code === 'forbidden') return erreur(401, 'Session expirée.');
    if (code === 'not_found') return erreur(404, 'Dossier introuvable.');
    if (code === 'invalid_request') return erreur(400, 'Requête invalide.');
    if (code === 'unprocessable') {
      logger.warn('ops.photos.rejected', { correlationId, code: refus });
      return erreur(422, MESSAGES[refus] ?? MESSAGES['default'] ?? '', refus);
    }
    if (code === 'conflict') {
      logger.warn('ops.photos.conflict', { correlationId, code: refus });
      return erreur(409, MESSAGES[refus] ?? MESSAGES['default'] ?? '', refus);
    }
    logger.error('ops.photos.error', { correlationId, code });
    return erreur(503, 'Service momentanément indisponible.');
  }
}
