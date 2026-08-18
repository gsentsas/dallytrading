/**
 * L'image d'un produit publié, servie au navigateur.
 *
 * `GET /api/shop/products/<slug>/image?v=<empreinte>&size=card|detail`
 *
 * ## Pourquoi le navigateur ne parle pas à Odoo
 *
 * Servir l'image directement depuis Odoo obligerait à donner au navigateur une
 * clé `shop:read` — c'est-à-dire à publier la clé — ou à ouvrir une route Odoo
 * sans authentification. Le BFF garde donc la clé et relaie les octets, comme
 * pour le catalogue et le panier. Le navigateur ne connaît qu'une adresse de
 * notre propre origine.
 *
 * ## Le cache ne récompense que ce qui existe
 *
 * Une image publiée est identique pour tous et son URL porte l'empreinte de son
 * contenu : elle est donc déclarée immuable et gardée un an. Un 404, lui, est
 * `no-store` — un produit non publié aujourd'hui peut l'être demain, et un
 * refus mis en cache par un intermédiaire survivrait à la publication.
 *
 * ## Ce que la réponse ne dit jamais
 *
 * Ni pourquoi c'est absent, ni ce qu'Odoo a répondu, ni où il se trouve. Un
 * produit inconnu, un produit non publié, un produit sans image et une image de
 * type refusé produisent le même 404, au même octet près.
 */

import { NextResponse } from 'next/server';

import { logger, newCorrelationId } from '@/lib/logger';
import {
  SHOP_IMAGE_SIZE_DEFAULT,
  isShopImageSize,
  type ShopImageSize,
} from '@/lib/shop/image';
import { ShopGatewayError, ShopOdooGateway } from '@/lib/shop/odoo-shop';

/**
 * Pas de `dynamic = 'force-dynamic'`, et c'est une correction.
 *
 * Cette route l'a porté, et **Next posait alors `Cache-Control: no-store` sur
 * la réponse**, écrasant l'en-tête du gestionnaire. Mesuré en Playwright : une
 * image servie en 200 repartait en `no-store`, si bien que le navigateur la
 * retéléchargeait à chaque affichage. Toute la stratégie de jeton de contenu —
 * une URL qui change quand l'image change, donc un cache d'un an — était
 * annulée sans qu'aucun test de balisage puisse le voir.
 *
 * La route reste dynamique de toute façon : elle lit `request.url`, ce qui
 * suffit à interdire toute mise en cache du rendu par le framework. La
 * dépublication prend donc effet immédiatement, comme avant.
 */

/** Un an, parce que l'URL change dès que l'image change. */
const CACHE_IMAGE_VERSIONNEE = 'public, max-age=31536000, immutable';

/**
 * Sans jeton de version, l'URL ne suit plus le contenu : le cache doit être
 * court, sinon une image remplacée resterait affichée pendant des mois.
 */
const CACHE_IMAGE_NUE = 'public, max-age=300';

const REFUS = {
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
} as const;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const { reference } = await params;
  const correlationId = newCorrelationId();
  const url = new URL(request.url);

  /**
   * Une taille hors liste retombe sur la taille par défaut plutôt que d'être
   * refusée. Un paramètre d'URL est du texte que n'importe qui compose : en
   * faire une erreur ajouterait une surface de refus sans rien protéger, alors
   * que la liste fermée a déjà tout fait — aucune valeur inédite ne provoque de
   * redimensionnement.
   */
  const brut = url.searchParams.get('size');
  const size: ShopImageSize = isShopImageSize(brut) ? brut : SHOP_IMAGE_SIZE_DEFAULT;
  const versionnee = Boolean(url.searchParams.get('v'));

  /**
   * Le jeton de galerie, transmis sans être interprété.
   *
   * Il est borné en longueur avant de partir : une valeur démesurée n'irait
   * nulle part côté Odoo, mais elle voyagerait dans une URL et dans les
   * journaux d'accès. Le format exact n'est pas validé ici — le seul juge est
   * la comparaison faite côté Odoo aux empreintes du produit autorisé, et
   * dupliquer ce jugement créerait deux vérités.
   */
  const brutGalerie = url.searchParams.get('gallery');
  const galleryToken =
    brutGalerie && brutGalerie.length <= 64 ? brutGalerie : undefined;

  try {
    const { bytes, contentType } = await new ShopOdooGateway().getProductImage(
      reference,
      size,
      correlationId,
      galleryToken,
    );

    return new NextResponse(bytes, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(bytes.byteLength),
        'Content-Disposition': 'inline',
        'Cache-Control': versionnee ? CACHE_IMAGE_VERSIONNEE : CACHE_IMAGE_NUE,
        // Le type a été vérifié contre une liste blanche en amont ; `nosniff`
        // interdit en plus au navigateur de deviner autre chose à partir des
        // octets.
        'X-Content-Type-Options': 'nosniff',
      },
    });
  } catch (error) {
    const code = error instanceof ShopGatewayError ? error.code : 'unknown';

    // Absent et non publié sont le même cas, et `not_open` le rejoint : une
    // boutique fermée n'a pas d'image à montrer, et le dire distinguerait cet
    // état sur une route qui n'a pas à le faire — la page `/boutique` s'en
    // charge déjà, avec les mots qu'il faut.
    /*
     * `invalid_response` rejoint le 404, et ce n'est pas un détail.
     *
     * Il désigne une image d'un type refusé — un SVG déposé dans le
     * back-office, par exemple. C'est un problème de **contenu**, pas de
     * disponibilité : du point de vue du visiteur, il n'y a pas d'image, et le
     * cahier des charges le range explicitement avec « inconnu » et « non
     * publié ». Le refus reste donc indiscernable, et le motif réel n'existe
     * que dans les journaux d'Odoo, qui le consigne en avertissement.
     */
    if (code === 'not_found' || code === 'not_open' || code === 'invalid_response') {
      return refus();
    }

    /*
     * Une panne de l'ERP n'est pas une absence de produit.
     *
     * Cette route rendait 404 pour tout, panne comprise. Mesuré en E2E : sous
     * charge, l'Odoo de test refusait quelques appels, et une photo bien
     * présente devenait un 404 — c'est-à-dire, du point de vue de l'appelant,
     * une photo qui n'existe pas. Le symptôme était une image manquante et une
     * suite rouge par intermittence, sans rien qui désigne la vraie cause.
     *
     * 502 ne rouvre pas la porte que le 404 unique ferme : « inconnu » et « non
     * publié » restent indiscernables, tous deux en 404. Ce qui devient
     * distinguable, c'est l'état de l'ERP — qui ne dit rien sur l'existence
     * d'un produit, et que l'exploitant a besoin de voir.
     */
    logger.error('Shop image unavailable', { correlationId, code });
    return new NextResponse(null, { status: 502, headers: REFUS });
  }
}

/**
 * Le refus, unique.
 *
 * Un corps vide : un message, même générique, serait une différence de plus
 * entre deux réponses qui doivent être indiscernables. Le statut suffit, et
 * c'est une image qu'on attendait — aucun code appelant ne lit ce corps.
 */
function refus(): NextResponse {
  return new NextResponse(null, { status: 404, headers: REFUS });
}
