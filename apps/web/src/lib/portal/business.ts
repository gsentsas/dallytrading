/**
 * La DAL métier du portail — le seul endroit qui parle des dossiers du client.
 *
 * ## Ce que chaque fonction fait, invariablement
 *
 * Elle exige une session portail vérifiée, appelle `PortalOdooGateway` (jamais la
 * passerelle d'intégration, qui n'est même pas importable depuis cette couche),
 * valide la réponse contre un schéma strict, et normalise l'erreur.
 *
 * ## Ce qu'aucune ne fait
 *
 * Aucune ne filtre par client. Il n'y a pas un seul `partner_id` dans ce fichier,
 * et c'est délibéré : le cloisonnement est assuré par les record rules Odoo, sous
 * l'identité de la session. Réécrire ce filtre ici en créerait une seconde
 * définition — et la seconde définition d'une règle de sécurité est celle qu'on
 * oublie de mettre à jour.
 *
 * Aucune n'accepte non plus de domaine, de tri libre ou de limite venant du
 * navigateur : la pagination est bornée côté Odoo, et ce qui remonte d'ici est
 * seulement une page et un décalage, contraints.
 */

import { z } from 'zod';

import { readPortalSession } from './auth';
import { PortalGatewayError, PortalOdooGateway } from './odoo-portal';
import {
  portalDashboardSchema,
  portalDocumentSchema,
  portalListSchema,
  portalProfileSchema,
  portalQuoteDetailSchema,
  portalQuoteSchema,
  portalShipmentDetailSchema,
  portalShipmentSchema,
  portalSourcingDetailSchema,
  portalSourcingRequestSchema,
  portalTradeDetailSchema,
  portalTradeSchema,
  type PortalDashboard,
  type PortalDocument,
  type PortalList,
  type PortalProfile,
  type PortalQuote,
  type PortalQuoteDetail,
  type PortalShipment,
  type PortalShipmentDetail,
  type PortalSourcingDetail,
  type PortalSourcingRequest,
  type PortalTrade,
  type PortalTradeDetail,
} from './dto';

const gateway = new PortalOdooGateway();

/** Taille de page. Odoo plafonne à 100 ; on reste bien en deçà pour l'affichage. */
export const PAGE_SIZE = 20;

/**
 * Appelle Odoo sous la session du client, puis valide.
 *
 * L'absence de session lève `unauthenticated` avant tout appel réseau : sans
 * cela, un chemin d'erreur pourrait aboutir à une requête sans cookie, qu'Odoo
 * traiterait comme anonyme — et le jour où un endpoint deviendrait `auth="public"`,
 * la faute serait ici.
 */
async function fetchPortal<T>(
  path: string,
  schema: z.ZodType<T>,
  correlationId: string,
): Promise<T> {
  const session = await readPortalSession();
  if (!session) {
    throw new PortalGatewayError('unauthenticated', 'no portal session');
  }
  const raw = await gateway.get<unknown>(path, session.odooSessionId, correlationId);
  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    // Le détail de l'écart n'est PAS journalisé : il contiendrait la valeur
    // reçue, donc potentiellement les données du client. Seul le chemin l'est.
    throw new PortalGatewayError(
      'unavailable', `unexpected ERP payload for ${path}`,
    );
  }
  return parsed.data;
}

/** Segment d'URL sûr : une référence vient de l'utilisateur, jamais de nous. */
function encodeReference(reference: string): string {
  return encodeURIComponent(reference);
}

/**
 * Décalage de pagination, borné.
 *
 * `page` arrive de la query string, donc du navigateur. Une valeur absurde est
 * ramenée à la première page plutôt que transmise : Odoo la bornerait de toute
 * façon, mais lui envoyer `offset=1e9` reviendrait à lui faire compter pour rien.
 */
export function offsetForPage(page: number): number {
  if (!Number.isFinite(page) || page < 1) return 0;
  return Math.min(Math.floor(page - 1), 10_000) * PAGE_SIZE;
}

function listPath(resource: string, page: number): string {
  return `/${resource}?limit=${PAGE_SIZE}&offset=${offsetForPage(page)}`;
}

