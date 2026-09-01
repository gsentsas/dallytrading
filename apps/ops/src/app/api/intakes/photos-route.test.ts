import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * L'envoi d'une preuve, vu du BFF.
 *
 * Ce que ces tests protègent avant tout : la borne mémoire. Le justificatif de
 * caisse appelle `request.formData()` sur un corps de taille inconnue ; un
 * envoi annoncé à zéro octet et long de cent mébioctets s'y retrouverait
 * entièrement en mémoire avant d'être refusé. Cette route ne doit jamais
 * pouvoir en faire autant, y compris quand l'annonce ment.
 */

vi.mock('@/lib/auth/auth', () => ({ readOpsSession: vi.fn() }));
vi.mock('@/lib/http/origine', () => ({ origineAcceptable: vi.fn(() => true) }));
vi.mock('@/lib/ops/photos', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/ops/photos')>();
  return { ...original, addPhoto: vi.fn(), fetchPhotos: vi.fn() };
});

const { readOpsSession } = await import('@/lib/auth/auth');
const { origineAcceptable } = await import('@/lib/http/origine');
const { addPhoto, fetchPhotos } = await import('@/lib/ops/photos');
const { OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const { resetRateLimits } = await import('@/lib/rate-limit');
const { POST, GET } = await import('@/app/api/intakes/[reference]/photos/route');

const REFERENCE = 'AIR-DSS-CDG-2026-902-A001';
const UUID = '11111111-1111-4111-8111-111111111111';
const FRONTIERE = 'xxxxxxxxxx';
const TYPE_MULTIPART = `multipart/form-data; boundary=${FRONTIERE}`;

const CLICHE = {
  photo_uuid: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
  kind: 'reception' as const,
  mime_type: 'image/jpeg',
  created_at: '2026-08-31T09:00:00Z',
  created_by: 'Gilles',
  can_delete: true,
};

const LISTE = {
  photos: [CLICHE],
  can_add: true,
  limits: { max_file_bytes: 10 * 1024 * 1024, max_active_photos: 20 },
};

/** Un corps multipart minimal, écrit à la main pour en maîtriser la taille. */
function multipart(
  octetsPhoto: number, requestUuid = UUID, kind = 'reception',
  typePhoto = 'image/jpeg',
): Blob {
  const texte = (nom: string, valeur: string) =>
    `--${FRONTIERE}\r\nContent-Disposition: form-data; name="${nom}"\r\n\r\n${valeur}\r\n`;
  const entete =
    texte('request_uuid', requestUuid)
    + texte('kind', kind)
    + `--${FRONTIERE}\r\nContent-Disposition: form-data; name="photo"; `
    + `filename="p.jpg"\r\nContent-Type: ${typePhoto}\r\n\r\n`;
  const pied = `\r\n--${FRONTIERE}--\r\n`;
  const encodeur = new TextEncoder();
  const debut = encodeur.encode(entete);
  const fin = encodeur.encode(pied);
  const complet = new Uint8Array(debut.length + octetsPhoto + fin.length);
  complet.set(debut, 0);
  complet.set(new Uint8Array(octetsPhoto).fill(0x41), debut.length);
  complet.set(fin, debut.length + octetsPhoto);
  return new Blob([complet]);
}

function requete(corps: BodyInit, entetes: Record<string, string> = {}): Request {
  return new Request(`https://ops.test/api/intakes/${REFERENCE}/photos`, {
    method: 'POST',
    headers: { 'Content-Type': TYPE_MULTIPART, ...entetes },
    body: corps,
    duplex: 'half',
  } as RequestInit);
}

function contexte() {
  return { params: Promise.resolve({ reference: REFERENCE }) };
}

/**
 * Ce que le runtime tire de lui-même.
 *
 * Mesuré : construire une `Request` à partir d'un flux fait lire un premier
 * morceau à undici, avant que la route n'existe. Les bornes ci-dessous en
 * tiennent compte plutôt que de prétendre à un zéro que la plateforme
 * n'atteint pas — ce qui compte est que la route ne *draine* pas le corps.
 */
const LECTURE_ANTICIPEE = 64 * 1024;

/**
 * Un corps produit à la demande, qui compte ce qu'on lui prend.
 *
 * C'est ce compteur qui distingue « refusé » de « refusé sans avoir tout
 * lu » — la seule chose qui protège vraiment la mémoire du processus.
 */
function fluxCompte(totalOctets: number, tailleMorceau = 64 * 1024) {
  const mesure = { livres: 0, annule: false };
  let reste = totalOctets;
  const flux = new ReadableStream<Uint8Array>({
    pull(sortie) {
      if (reste <= 0) { sortie.close(); return; }
      const taille = Math.min(tailleMorceau, reste);
      reste -= taille;
      mesure.livres += taille;
      sortie.enqueue(new Uint8Array(taille).fill(0x41));
    },
    cancel() { mesure.annule = true; },
  });
  return { flux, mesure };
}

beforeEach(() => {
  resetRateLimits();
  vi.mocked(readOpsSession).mockReset();
  vi.mocked(origineAcceptable).mockReset();
  vi.mocked(addPhoto).mockReset();
  vi.mocked(fetchPhotos).mockReset();
  vi.mocked(readOpsSession).mockResolvedValue({ odooSessionId: 'session', issuedAt: 1 });
  vi.mocked(origineAcceptable).mockReturnValue(true);
  vi.mocked(addPhoto).mockResolvedValue({ status: 'added', photo: CLICHE });
  vi.mocked(fetchPhotos).mockResolvedValue(LISTE);
});

describe('POST /api/intakes/<ref>/photos · les gardes d’entrée', () => {
  it('F03 · refuse l’absence de session avant de lire quoi que ce soit', async () => {
    vi.mocked(readOpsSession).mockResolvedValue(null);
    const { flux, mesure } = fluxCompte(1024);
    expect((await POST(requete(flux), contexte())).status).toBe(401);
    expect(mesure.livres).toBeLessThanOrEqual(LECTURE_ANTICIPEE);
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('F04 · refuse une origine inacceptable', async () => {
    vi.mocked(origineAcceptable).mockReturnValue(false);
    expect((await POST(requete(multipart(8)), contexte())).status).toBe(403);
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('F05 · refuse un corps qui n’est pas multipart', async () => {
    const reponse = await POST(
      requete('{}', { 'Content-Type': 'application/json' }), contexte());
    expect(reponse.status).toBe(415);
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('F09 · exige un identifiant de geste bien formé', async () => {
    for (const identifiant of ['', 'pas-un-uuid']) {
      const reponse = await POST(requete(multipart(8, identifiant)), contexte());
      expect(reponse.status, identifiant).toBe(400);
    }
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('F10 · refuse une nature inconnue et un type annoncé hors liste', async () => {
    const nature = await POST(requete(multipart(8, UUID, 'selfie')), contexte());
    expect(nature.status).toBe(422);
    expect((await nature.json()).code).toBe('photo_kind_invalid');

    const type = await POST(
      requete(multipart(8, UUID, 'reception', 'application/pdf')), contexte());
    expect(type.status).toBe(422);
    expect((await type.json()).code).toBe('photo_type_not_allowed');
    expect(addPhoto).not.toHaveBeenCalled();
  });
});

describe('F06–F08 · la borne mémoire', () => {
  it('F06 · une annonce trop grande est refusée sans lire le corps', async () => {
    const { flux, mesure } = fluxCompte(64 * 1024);
    const reponse = await POST(
      requete(flux, { 'Content-Length': String(200 * 1024 * 1024) }), contexte());
    expect(reponse.status).toBe(422);
    expect((await reponse.json()).code).toBe('photo_too_large');
    // La route n'a rien tiré de la source : c'est tout l'intérêt de
    // l'annonce. Seule la lecture anticipée du runtime figure au compteur.
    expect(mesure.livres).toBeLessThanOrEqual(LECTURE_ANTICIPEE);
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('F07 · sans annonce, un flux trop long est refusé quand même', async () => {
    const { flux } = fluxCompte(30 * 1024 * 1024);
    const reponse = await POST(requete(flux), contexte());
    expect(reponse.status).toBe(422);
    expect((await reponse.json()).code).toBe('photo_too_large');
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('F08 · cent mébioctets ne produisent jamais cent mébioctets en mémoire',
    async () => {
      const { flux, mesure } = fluxCompte(100 * 1024 * 1024);
      const reponse = await POST(requete(flux), contexte());
      expect(reponse.status).toBe(422);
      // La lecture s'arrête juste après le plafond — dix mébioctets et la
      // marge multipart — et non au centième.
      const plafond = 10 * 1024 * 1024 + 64 * 1024;
      expect(mesure.livres).toBeLessThanOrEqual(
        plafond + 2 * LECTURE_ANTICIPEE);
      // L'écart avec les cent mébioctets annoncés est ce qui se mesure ici.
      expect(mesure.livres).toBeLessThan(11 * 1024 * 1024);
      // Et la source est réellement coupée, pas absorbée jusqu'au bout.
      expect(mesure.annule).toBe(true);
    });

  it('un corps sous le plafond passe et atteint Odoo', async () => {
    const reponse = await POST(requete(multipart(2048)), contexte());
    expect(reponse.status).toBe(200);
    expect(addPhoto).toHaveBeenCalledWith(
      REFERENCE, UUID, 'reception',
      expect.objectContaining({ type: 'image/jpeg' }),
      'session', expect.any(String));
  });
});

describe('F11–F13 · le débit', () => {
  it('F11 · finit par refuser une session qui martèle', async () => {
    for (let index = 0; index < 30; index += 1) {
      const identifiant = crypto.randomUUID();
      expect((await POST(requete(multipart(64, identifiant)), contexte())).status,
             `envoi ${index + 1}`).toBe(200);
    }
    const refuse = await POST(
      requete(multipart(64, crypto.randomUUID())), contexte());
    expect(refuse.status).toBe(429);
    expect(Number(refuse.headers.get('retry-after'))).toBeGreaterThan(0);
    expect(vi.mocked(addPhoto)).toHaveBeenCalledTimes(30);
  });

  it('F13 · une reprise d’un geste admis ne reprend pas de budget de session',
    async () => {
      // Un envoi, puis cinq reprises : le budget de session n'en a payé
      // qu'une. On le vérifie en épuisant ensuite ce budget avec des gestes
      // neufs — s'il en restait vingt-neuf, c'est qu'une seule unité a été
      // consommée.
      const geste = crypto.randomUUID();
      expect((await POST(requete(multipart(64, geste)), contexte())).status).toBe(200);
      for (let index = 0; index < 5; index += 1) {
        expect((await POST(requete(multipart(64, geste)), contexte())).status,
               `reprise ${index + 1}`).toBe(200);
      }
      for (let index = 0; index < 29; index += 1) {
        expect((await POST(
          requete(multipart(64, crypto.randomUUID())), contexte())).status,
          `geste neuf ${index + 1}`).toBe(200);
      }
      expect((await POST(
        requete(multipart(64, crypto.randomUUID())), contexte())).status).toBe(429);
    });
});

describe('R1–R7 · l’admission d’un geste', () => {
  /**
   * Épuise le budget de session avec des gestes distincts et admis.
   *
   * `dejaConsommes` compte les unités qu'un essai antérieur a déjà prises —
   * un envoi refusé par Odoo en fait partie : il a bien atteint le serveur.
   */
  async function remplirLeBudget(dejaConsommes = 0): Promise<void> {
    for (let index = 0; index < 30 - dejaConsommes; index += 1) {
      expect((await POST(
        requete(multipart(64, crypto.randomUUID())), contexte())).status,
        `envoi ${index + 1}`).toBe(200);
    }
  }

  it('R1 · un geste déjà accepté par Odoo passe encore, budget plein',
    async () => {
      const geste = crypto.randomUUID();
      expect((await POST(requete(multipart(64, geste)), contexte())).status).toBe(200);
      // Vingt-neuf de plus : le budget de session est désormais épuisé.
      for (let index = 0; index < 29; index += 1) {
        await POST(requete(multipart(64, crypto.randomUUID())), contexte());
      }
      expect((await POST(
        requete(multipart(64, crypto.randomUUID())), contexte())).status).toBe(429);

      vi.mocked(addPhoto).mockClear();
      const reprise = await POST(requete(multipart(64, geste)), contexte());
      expect(reprise.status).toBe(200);
      expect(addPhoto).toHaveBeenCalledTimes(1);
    });

  it('R2 · un geste neuf est refusé sans jamais atteindre Odoo', async () => {
    await remplirLeBudget();
    vi.mocked(addPhoto).mockClear();
    const neuf = crypto.randomUUID();

    const refus = await POST(requete(multipart(64, neuf)), contexte());
    expect(refus.status).toBe(429);
    expect(Number(refus.headers.get('retry-after'))).toBeGreaterThan(0);
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('R3 · le rejouer ne l’a pas rendu « connu » pour autant', async () => {
    // C'est ici que se voit la différence entre « observé » et « admis ». Une
    // clé posée à la simple observation ferait passer ce second essai.
    await remplirLeBudget();
    const neuf = crypto.randomUUID();
    expect((await POST(requete(multipart(64, neuf)), contexte())).status).toBe(429);
    vi.mocked(addPhoto).mockClear();

    expect((await POST(requete(multipart(64, neuf)), contexte())).status).toBe(429);
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('R4 · deux requêtes concurrentes du même geste neuf ne s’ouvrent pas la porte',
    async () => {
      await remplirLeBudget();
      vi.mocked(addPhoto).mockClear();
      const neuf = crypto.randomUUID();

      const [a, b] = await Promise.all([
        POST(requete(multipart(64, neuf)), contexte()),
        POST(requete(multipart(64, neuf)), contexte()),
      ]);
      expect(a.status).toBe(429);
      expect(b.status).toBe(429);
      expect(addPhoto).not.toHaveBeenCalled();

      // Et rien n'est resté derrière : un troisième essai est encore refusé.
      expect((await POST(requete(multipart(64, neuf)), contexte())).status).toBe(429);
      expect(addPhoto).not.toHaveBeenCalled();
    });

  it('R5 · les reprises d’un geste admis sont bornées', async () => {
    const geste = crypto.randomUUID();
    expect((await POST(requete(multipart(64, geste)), contexte())).status).toBe(200);
    for (let index = 0; index < 5; index += 1) {
      expect((await POST(requete(multipart(64, geste)), contexte())).status,
             `reprise ${index + 1}`).toBe(200);
    }
    vi.mocked(addPhoto).mockClear();

    const trop = await POST(requete(multipart(64, geste)), contexte());
    expect(trop.status).toBe(429);
    expect(Number(trop.headers.get('retry-after'))).toBeGreaterThan(0);
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('R6 · un refus métier d’Odoo ne vaut pas admission', async () => {
    const geste = crypto.randomUUID();
    vi.mocked(addPhoto).mockRejectedValueOnce(
      new OpsGatewayError('unprocessable', 'x', 'photo_dimensions_too_large'));
    expect((await POST(requete(multipart(64, geste)), contexte())).status).toBe(422);

    // Le budget se remplit ensuite. Le geste refusé n'a aucun privilège — mais
    // il a bien consommé son unité en atteignant Odoo.
    await remplirLeBudget(1);
    vi.mocked(addPhoto).mockClear();
    expect((await POST(requete(multipart(64, geste)), contexte())).status).toBe(429);
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('R6b · une panne de service ne vaut pas davantage admission', async () => {
    const geste = crypto.randomUUID();
    vi.mocked(addPhoto).mockRejectedValueOnce(new Error('ECONNREFUSED'));
    expect((await POST(requete(multipart(64, geste)), contexte())).status).toBe(503);

    await remplirLeBudget(1);
    vi.mocked(addPhoto).mockClear();
    expect((await POST(requete(multipart(64, geste)), contexte())).status).toBe(429);
    expect(addPhoto).not.toHaveBeenCalled();
  });

  it('R7 · deux premiers appels concurrents passent, sans doublon métier',
    async () => {
      // Budget disponible : les deux consomment leur unité — une prudence, pas
      // un défaut. L'unicité de la photo reste garantie par l'idempotence
      // d'Odoo, à qui l'on rend ici `replayed` pour le second.
      const geste = crypto.randomUUID();
      vi.mocked(addPhoto)
        .mockResolvedValueOnce({ status: 'added', photo: CLICHE })
        .mockResolvedValueOnce({ status: 'replayed', photo: CLICHE });

      const [a, b] = await Promise.all([
        POST(requete(multipart(64, geste)), contexte()),
        POST(requete(multipart(64, geste)), contexte()),
      ]);
      expect(a.status).toBe(200);
      expect(b.status).toBe(200);
      expect(addPhoto).toHaveBeenCalledTimes(2);
      const statuts = [(await a.json()).data.status, (await b.json()).data.status];
      expect(statuts.sort()).toEqual(['added', 'replayed']);
    });
});

describe('les refus d’Odoo sont traduits, jamais relayés bruts', () => {
  it.each([
    ['unprocessable', 'photo_dimensions_too_large', 422],
    ['unprocessable', 'photo_type_not_allowed', 422],
    ['conflict', 'photo_state_not_allowed', 409],
    ['conflict', 'idempotency_conflict', 409],
    ['conflict', 'photo_quota_active', 409],
  ] as const)('%s/%s → %i', async (code, refus, statut) => {
    vi.mocked(addPhoto).mockRejectedValue(new OpsGatewayError(code, 'x', refus));
    const reponse = await POST(requete(multipart(64)), contexte());
    expect(reponse.status).toBe(statut);
    const corps = await reponse.json();
    expect(corps.code).toBe(refus);
    expect(corps.error.length).toBeGreaterThan(10);
  });

  it('ne laisse fuir ni identifiant interne ni détail de panne', async () => {
    vi.mocked(addPhoto).mockRejectedValue(
      new Error('ECONNREFUSED 127.0.0.1:18169 attachment_id=91'));
    const reponse = await POST(requete(multipart(64)), contexte());
    expect(reponse.status).toBe(503);
    const corps = JSON.stringify(await reponse.json());
    for (const interdit of ['ECONNREFUSED', '18169', 'attachment_id', '91']) {
      expect(corps).not.toContain(interdit);
    }
  });
});

describe('F16 · GET /api/intakes/<ref>/photos', () => {
  it('rend la liste sans jamais la mettre en cache', async () => {
    const reponse = await GET(
      new Request(`https://ops.test/api/intakes/${REFERENCE}/photos`), contexte());
    expect(reponse.status).toBe(200);
    expect(reponse.headers.get('cache-control')).toContain('no-store');
    expect((await reponse.json()).data).toEqual(LISTE);
  });

  it('refuse sans session, et traduit un dossier introuvable', async () => {
    vi.mocked(readOpsSession).mockResolvedValue(null);
    expect((await GET(
      new Request('https://ops.test/x'), contexte())).status).toBe(401);

    vi.mocked(readOpsSession).mockResolvedValue({
      odooSessionId: 'session', issuedAt: 1 });
    vi.mocked(fetchPhotos).mockRejectedValue(
      new OpsGatewayError('not_found', 'introuvable'));
    expect((await GET(
      new Request('https://ops.test/x'), contexte())).status).toBe(404);
  });
});
