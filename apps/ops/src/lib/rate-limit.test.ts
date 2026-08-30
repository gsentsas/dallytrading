import { beforeEach, describe, expect, it } from 'vitest';

import {
  OPS_LOGIN_IP,
  OPS_RECHERCHE_IP,
  OPS_RECHERCHE_SESSION,
  cleRechercheIp,
  cleRechercheSession,
  OPS_LOGIN_UTILISATEUR,
  checkRateLimit,
  cleLoginIp,
  cleLoginUtilisateur,
  clearRateLimitKey,
  getClientIp,
  peekRateLimit,
  resetRateLimits,
} from '@/lib/rate-limit';

beforeEach(() => {
  resetRateLimits();
});

describe('budgets de connexion', () => {
  it('laisse passer jusqu’à la limite puis refuse', () => {
    for (let essai = 0; essai < OPS_LOGIN_UTILISATEUR.limite; essai += 1) {
      expect(
        checkRateLimit('ops:login:user:gilles', OPS_LOGIN_UTILISATEUR.limite, 60_000).allowed,
      ).toBe(true);
    }
    const refus = checkRateLimit('ops:login:user:gilles', OPS_LOGIN_UTILISATEUR.limite, 60_000);
    expect(refus.allowed).toBe(false);
    expect(refus.retryAfterSeconds).toBeGreaterThan(0);
  });

  it('borne plus sévèrement un compte qu’une adresse', () => {
    // Un poste partagé sert plusieurs opérateurs ; un compte martelé est un
    // compte attaqué.
    expect(OPS_LOGIN_UTILISATEUR.limite).toBeLessThan(OPS_LOGIN_IP.limite);
  });

  it('sépare le budget d’un compte de celui d’un autre', () => {
    for (let essai = 0; essai <= OPS_LOGIN_UTILISATEUR.limite; essai += 1) {
      checkRateLimit(cleLoginUtilisateur('gilles'), OPS_LOGIN_UTILISATEUR.limite, 60_000);
    }
    expect(
      checkRateLimit(cleLoginUtilisateur('alain'), OPS_LOGIN_UTILISATEUR.limite, 60_000).allowed,
    ).toBe(true);
  });
});

describe('consultation sans consommation', () => {
  it('ne fait pas monter le compteur', () => {
    for (let essai = 0; essai < 20; essai += 1) peekRateLimit('k', 3);
    // Sinon un refus ferait lui-même monter le compteur, et la fenêtre de
    // cinq minutes se prolongerait sous le martèlement qu'elle doit arrêter.
    expect(checkRateLimit('k', 3, 60_000).allowed).toBe(true);
  });

  it('signale un budget déjà épuisé', () => {
    for (let essai = 0; essai < 3; essai += 1) checkRateLimit('k', 3, 60_000);
    expect(peekRateLimit('k', 3).allowed).toBe(false);
  });

  it('repart à neuf après effacement de la clé', () => {
    for (let essai = 0; essai < 3; essai += 1) checkRateLimit('k', 3, 60_000);
    clearRateLimitKey('k');
    expect(peekRateLimit('k', 3).allowed).toBe(true);
  });
});

describe('forme des clés', () => {
  it('préfixe les clés d’adresse et de compte séparément', () => {
    expect(cleLoginIp('10.0.0.1')).toBe('ops:login:ip:10.0.0.1');
    expect(cleLoginUtilisateur('gilles')).toBe('ops:login:user:gilles');
  });

  it('ne partage aucune clé avec le portail client', () => {
    // Un client qui martèle le portail ne doit pas verrouiller un logisticien.
    expect(cleLoginIp('10.0.0.1').startsWith('ops:')).toBe(true);
    expect(cleLoginUtilisateur('gilles').startsWith('ops:')).toBe(true);
  });

  it('normalise la casse et les espaces du compte', () => {
    // Sans cela, la limite par compte se contourne en changeant la casse.
    expect(cleLoginUtilisateur('  GiLLes ')).toBe(cleLoginUtilisateur('gilles'));
  });
});

describe('budgets de la recherche client', () => {
  it('sépare la session de l’adresse', () => {
    expect(cleRechercheSession('sX').startsWith('ops:customers:session:')).toBe(true);
    expect(cleRechercheIp('10.0.0.1')).toBe('ops:customers:ip:10.0.0.1');
  });

  it('ne recopie jamais l’identifiant de session dans la clé', () => {
    // Un identifiant de session vaut un mot de passe : il ne doit apparaître
    // ni dans une table en mémoire, ni dans un message de journal.
    const cle = cleRechercheSession('session-odoo-tres-reconnaissable');
    expect(cle).not.toContain('session-odoo-tres-reconnaissable');
    expect(cle).toMatch(/^ops:customers:session:[0-9a-f]{32}$/);
  });

  it('donne la même clé pour la même session', () => {
    expect(cleRechercheSession('sX')).toBe(cleRechercheSession('sX'));
  });

  it('donne des clés différentes pour deux sessions', () => {
    expect(cleRechercheSession('sX')).not.toBe(cleRechercheSession('sY'));
  });

  it('borne la session plus serré que l’adresse', () => {
    // Tout un entrepôt sort par la même adresse : une limite qui ne
    // connaîtrait que l'IP frapperait l'équipe pour l'imprudence d'un poste.
    expect(OPS_RECHERCHE_SESSION.limite).toBeLessThan(OPS_RECHERCHE_IP.limite);
  });

  it('ne gêne pas une réception normale', () => {
    // Une réception, c'est une recherche, parfois deux.
    expect(OPS_RECHERCHE_SESSION.limite).toBeGreaterThanOrEqual(60);
  });

  it('ne partage aucune clé avec la connexion', () => {
    expect(cleRechercheIp('10.0.0.1')).not.toBe(cleLoginIp('10.0.0.1'));
  });
});

describe('adresse du client', () => {
  it('retient la première entrée de X-Forwarded-For', () => {
    const enTetes = new Headers({ 'x-forwarded-for': '203.0.113.7, 10.0.0.1' });
    expect(getClientIp(enTetes)).toBe('203.0.113.7');
  });

  it('retombe sur « unknown » en l’absence d’en-tête', () => {
    expect(getClientIp(new Headers())).toBe('unknown');
  });
});
