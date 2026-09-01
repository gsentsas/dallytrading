import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Les trois capacités que les photos ont demandées à la passerelle.
 *
 * Elles sont additives, et ces tests le vérifient dans les deux sens : ce que
 * les photos gagnent, et ce que le justificatif de caisse et le reçu PDF
 * gardent. Une passerelle partagée ne se modifie pas sur la foi d'une seule
 * fonctionnalité.
 */

import {
  CHAMPS_FICHIER,
  OpsGatewayError,
  opsDelete,
  opsGet,
  opsGetBinaire,
  opsGetDocument,
  opsPost,
  opsPostFichier,
} from '@/lib/auth/odoo-ops';
import { resetOpsEnv } from '@/lib/env';

const SOURCE = readFileSync(
  fileURLToPath(new URL('./odoo-ops.ts', import.meta.url)), 'utf8');

const SESSION = 'session-de-banc';
const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0]);

let appels: Array<{ url: string; init: RequestInit }>;

beforeEach(() => {
  appels = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
  // Les espions posés sur `AbortSignal.prototype` sont globaux : les laisser
  // en place ferait échouer les tests suivants pour une raison sans rapport.
  vi.restoreAllMocks();
  delete process.env.ODOO_TIMEOUT_MS;
  resetOpsEnv();
});

function espionner(reponse: Response | (() => Response | Promise<Response>)) {
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL, init: RequestInit = {}) => {
    appels.push({ url: String(url), init });
    return typeof reponse === 'function' ? reponse() : reponse;
  }));
}

function reponseJson(charge: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(charge), {
    status: 200, headers: { 'content-type': 'application/json' }, ...init,
  });
}

function reponseImage(morceaux: Uint8Array[], type = 'image/jpeg'): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(sortie) {
        for (const morceau of morceaux) sortie.enqueue(morceau);
        sortie.close();
      },
    }),
    { status: 200, headers: { 'content-type': type } },
  );
}

async function toutLire(flux: ReadableStream<Uint8Array>): Promise<number> {
  const lecteur = flux.getReader();
  let total = 0;
  for (;;) {
    const { done, value } = await lecteur.read();
    if (done) break;
    total += value?.byteLength ?? 0;
  }
  return total;
}

describe('T01–T03 · le champ multipart est choisi dans un jeu fermé', () => {
  it('T01 · le justificatif de caisse pose toujours « receipt »', async () => {
    espionner(reponseJson({ success: true, data: { ok: true } }));
    await opsPostFichier(
      'expenses/EXP-1/receipt',
      { nom: 't.jpg', type: 'image/jpeg', contenu: new Blob([JPEG]) },
      { request_uuid: 'u' }, SESSION, 'corr');
    const corps = appels[0]?.init.body as FormData;
    expect(corps.get('receipt')).toBeInstanceOf(File);
    expect(corps.get('photo')).toBeNull();
  });

  it('T02 · la photo pose « photo »', async () => {
    espionner(reponseJson({ success: true, data: { ok: true } }));
    await opsPostFichier(
      'intakes/AIR-1-A001/photos',
      { nom: 'p.jpg', type: 'image/jpeg', contenu: new Blob([JPEG]) },
      { request_uuid: 'u', kind: 'reception' }, SESSION, 'corr', 'photo');
    const corps = appels[0]?.init.body as FormData;
    expect(corps.get('photo')).toBeInstanceOf(File);
    expect(corps.get('receipt')).toBeNull();
  });

  it('T03 · un champ arbitraire est refusé, y compris en contournant le typage',
    async () => {
      espionner(reponseJson({ success: true, data: {} }));
      await expect(opsPostFichier(
        'intakes/AIR-1-A001/photos',
        { nom: 'p.jpg', type: 'image/jpeg', contenu: new Blob([JPEG]) },
        {}, SESSION, 'corr',
        'datas' as unknown as (typeof CHAMPS_FICHIER)[number],
      )).rejects.toThrow(OpsGatewayError);
      expect(appels).toHaveLength(0);
    });

  it('le jeu fermé ne contient que les deux champs attendus', () => {
    expect([...CHAMPS_FICHIER]).toEqual(['receipt', 'photo']);
  });
});

