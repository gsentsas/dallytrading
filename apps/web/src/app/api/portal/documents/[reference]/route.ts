/**
 * GET /api/portal/documents/[reference] — le fichier, par notre serveur.
 *
 * ## Pourquoi ne pas rediriger vers Odoo
 *
 * Une redirection vers `/web/content/<id>` serait plus simple et livrerait le
 * fichier. Elle donnerait aussi au navigateur une URL Odoo durable : copiable,
 * partageable, indexable, et valable tant que la session vit. Le contrôle
 * d'accès existerait toujours côté Odoo, mais l'adresse aurait quitté notre
 * périmètre, et nous n'aurions plus aucun moyen de savoir qui la détient.
 *
 * Les octets transitent donc par ici. Le navigateur ne connaît que
 * `/api/portal/documents/DOC-42`, qui ne fonctionne qu'avec le cookie de session.
 *
 * ## Ce que ce handler ne décide pas
 *
 * Il ne décide pas qui a le droit. Odoo refait le contrôle complet — record rule
 * sur `dally.portal.document` (appartenance ET `published_to_portal`), puis
 * `check_access` avant de lire la pièce jointe. Un identifiant deviné ne ramène
 * rien, et la réponse est le même 404 que pour un document inexistant.
 */

import type { NextResponse } from 'next/server';

import { downloadDocument } from '@/lib/portal/business';
import { PortalGatewayError } from '@/lib/portal/odoo-portal';
import { logger, newCorrelationId } from '@/lib/logger';
import { portalError } from '../../_shared';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ reference: string }> },
): Promise<Response | NextResponse> {
  const correlationId = newCorrelationId();
  const { reference } = await params;

  try {
    const { body, filename } = await downloadDocument(reference, correlationId);

    return new Response(body, {
      status: 200,
      headers: {
        // Jamais le type MIME déclaré à l'envoi : un fichier téléversé qui
        // s'annoncerait `text/html` s'exécuterait dans le navigateur, sur notre
        // origine, avec le cookie de session. Odoo renvoie déjà
        // `application/octet-stream` ; on le réaffirme plutôt que de le relayer.
        'Content-Type': 'application/octet-stream',
        // `attachment` : le fichier est enregistré, jamais rendu dans la page.
        'Content-Disposition': `attachment; filename="${filename}"`,
        'Content-Length': String(body.byteLength),
        'Cache-Control': 'no-store',
        // Sans `nosniff`, un navigateur peut ignorer le type déclaré et deviner
        // d'après le contenu — ce qui annulerait la précaution ci-dessus.
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
      },
    });
  } catch (error) {
    if (error instanceof PortalGatewayError) {
      if (
        error.code === 'not_found' ||
        error.code === 'unauthenticated' ||
        error.code === 'forbidden'
      ) {
        // Un seul et même 404 : « n'existe pas », « ne vous appartient pas »,
        // « pas publié » et « session expirée » sont indistinguables de dehors.
        return portalError(404, 'not_found', 'Document introuvable.', correlationId);
      }
      logger.error('Portal document download failed', {
        correlationId, code: error.code,
      });
    } else {
      logger.error('Portal document download failed', { correlationId });
    }
    return portalError(
      503, 'unavailable', 'Le service est momentanément indisponible.', correlationId,
    );
  }
}
