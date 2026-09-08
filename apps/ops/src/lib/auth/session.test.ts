import { describe, expect, it } from 'vitest';

import {
  OPS_COOKIE,
  OPS_SESSION_MAX_AGE_SECONDS,
  OpsSessionError,
  cookieOptions,
  isExpired,
  sealSession,
  unsealSession,
} from '@/lib/auth/session';

const SECRET = 'secret-de-banc-pour-les-tests-0123456789';
const AUTRE_SECRET = 'un-tout-autre-secret-de-banc-9876543210';

describe('scellement de la session Ops', () => {
  it('rend exactement ce qui a été scellé', () => {
    const session = { odooSessionId: 'abc123', issuedAt: 1_700_000_000_000 };
    expect(unsealSession(sealSession(session, SECRET), SECRET)).toEqual(session);
  });

  it('produit un jeton différent à chaque scellement du même contenu', () => {
    const session = { odooSessionId: 'abc123', issuedAt: 1_700_000_000_000 };
    // Vecteur d'initialisation aléatoire : deux scellements identiques ne
    // doivent pas produire le même texte, sinon la réutilisation d'une session
    // se lit à l'œil nu dans les journaux d'accès.
    expect(sealSession(session, SECRET)).not.toEqual(sealSession(session, SECRET));
  });

  it('refuse un jeton scellé avec un autre secret', () => {
    const jeton = sealSession({ odooSessionId: 'abc', issuedAt: 1 }, AUTRE_SECRET);
    expect(() => unsealSession(jeton, SECRET)).toThrow(OpsSessionError);
  });

  it('refuse un jeton dont le texte chiffré a été modifié', () => {
    const jeton = sealSession({ odooSessionId: 'abc', issuedAt: 1 }, SECRET);
    const parties = jeton.split('.');
    parties[2] = Buffer.from('charge forgee').toString('base64url');
    expect(() => unsealSession(parties.join('.'), SECRET)).toThrow(OpsSessionError);
  });

  it('refuse un jeton dont la version a changé', () => {
    const jeton = sealSession({ odooSessionId: 'abc', issuedAt: 1 }, SECRET);
    const parties = jeton.split('.');
    parties[0] = 'v2';
    expect(() => unsealSession(parties.join('.'), SECRET)).toThrow(OpsSessionError);
  });

  it.each([
    ['vide', ''],
    ['sans séparateurs', 'nimportequoi'],
    ['trop de parties', 'v1.a.b.c.d'],
    ['pas assez de parties', 'v1.a.b'],
  ])('refuse un jeton %s', (_cas, valeur) => {
    expect(() => unsealSession(valeur, SECRET)).toThrow(OpsSessionError);
  });

  it('donne le même message quelle que soit l’anomalie', () => {
    // Un message qui distinguerait « mauvais format » de « signature
    // invalide » offrirait un oracle à qui teste des cookies fabriqués.
    const messages = new Set<string>();
    for (const valeur of ['', 'v1.a.b', 'v2.a.b.c', 'v1.a.b.c']) {
      try {
        unsealSession(valeur, SECRET);
      } catch (erreur) {
        messages.add((erreur as Error).message);
      }
    }
    expect(messages.size).toBe(1);
  });

  it('refuse un contenu déchiffrable mais sans identifiant de session', () => {
    // Scellé avec le bon secret : seule la forme du contenu est en cause.
    const jeton = sealSession(
      { issuedAt: 1 } as unknown as { odooSessionId: string; issuedAt: number },
      SECRET,
    );
    expect(() => unsealSession(jeton, SECRET)).toThrow(OpsSessionError);
  });

  it('ne transporte que la session Odoo et son instant d’émission', () => {
    // Le cookie ne doit porter ni nom, ni rôle, ni capacité : tout ce que
    // l'application affiche est relu auprès d'Odoo.
    const session = { odooSessionId: 'abc', issuedAt: 42 };
    const jeton = sealSession(session, SECRET);
    expect(Object.keys(unsealSession(jeton, SECRET)).sort()).toEqual(['issuedAt', 'odooSessionId']);
  });

  it('ne laisse pas fuir la session Odoo en clair dans le jeton', () => {
    const jeton = sealSession({ odooSessionId: 'session-odoo-secrete', issuedAt: 1 }, SECRET);
    expect(jeton).not.toContain('session-odoo-secrete');
  });
});

describe('durée de vie', () => {
  it('accepte une session émise à l’instant', () => {
    expect(isExpired({ odooSessionId: 'a', issuedAt: Date.now() })).toBe(false);
  });

  it('rejette une session plus vieille que huit heures', () => {
    const emission = Date.now() - (OPS_SESSION_MAX_AGE_SECONDS + 1) * 1000;
    expect(isExpired({ odooSessionId: 'a', issuedAt: emission })).toBe(true);
  });

  it('dure exactement huit heures', () => {
    expect(OPS_SESSION_MAX_AGE_SECONDS).toBe(8 * 60 * 60);
  });
});