describe('T04–T05 · le retrait', () => {
  it('T04 · émet bien un DELETE, avec la session et le corps', async () => {
    espionner(reponseJson({ success: true, data: { status: 'deleted' } }));
    await opsDelete('intakes/AIR-1-A001/photos/abc-123', { request_uuid: 'u' },
                    SESSION, 'corr');
    expect(appels[0]?.init.method).toBe('DELETE');
    expect(appels[0]?.url).toContain('/api/v1/ops/intakes/AIR-1-A001/photos/abc-123');
    expect(String(appels[0]?.init.body)).toContain('request_uuid');
    const entetes = appels[0]?.init.headers as Record<string, string>;
    expect(entetes.Cookie).toContain(SESSION);
  });

  it('T05 · refuse une ressource hors périmètre avant d’émettre', async () => {
    espionner(reponseJson({ success: true, data: {} }));
    for (const ressource of ['../web/content/9', 'intakes/A 1/photos', 'a?b=c']) {
      await expect(opsDelete(ressource, {}, SESSION, 'corr'))
        .rejects.toThrow(OpsGatewayError);
    }
    expect(appels).toHaveLength(0);
  });
});

describe('T06–T11 · le relais binaire', () => {
  it('T06/T07 · ne bufferise jamais le fichier', () => {
    // La preuve est dans le source : une seule ligne `arrayBuffer` suffirait à
    // ramener les dix mébioctets en mémoire à chaque lecteur simultané.
    const debut = SOURCE.indexOf('export async function opsGetBinaire');
    const fin = SOURCE.indexOf('/** L’identité de l’opérateur connecté. */');
    const corps = SOURCE.slice(debut, fin > debut ? fin : undefined);
    expect(corps).not.toContain('arrayBuffer');
    expect(corps).not.toContain('.blob(');
    expect(corps).not.toContain('Buffer.from');
    // Et le flux rendu est bien celui de la réponse, sous surveillance.
    expect(corps).toContain('corpsSurveille(reponse.body');
  });

  it('T08 · transmet la session Ops et le préfixe, sans chemin libre', async () => {
    espionner(reponseImage([JPEG]));
    const image = await opsGetBinaire(
      'intakes/AIR-1-A001/photos/abc', SESSION, 'corr', ['image/jpeg']);
    expect(appels[0]?.url).toContain('/api/v1/ops/intakes/AIR-1-A001/photos/abc');
    const entetes = appels[0]?.init.headers as Record<string, string>;
    expect(entetes.Cookie).toBe(`session_id=${SESSION}`);
    expect(await toutLire(image.corps)).toBe(JPEG.byteLength);
  });

  it('T09 · traite une redirection vers /web/login comme un refus', async () => {
    espionner(new Response(null, {
      status: 303, headers: { location: '/web/login' },
    }));
    await expect(opsGetBinaire('intakes/A-1/photos/x', SESSION, 'corr', ['image/jpeg']))
      .rejects.toMatchObject({ code: 'forbidden' });

    // Le 303 rendu par le mock ne prouve rien à lui seul : c'est `fetch` qui
    // décide de suivre une redirection ou de la rendre, et un mock ne joue pas
    // cette sémantique. Ce qui se vérifie ici, c'est donc la **configuration**
    // — sans `manual`, Odoo répondrait `200 text/html` sur la page de
    // connexion, et le refus deviendrait une image illisible.
    expect(appels[0]?.init.redirect).toBe('manual');
  });

  it('T10 · traduit un 403', async () => {
    espionner(new Response('', { status: 403 }));
    await expect(opsGetBinaire('intakes/A-1/photos/x', SESSION, 'corr', ['image/jpeg']))
      .rejects.toMatchObject({ code: 'forbidden' });
  });

  it('T11 · traduit un 404 et relaie son code métier', async () => {
    espionner(reponseJson({ error: { code: 'photo_not_found' } }, { status: 404 }));
    await expect(opsGetBinaire('intakes/A-1/photos/x', SESSION, 'corr', ['image/jpeg']))
      .rejects.toMatchObject({ code: 'not_found', conflictCode: 'photo_not_found' });
  });

  it('refuse un refus JSON servi sous l’étiquette d’une image', async () => {
    espionner(reponseJson({ success: false }));
    await expect(opsGetBinaire('intakes/A-1/photos/x', SESSION, 'corr', ['image/jpeg']))
      .rejects.toMatchObject({ code: 'unavailable' });
  });

  it('refuse une ressource hors périmètre avant d’émettre', async () => {
    espionner(reponseImage([JPEG]));
    await expect(opsGetBinaire('../web/content/9', SESSION, 'corr', ['image/jpeg']))
      .rejects.toThrow(OpsGatewayError);
    expect(appels).toHaveLength(0);
  });
});

