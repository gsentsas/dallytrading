/**
 * Les référentiels publics, relayés au navigateur.
 *
 * `GET /api/references/<kind>?q=<argument>`
 *
 * ## Pourquoi le navigateur ne parle pas à Odoo
 *
 * Interroger l'ERP directement supposerait de publier une clé d'API dans la
 * page. Le BFF garde la clé et relaie la réponse, comme pour le catalogue et
 * la boutique : le navigateur ne connaît qu'une adresse de notre origine.
 *
 * ## Ce que cette route peut renvoyer
 *
 * Quatre listes, et rien d'autre : pays, subdivisions, lieux desservis,
 * incoterms. Le `kind` est validé contre une table close avant tout appel — il
 * ne sert jamais à composer un chemin. Un `kind` inconnu est un 404, pas une
 * requête transmise à l'ERP.
 *
 * Aucune de ces listes ne contient de transporteur, de compagnie, de navire,
 * d'itinéraire ni de prix. Ces éléments relèvent de la qualification
 * commerciale, et le schéma les rejetterait s'ils apparaissaient.
 *
 * ## Le cache
 *
 * Ces listes sont identiques pour tout le monde et changent rarement : cinq
 * minutes de cache partagé épargnent à l'ERP autant d'appels qu'il y a de
 * visiteurs. Une erreur, elle, n'est jamais mise en cache — la panne d'une
 * minute ne doit pas durer cinq.
 */

import { NextResponse } from 'next/server';

import { logger, newCorrelationId } from '@/lib/logger';
import { REFERENCE_KINDS, isReferenceKind } from '@/lib/references/dto';
import { getOdooGateway } from '@/services/odoo';

const CACHE_LISTE = 'public, max-age=300';

/** Longueur maximale de l'argument : un code pays, un mode, rien de plus. */
const ARGUMENT_MAX = 40;

export async function GET(
  request: Request,
  context: { params: Promise<{ kind: string }> },
): Promise<NextResponse> {
  const { kind } = await context.params;
  const correlationId = newCorrelationId();

  if (!isReferenceKind(kind)) {
    return NextResponse.json(
      { error: 'not_found' },
      { status: 404, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  const argument = new URL(request.url).searchParams
    .get('q')
    ?.trim()
    .slice(0, ARGUMENT_MAX);

  try {
    const brutes = await getOdooGateway().listReferences(
      kind,
      argument || undefined,
      correlationId,
    );

    // Le schéma est la seconde barrière : Odoo décide ce qu'il publie, la
    // vitrine décide ce qu'elle accepte. Une entrée non conforme est écartée
    // plutôt que de faire échouer la liste entière — une subdivision malformée
    // ne doit pas empêcher de choisir les treize autres.
    const schema = REFERENCE_KINDS[kind];
    const entrees = brutes.flatMap((brute) => {
      const resultat = schema.safeParse(brute);
      return resultat.success ? [resultat.data] : [];
    });

    if (entrees.length !== brutes.length) {
      logger.warn('references.rejected', {
        correlationId,
        kind,
        rejected: brutes.length - entrees.length,
      });
    }

    return NextResponse.json(
      { [kind]: entrees },
      { status: 200, headers: { 'Cache-Control': CACHE_LISTE } },
    );
  } catch (error) {
    logger.error('references.failed', {
      correlationId,
      kind,
      message: error instanceof Error ? error.message : 'unknown',
    });
    // Une liste vide plutôt qu'une erreur : le formulaire reste utilisable,
    // les villes restent saisissables à la main, et le visiteur n'a pas à
    // comprendre qu'un ERP est en panne.
    return NextResponse.json(
      { [kind]: [] },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