// ─── Tableau de bord ─────────────────────────────────────────────────

export function getDashboard(correlationId: string): Promise<PortalDashboard> {
  return fetchPortal('/dashboard', portalDashboardSchema, correlationId);
}

// ─── Profil ──────────────────────────────────────────────────────────

export function getProfile(correlationId: string): Promise<PortalProfile> {
  return fetchPortal('/me', portalProfileSchema, correlationId);
}

// ─── Devis ───────────────────────────────────────────────────────────

export function listQuotes(
  page: number, correlationId: string,
): Promise<PortalList<PortalQuote>> {
  return fetchPortal(
    listPath('quotes', page), portalListSchema(portalQuoteSchema), correlationId,
  );
}

export function getQuote(
  reference: string, correlationId: string,
): Promise<PortalQuoteDetail> {
  return fetchPortal(
    `/quotes/${encodeReference(reference)}`, portalQuoteDetailSchema, correlationId,
  );
}

// ─── Sourcing ────────────────────────────────────────────────────────

export function listSourcing(
  page: number, correlationId: string,
): Promise<PortalList<PortalSourcingRequest>> {
  return fetchPortal(
    listPath('sourcing', page),
    portalListSchema(portalSourcingRequestSchema),
    correlationId,
  );
}

export function getSourcing(
  reference: string, correlationId: string,
): Promise<PortalSourcingDetail> {
  return fetchPortal(
    `/sourcing/${encodeReference(reference)}`,
    portalSourcingDetailSchema,
    correlationId,
  );
}

// ─── Trading ─────────────────────────────────────────────────────────

export function listTrades(
  page: number, correlationId: string,
): Promise<PortalList<PortalTrade>> {
  return fetchPortal(
    listPath('trades', page), portalListSchema(portalTradeSchema), correlationId,
  );
}

export function getTrade(
  reference: string, correlationId: string,
): Promise<PortalTradeDetail> {
  return fetchPortal(
    `/trades/${encodeReference(reference)}`, portalTradeDetailSchema, correlationId,
  );
}

// ─── Expéditions ─────────────────────────────────────────────────────

export function listShipments(
  page: number, correlationId: string,
): Promise<PortalList<PortalShipment>> {
  return fetchPortal(
    listPath('shipments', page),
    portalListSchema(portalShipmentSchema),
    correlationId,
  );
}

export function getShipment(
  reference: string, correlationId: string,
): Promise<PortalShipmentDetail> {
  return fetchPortal(
    `/shipments/${encodeReference(reference)}`,
    portalShipmentDetailSchema,
    correlationId,
  );
}

// ─── Documents ───────────────────────────────────────────────────────

export function listDocuments(
  page: number, correlationId: string,
): Promise<PortalList<PortalDocument>> {
  return fetchPortal(
    listPath('documents', page),
    portalListSchema(portalDocumentSchema),
    correlationId,
  );
}

/**
 * Extrait l'identifiant Odoo de la référence publique `DOC-<id>`.
 *
 * Cet identifiant ne confère aucun droit : il désigne une ligne que la record
 * rule doit de toute façon laisser passer, et le contrôleur Odoo refait le
 * contrôle au téléchargement. Il n'est donc pas un secret — simplement la
 * poignée par laquelle on demande le fichier.
 *
 * `null` pour toute forme inattendue, ce qui produira un 404 chez l'appelant.
 */
export function documentIdFromReference(reference: string): number | null {
  const match = /^DOC-(\d{1,12})$/.exec(reference);
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/** Le fichier lui-même, sous la session du client. */
export async function downloadDocument(
  reference: string, correlationId: string,
): Promise<{ body: ArrayBuffer; filename: string }> {
  const id = documentIdFromReference(reference);
  if (id === null) {
    throw new PortalGatewayError('not_found', 'malformed document reference', 404);
  }
  const session = await readPortalSession();
  if (!session) {
    throw new PortalGatewayError('unauthenticated', 'no portal session');
  }
  return gateway.download(
    `/documents/${id}/download`, session.odooSessionId, correlationId,
  );
}