describe('T12 · la lecture du corps est bornée dans le temps', () => {
  it('interrompt une source qui se tait, et l’annule réellement', async () => {
    process.env.ODOO_TIMEOUT_MS = '60';
    resetOpsEnv();

    let annulee = false;
    // Une source qui livre un premier morceau puis ne répond plus jamais :
    // exactement ce qu'un serveur bloqué produit après ses en-têtes.
    const source = new ReadableStream<Uint8Array>({
      start(sortie) { sortie.enqueue(JPEG); },
      pull() { return new Promise<void>(() => undefined); },
      cancel() { annulee = true; },
    });
    espionner(new Response(source, {
      status: 200, headers: { 'content-type': 'image/jpeg' },
    }));

    const image = await opsGetBinaire(
      'intakes/A-1/photos/x', SESSION, 'corr', ['image/jpeg']);
    const lecteur = image.corps.getReader();

    const premier = await lecteur.read();
    expect(premier.value?.byteLength).toBe(JPEG.byteLength);

    // Le second appel ne rend pas la main tant que le minuteur n'a pas parlé.
    await expect(lecteur.read()).rejects.toThrow(OpsGatewayError);
    expect(annulee).toBe(true);
  });

  it('l’annulation par l’aval éteint le minuteur et la source', async () => {
    let annulee = false;
    const source = new ReadableStream<Uint8Array>({
      start(sortie) { sortie.enqueue(JPEG); },
      pull() { return new Promise<void>(() => undefined); },
      cancel() { annulee = true; },
    });
    espionner(new Response(source, {
      status: 200, headers: { 'content-type': 'image/jpeg' },
    }));
    const image = await opsGetBinaire(
      'intakes/A-1/photos/x', SESSION, 'corr', ['image/jpeg']);
    await image.corps.cancel('écran fermé');
    expect(annulee).toBe(true);
  });
});

/**
 * Le solde des écouteurs d'abandon posés sur les signaux.
 *
 * On mesure le solde — posés moins retirés — et non le nombre d'appels :
 * `nettoyer()` est idempotent et peut passer deux fois sans rien laisser
 * derrière lui.
 */
function observerLesEcouteurs() {
  const poses: string[] = [];
  const retires: string[] = [];
  const ajout = AbortSignal.prototype.addEventListener;
  const retrait = AbortSignal.prototype.removeEventListener;
  vi.spyOn(AbortSignal.prototype, 'addEventListener').mockImplementation(
    function (this: AbortSignal, type: string, ...reste: unknown[]) {
      poses.push(type);
      return (ajout as never as (...a: unknown[]) => void).call(this, type, ...reste);
    } as never);
  vi.spyOn(AbortSignal.prototype, 'removeEventListener').mockImplementation(
    function (this: AbortSignal, type: string, ...reste: unknown[]) {
      retires.push(type);
      return (retrait as never as (...a: unknown[]) => void).call(this, type, ...reste);
    } as never);
  return {
    poses: () => poses.filter((type) => type === 'abort').length,
    solde: () => poses.filter((type) => type === 'abort').length
      - retires.filter((type) => type === 'abort').length,
  };
}

/** Une source qui livre un morceau puis se tait — un serveur bloqué. */
function sourceMuette() {
  const mesure = { annulee: false };
  const flux = new ReadableStream<Uint8Array>({
    start(sortie) { sortie.enqueue(JPEG); },
    pull() { return new Promise<void>(() => undefined); },
    cancel() { mesure.annulee = true; },
  });
  return { flux, mesure };
}

describe('l’écouteur d’abandon ne s’accumule pas', () => {
  it('un seul écouteur pour tout le flux, quel qu’en soit le nombre de morceaux',
    async () => {
      // Poser un écouteur par morceau les retiendrait tous jusqu'à la fin :
      // sur une photo de dix mébioctets, cela ferait des centaines d'objets
      // vivants pour une seule lecture.
      const ecouteurs = observerLesEcouteurs();
      espionner(reponseImage(Array.from({ length: 25 }, () => JPEG)));

      const image = await opsGetBinaire(
        'intakes/A-1/photos/x', SESSION, 'corr', ['image/jpeg']);
      const total = await toutLire(image.corps);

      expect(total).toBe(JPEG.byteLength * 25);
      expect(ecouteurs.poses()).toBe(1);
      // Et il ne survit pas à la fin normale du flux.
      expect(ecouteurs.solde()).toBeLessThanOrEqual(0);
    });

  it('l’écouteur ne survit pas à une expiration', async () => {
    process.env.ODOO_TIMEOUT_MS = '60';
    resetOpsEnv();
    const ecouteurs = observerLesEcouteurs();
    const { flux, mesure } = sourceMuette();
    espionner(new Response(flux, {
      status: 200, headers: { 'content-type': 'image/jpeg' },
    }));

    const image = await opsGetBinaire(
      'intakes/A-1/photos/x', SESSION, 'corr', ['image/jpeg']);
    const lecteur = image.corps.getReader();
    await lecteur.read();
    await expect(lecteur.read()).rejects.toThrow(OpsGatewayError);

    expect(mesure.annulee).toBe(true);
    expect(ecouteurs.poses()).toBe(1);
    expect(ecouteurs.solde()).toBeLessThanOrEqual(0);
  });

  it('l’écouteur ne survit pas à une annulation par l’aval', async () => {
    const ecouteurs = observerLesEcouteurs();
    const { flux, mesure } = sourceMuette();
    espionner(new Response(flux, {
      status: 200, headers: { 'content-type': 'image/jpeg' },
    }));

    const image = await opsGetBinaire(
      'intakes/A-1/photos/x', SESSION, 'corr', ['image/jpeg']);
    await image.corps.cancel('écran fermé');

    expect(mesure.annulee).toBe(true);
    expect(ecouteurs.poses()).toBe(1);
    expect(ecouteurs.solde()).toBeLessThanOrEqual(0);
  });
});

