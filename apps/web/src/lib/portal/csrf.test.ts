import { describe, expect, it } from 'vitest';

import { checkOrigin, safeNextPath } from './csrf';

const SITE = 'https://dallytrading.com';

function headers(values: Record<string, string>): Headers {
  return new Headers(values);
}

describe('checkOrigin', () => {
  it('accepte notre propre origine', () => {
    expect(checkOrigin(headers({ origin: SITE }), SITE)).toEqual({ ok: true });
  });

  it('tolère un slash final et une casse différente', () => {
    expect(
      checkOrigin(headers({ origin: 'HTTPS://DallyTrading.com/' }), SITE).ok,
    ).toBe(true);
  });

  it('refuse une origine tierce', () => {
    expect(checkOrigin(headers({ origin: 'https://evil.example' }), SITE)).toEqual({
      ok: false,
      reason: 'mismatch',
    });
  });

  it('refuse un sous-domaine, même du bon domaine', () => {
    // Un sous-domaine peut appartenir à un service tiers ou avoir été pris par
    // un enregistrement DNS oublié : ce n’est pas la même origine.
    expect(checkOrigin(headers({ origin: 'https://evil.dallytrading.com' }), SITE).ok)
      .toBe(false);
  });

  it('refuse le même hôte en http', () => {
    expect(checkOrigin(headers({ origin: 'http://dallytrading.com' }), SITE).ok).toBe(false);
  });

  it('refuse une requête sans Origin ni Referer', () => {
    expect(checkOrigin(headers({}), SITE)).toEqual({ ok: false, reason: 'missing' });
  });

  it('refuse un Referer seul quand Origin est absent', () => {
    expect(
      checkOrigin(headers({ referer: `${SITE}/connexion?next=/espace-client` }), SITE).ok,
    ).toBe(false);
  });

  it('refuse un Referer illisible', () => {
    expect(checkOrigin(headers({ referer: 'pas-une-url' }), SITE).ok).toBe(false);
  });

  it('privilégie Origin sur Referer', () => {
    // Origin fait foi : un Referer légitime ne doit pas racheter une origine tierce.
    expect(
      checkOrigin(
        headers({ origin: 'https://evil.example', referer: `${SITE}/connexion` }),
        SITE,
      ).ok,
    ).toBe(false);
  });
});

describe('safeNextPath', () => {
  it('conserve une destination interne du portail', () => {
    expect(safeNextPath('/espace-client')).toBe('/espace-client');
    expect(safeNextPath('/espace-client/devis')).toBe('/espace-client/devis');
  });

  const rejected = [
    ['absent', undefined],
    ['vide', ''],
    ['absolu http', 'https://evil.example/phish'],
    ['protocole-relatif', '//evil.example'],
    ['antislash', '/\\evil.example'],
    ['schéma javascript', 'javascript:alert(1)'],
    ['injection de saut de ligne', '/espace-client\r\nSet-Cookie: a=b'],
    ['hors du portail', '/contact'],
    ['racine', '/'],
    ['préfixe trompeur', '/espace-clientele'],
  ] as const;

  for (const [label, value] of rejected) {
    it(`retombe sur /espace-client : ${label}`, () => {
      expect(safeNextPath(value)).toBe('/espace-client');
    });
  }
});
