/**
 * Le proxy redirige, il ne protège pas.
 *
 * Ces tests le vérifient dans les deux sens : il redirige un visiteur sans
 * cookie, ET il laisse passer un cookie manifestement bidon. La seconde
 * assertion est la plus importante — elle documente noir sur blanc que la
 * protection réelle est ailleurs, dans `requirePortalSession()`.
 */

import { describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';

import { proxy, config } from './proxy';
import { PORTAL_COOKIE } from './lib/portal/session';

function request(path: string, cookie?: string): NextRequest {
  const nextRequest = new NextRequest(new URL(`https://dallytrading.com${path}`));
  if (cookie !== undefined) {
    nextRequest.cookies.set(PORTAL_COOKIE, cookie);
  }
  return nextRequest;
}

describe('proxy', () => {
  it('redirige vers /connexion sans cookie', () => {
    const response = proxy(request('/espace-client'));
    const location = new URL(response.headers.get('location') as string);
    expect(location.pathname).toBe('/connexion');
    expect(location.searchParams.get('next')).toBe('/espace-client');
  });

  it('conserve le chemin demandé pour y revenir après connexion', () => {
    const response = proxy(request('/espace-client/expeditions'));
    const location = new URL(response.headers.get('location') as string);
    expect(location.searchParams.get('next')).toBe('/espace-client/expeditions');
  });

  it('ne transmet jamais une URL absolue dans `next`', () => {
    const response = proxy(request('/espace-client/devis'));
    const next = new URL(response.headers.get('location') as string)
      .searchParams.get('next');
    expect(next?.startsWith('/')).toBe(true);
    expect(next).not.toContain('://');
  });

  it('laisse passer un cookie sans le vérifier — c’est assumé', () => {
    // Un cookie arbitraire suffit à passer le proxy. C’est acceptable seulement
    // parce que la page appelle ensuite Odoo et se fait refuser.
    const response = proxy(request('/espace-client', 'cookie-totalement-forge'));
    expect(response.headers.get('location')).toBeNull();
  });

  it('redirige aussi sur un cookie vide', () => {
    const response = proxy(request('/espace-client', ''));
    expect(response.headers.get('location')).toContain('/connexion');
  });

  it('ne s’applique qu’au portail', () => {
    // Étendre le matcher aux pages publiques les rendrait dynamiques et
    // casserait leur rendu statique.
    expect(config.matcher).toEqual(['/espace-client/:path*']);
  });
});
