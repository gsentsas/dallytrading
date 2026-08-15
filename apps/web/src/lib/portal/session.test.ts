import { describe, expect, it } from 'vitest';

import {
  PORTAL_COOKIE,
  PORTAL_SESSION_MAX_AGE_SECONDS,
  PortalSessionError,
  cookieOptions,
  isExpired,
  sealSession,
  unsealSession,
} from './session';

const SECRET = 'test-secret-for-unit-tests-only-not-a-real-value-0123456789';
const OTHER_SECRET = 'a-different-secret-of-sufficient-length-9876543210abcdef';

function session(overrides: Partial<{ odooSessionId: string; issuedAt: number }> = {}) {
  return {
    odooSessionId: 'abcdefghijklmnop1234',
    issuedAt: Math.floor(Date.now() / 1000),
    ...overrides,
  };
}

describe('portal session cookie', () => {
  it('fait l’aller-retour sans perte', () => {
    const original = session();
    expect(unsealSession(sealSession(original, SECRET), SECRET)).toEqual(original);
  });

  it('produit un scellé différent à chaque appel (IV aléatoire)', () => {
    const original = session();
    expect(sealSession(original, SECRET)).not.toBe(sealSession(original, SECRET));
  });

  it('n’expose pas l’identifiant de session en clair', () => {
    const sealed = sealSession(session({ odooSessionId: 'SECRETSESSION123456' }), SECRET);
    expect(sealed).not.toContain('SECRETSESSION123456');
    expect(Buffer.from(sealed).toString('utf8')).not.toContain('odooSessionId');
  });

  it('refuse un cookie scellé avec un autre secret', () => {
    const sealed = sealSession(session(), OTHER_SECRET);
    expect(() => unsealSession(sealed, SECRET)).toThrow(PortalSessionError);
  });

  describe('altération', () => {
    // Chaque variante doit produire la MÊME erreur : distinguer « altéré » de
    // « expiré » donnerait un signal à qui teste des variantes.
    const cases: Array<[string, (sealed: string) => string]> = [
      ['version inconnue', (s) => `v2${s.slice(2)}`],
      ['structure tronquée', (s) => s.split('.').slice(0, 3).join('.')],
      ['segment surnuméraire', (s) => `${s}.extra`],
      ['chiffré modifié', (s) => {
        const parts = s.split('.');
        const data = Buffer.from(parts[2] as string, 'base64url');
        data[0] = (data[0] ?? 0) ^ 0xff;
        parts[2] = data.toString('base64url');
        return parts.join('.');
      }],
      ['tag modifié', (s) => {
        const parts = s.split('.');
        const tag = Buffer.from(parts[3] as string, 'base64url');
        tag[0] = (tag[0] ?? 0) ^ 0xff;
        parts[3] = tag.toString('base64url');
        return parts.join('.');
      }],
      ['IV tronqué', (s) => {
        const parts = s.split('.');
        parts[1] = Buffer.alloc(4).toString('base64url');
        return parts.join('.');
      }],
      ['valeur vide', () => ''],
      ['valeur arbitraire', () => 'n’importe quoi'],
    ];

    for (const [label, mutate] of cases) {
      it(`rejette : ${label}`, () => {
        const sealed = sealSession(session(), SECRET);
        expect(() => unsealSession(mutate(sealed), SECRET)).toThrow(PortalSessionError);
      });
    }
  });

  it('rejette un paquet valide mais sans identifiant de session', () => {
    // Chiffré avec la bonne clé, donc le tag est correct : seul le contrôle de
    // structure peut l’arrêter.
    const sealed = sealSession(
      { odooSessionId: '', issuedAt: 1 } as never,
      SECRET,
    );
    expect(() => unsealSession(sealed, SECRET)).toThrow(PortalSessionError);
  });
});

describe('isExpired', () => {
  const now = 1_800_000_000_000;

  it('accepte une session fraîche', () => {
    expect(isExpired(session({ issuedAt: Math.floor(now / 1000) }), now)).toBe(false);
  });

  it('refuse une session au-delà du plafond', () => {
    const issuedAt = Math.floor(now / 1000) - PORTAL_SESSION_MAX_AGE_SECONDS - 1;
    expect(isExpired(session({ issuedAt }), now)).toBe(true);
  });

  it('refuse une session émise dans le futur', () => {
    // Une horloge décalée ou un `issuedAt` forgé : dans les deux cas on refuse
    // plutôt que d’accorder une durée de vie plus longue que prévu.
    expect(isExpired(session({ issuedAt: Math.floor(now / 1000) + 60 }), now)).toBe(true);
  });
});

describe('cookieOptions', () => {
  it('est HttpOnly, SameSite=Lax et limité à la racine', () => {
    const options = cookieOptions(true);
    expect(options.httpOnly).toBe(true);
    expect(options.sameSite).toBe('lax');
    expect(options.path).toBe('/');
    expect(options.maxAge).toBe(PORTAL_SESSION_MAX_AGE_SECONDS);
  });

  it('porte Secure en production et pas en développement local', () => {
    expect(cookieOptions(true).secure).toBe(true);
    expect(cookieOptions(false).secure).toBe(false);
  });

  it('n’utilise pas le nom du cookie d’Odoo', () => {
    expect(PORTAL_COOKIE).toBe('dt_portal_session');
    expect(PORTAL_COOKIE).not.toBe('session_id');
  });
});