describe('T13–T14 · ce qui ne devait pas bouger n’a pas bougé', () => {
  it('T13 · opsGetDocument reste réservé au PDF et rend un tampon', async () => {
    espionner(new Response(new Uint8Array([0x25, 0x50, 0x44, 0x46]), {
      status: 200, headers: { 'content-type': 'application/pdf' },
    }));
    const document = await opsGetDocument('intakes/A-1/receipt/pdf', SESSION, 'corr');
    expect(document.type).toBe('application/pdf');
    expect(document.contenu.byteLength).toBe(4);

    espionner(reponseImage([JPEG]));
    await expect(opsGetDocument('intakes/A-1/photos/x', SESSION, 'corr'))
      .rejects.toMatchObject({ code: 'unavailable' });
  });

  it('T14 · un appel JSON garde son minuteur interne et son contrat', async () => {
    espionner(reponseJson({ success: true, data: { valeur: 1 } }));
    const data = await opsGet<{ valeur: number }>('me', SESSION, 'corr');
    expect(data).toEqual({ valeur: 1 });
    expect(appels[0]?.init.method).toBe('GET');
    const entetes = appels[0]?.init.headers as Record<string, string>;
    expect(entetes['Content-Type']).toBe('application/json');
  });

  it('T14b · le refus de suivre une redirection vaut pour TOUS les appels', async () => {
    // La garantie est posée une fois, dans `appel()`, et vaut pour les dix
    // appelants — JSON, multipart, PDF et binaire. La rendre facultative pour
    // n'en servir qu'un seul retirerait `manual` à tous les autres : une
    // session expirée y deviendrait alors un `200 text/html` que le contrat
    // zod refuserait sans dire pourquoi, ou pire, qu'un `Content-Type`
    // complaisant laisserait passer.
    // `appels` est cumulatif et `espionner()` ne le vide pas : lire
    // `appels[0]` relirait six fois le premier appel, et cinq des six chemins
    // ne seraient pas testés du tout.
    espionner(reponseJson({ success: true, data: {} }));
    await opsGet('me', SESSION, 'corr');
    expect(appels.at(-1)?.init.redirect).toBe('manual');

    espionner(reponseJson({ success: true, data: {} }));
    await opsPost('intakes', { a: 1 }, SESSION, 'corr');
    expect(appels.at(-1)?.init.redirect).toBe('manual');

    espionner(reponseJson({ success: true, data: {} }));
    await opsDelete('intakes/A-1/photos/x', { request_uuid: 'u' }, SESSION, 'corr');
    expect(appels.at(-1)?.init.redirect).toBe('manual');

    espionner(reponseJson({ success: true, data: {} }));
    await opsPostFichier(
      'expenses/E-1/receipt',
      { nom: 't.jpg', type: 'image/jpeg', contenu: new Blob([JPEG]) },
      {}, SESSION, 'corr');
    expect(appels.at(-1)?.init.redirect).toBe('manual');

    espionner(new Response(new Uint8Array([0x25, 0x50, 0x44, 0x46]), {
      status: 200, headers: { 'content-type': 'application/pdf' },
    }));
    await opsGetDocument('intakes/A-1/receipt/pdf', SESSION, 'corr');
    expect(appels.at(-1)?.init.redirect).toBe('manual');

    espionner(reponseImage([JPEG]));
    const image = await opsGetBinaire(
      'intakes/A-1/photos/x', SESSION, 'corr', ['image/jpeg']);
    await toutLire(image.corps);
    expect(appels.at(-1)?.init.redirect).toBe('manual');
  });

  it('le minuteur interne n’est court-circuité que sur demande explicite', () => {
    // Sans `minuteur`, `appel()` crée et éteint le sien : c'est ce qui garantit
    // qu'aucun chemin JSON ne laisse traîner de compte à rebours.
    expect(SOURCE).toContain('const minuteur = options.minuteur ?? new AbortController()');
    expect(SOURCE).toContain('if (echeance) clearTimeout(echeance);');
  });
});