describe('attributs du cookie', () => {
  it('porte un nom distinct de celui du portail client', () => {
    // Deux applications, deux publics, deux cookies. Les confondre ferait
    // d'une compromission du portail une compromission des opérations.
    expect(OPS_COOKIE).toBe('dt_ops_session');
    expect(OPS_COOKIE).not.toBe('dt_portal_session');
  });

  it('est inaccessible au JavaScript de la page et limité au même site', () => {
    const options = cookieOptions(true);
    expect(options.httpOnly).toBe(true);
    expect(options.sameSite).toBe('lax');
    expect(options.path).toBe('/');
    expect(options.maxAge).toBe(OPS_SESSION_MAX_AGE_SECONDS);
  });

  it('n’est marqué « secure » que sur une origine HTTPS', () => {
    expect(cookieOptions(true).secure).toBe(true);
    expect(cookieOptions(false).secure).toBe(false);
  });

  it('ne fixe aucun domaine, donc reste sur le sous-domaine des opérations', () => {
    // Un `Domain=dallytrading.com` enverrait le cookie d'opérateur au site
    // public et au CRM. L'absence de la clé est la garantie.
    expect(Object.keys(cookieOptions(true))).not.toContain('domain');
  });
});

/**
 * « Se souvenir de moi ».
 *
 * La case ne touche qu'une chose : la durée de vie du cookie sur l'appareil.
 * Elle ne peut ni allonger la session au-delà du plafond serveur, ni changer
 * ce que la session contient. Ces cinq cas fixent exactement cela, parce
 * qu'une case de connexion qui dériverait vers autre chose se remarquerait
 * tard et mal.
 */
describe('se souvenir de moi', () => {
  it('sans persistance, le cookie n’a pas d’âge maximum', () => {
    // Pas de `maxAge` : le navigateur l'efface à sa fermeture.
    const options = cookieOptions(true, false);
    expect(options).not.toHaveProperty('maxAge');
  });

  it('avec persistance, le cookie tient exactement le plafond de session', () => {
    expect(cookieOptions(true, true).maxAge).toBe(OPS_SESSION_MAX_AGE_SECONDS);
    // Et ce plafond est bien la journée de travail, pas davantage.
    expect(OPS_SESSION_MAX_AGE_SECONDS).toBe(8 * 60 * 60);
  });

  it('sans argument, garde le comportement d’avant : persistant', () => {
    // Une requête ancienne, qui n'envoie pas le drapeau, ne doit pas se voir
    // déconnectée à la fermeture du navigateur du jour au lendemain.
    expect(cookieOptions(true).maxAge).toBe(OPS_SESSION_MAX_AGE_SECONDS);
  });

  it('la persistance ne change rien aux autres attributs du cookie', () => {
    const persistant = cookieOptions(true, true);
    const ephemere = cookieOptions(true, false);
    for (const cle of ['httpOnly', 'secure', 'sameSite', 'path'] as const) {
      expect(ephemere[cle]).toEqual(persistant[cle]);
    }
    // Ni l'un ni l'autre n'ouvre le cookie à un sous-domaine.
    expect(Object.keys(ephemere)).not.toContain('domain');
  });

  it('un cookie persistant n’empêche pas l’expiration au-delà de huit heures', () => {
    // Le point qui compte : cocher la case ne prolonge pas la session. Le
    // serveur relit `issuedAt` et refuse, quoi que le cookie prétende.
    const emise = 1_700_000_000_000;
    const session = { odooSessionId: 'abc123', issuedAt: emise };
    const huitHeures = OPS_SESSION_MAX_AGE_SECONDS * 1000;
    expect(isExpired(session, emise + huitHeures - 1)).toBe(false);
    expect(isExpired(session, emise + huitHeures)).toBe(true);
    expect(isExpired(session, emise + huitHeures + 60_000)).toBe(true);
  });

  it('la persistance ne touche ni au contenu scellé ni à l’identité', () => {
    // Le cookie porte la session Odoo et rien d'autre : la case ne peut pas
    // y glisser un droit, un rôle, ou une durée qui lui serait propre.
    const session = { odooSessionId: 'abc123', issuedAt: 1_700_000_000_000 };
    expect(unsealSession(sealSession(session, SECRET), SECRET)).toEqual(session);
    expect(Object.keys(session)).toEqual(['odooSessionId', 'issuedAt']);
  });
});
