import 'fake-indexeddb/auto';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { NOM_BASE, reinitialiserBase } from '@/lib/offline/db';
import {
  marquerSynchronise, mettreEnFile, mutationsDe, prochaineAEnvoyer,
} from '@/lib/offline/queue';
import { classer, synchroniser, tenter } from '@/lib/offline/sync';

const GILLES = 'proprietaire-gilles';
const DALANDA = 'proprietaire-dalanda';
const AXXX = 'AIR-DSS-CDG-TEST-001-A169';

async function viderBase() {
  reinitialiserBase();
  await new Promise<void>((resoudre) => {
    const demande = indexedDB.deleteDatabase(NOM_BASE);
    demande.onsuccess = () => resoudre();
    demande.onerror = () => resoudre();
    demande.onblocked = () => resoudre();
  });
}

/** Une réponse HTTP factice, avec le corps qu'Odoo rendrait. */
function reponse(statut: number, corps: unknown) {
  return {
    status: statut,
    json: async () => corps,
  } as unknown as Response;
}

function succesReception(reference = AXXX) {
  return { success: true, data: { status: 'created', intake: { reference } } };
}

async function uneReception() {
  return mettreEnFile({
    operation_type: 'intake_create', owner_key: GILLES,
    payload: { consolidation_reference: 'AIR-DSS-CDG-TEST-001' },
    resume: 'Savon',
  });
}

beforeEach(async () => {
  await viderBase();
  // `navigator.locks` n'existe pas sous Node : le repli `localStorage` est
  // exercé, ce qui est justement le chemin le moins couvert par ailleurs.
  const magasin = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (cle: string) => magasin.get(cle) ?? null,
    setItem: (cle: string, valeur: string) => { magasin.set(cle, valeur); },
    removeItem: (cle: string) => { magasin.delete(cle); },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('classement des réponses', () => {
  it('un 200 confirmé est le seul succès', () => {
    expect(classer(200, { success: true }, AXXX))
      .toEqual({ issue: 'succes', reference: AXXX });
    // Un 200 sans confirmation n'en est pas un.
    expect(classer(200, { success: false }, null).issue).toBe('metier');
  });

  it.each([500, 502, 503, 429])('le statut %s est rejouable', (statut) => {
    expect(classer(statut, null, null).issue).toBe('transitoire');
  });

  it.each([401, 403])('le statut %s demande une reconnexion', (statut) => {
    expect(classer(statut, null, null).issue).toBe('authentification');
  });

  it.each([400, 409, 415, 422])('le statut %s est un refus métier', (statut) => {
    expect(classer(statut, { code: 'x', error: 'y' }, null).issue).toBe('metier');
  });
});

describe('une tentative', () => {
  it('envoie exactement le même identifiant que celui stocké', async () => {
    const mutation = await uneReception();
    const faux = vi.fn(async () => reponse(200, succesReception()));
    vi.stubGlobal('fetch', faux);

    await tenter(mutation);
    const [, init] = faux.mock.calls[0] as unknown as [string, RequestInit];
    const corps = JSON.parse(String(init.body)) as { request_uuid: string };
    expect(corps.request_uuid).toBe(mutation.request_uuid);
  });

  it('vise la route du BFF, jamais Odoo directement', async () => {
    const mutation = await uneReception();
    const faux = vi.fn(async () => reponse(200, succesReception()));
    vi.stubGlobal('fetch', faux);
    await tenter(mutation);
    const [url] = faux.mock.calls[0] as unknown as [string];
    expect(url).toBe('/api/intakes');
    expect(url).not.toContain('/api/v1/ops/');
  });

  it('traite un réseau coupé comme ambigu, pas comme un échec', async () => {
    const mutation = await uneReception();
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline'); }));
    const verdict = await tenter(mutation);
    expect(verdict.issue).toBe('ambigu');
  });

  it('traite un délai dépassé comme ambigu : le serveur a peut-être écrit', async () => {
    const mutation = await uneReception();
    vi.stubGlobal('fetch', vi.fn(async () => {
      const erreur = new Error('aborted');
      erreur.name = 'AbortError';
      throw erreur;
    }));
    const verdict = await tenter(mutation);
    expect(verdict).toMatchObject({ issue: 'ambigu', code: 'timeout' });
  });

  it('refuse de partir sans cible quand l’opération en exige une', async () => {
    const orphelin = await mettreEnFile({
      operation_type: 'wave_payment', owner_key: GILLES,
      payload: { amount: 1 }, resume: 'x',
    });
    const faux = vi.fn();
    vi.stubGlobal('fetch', faux);
    const verdict = await tenter(orphelin);
    expect(verdict).toMatchObject({ issue: 'metier', code: 'missing_target' });
    expect(faux).not.toHaveBeenCalled();
  });
});

describe('la synchronisation', () => {
  it('marque synchronisé et retient le vrai numéro de dossier', async () => {
    await uneReception();
    vi.stubGlobal('fetch', vi.fn(async () => reponse(200, succesReception())));

    const resultat = await synchroniser(GILLES);
    expect(resultat.synchronisees).toBe(1);
    const relue = (await mutationsDe(GILLES))[0];
    expect(relue?.status).toBe('synced');
    expect(relue?.server_reference).toBe(AXXX);
  });

  it('un délai dépassé laisse l’opération en attente, identifiant intact', async () => {
    const mutation = await uneReception();
    vi.stubGlobal('fetch', vi.fn(async () => {
      const erreur = new Error('aborted');
      erreur.name = 'AbortError';
      throw erreur;
    }));

    await synchroniser(GILLES);
    const relue = (await mutationsDe(GILLES))[0];
    expect(relue?.status).toBe('pending');
    expect(relue?.request_uuid).toBe(mutation.request_uuid);
    expect(relue?.server_reference).toBeNull();
  });

  it('rejoue après un silence ambigu et accepte la réponse de rejeu', async () => {
    // Le scénario critique : Odoo a écrit, la réponse s'est perdue. La seconde
    // tentative doit porter le même identifiant et être reconnue comme rejeu.
    const mutation = await uneReception();
    const appels: string[] = [];
    let premier = true;
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      appels.push(JSON.parse(String(init.body)).request_uuid);
      if (premier) {
        premier = false;
        const erreur = new Error('aborted');
        erreur.name = 'AbortError';
        throw erreur;
      }
      return reponse(200, {
        success: true,
        data: { status: 'replayed', intake: { reference: AXXX } },
      });
    }));

    await synchroniser(GILLES);
    // Le report pose un délai : on le neutralise comme le ferait le temps.
    const enAttente = (await mutationsDe(GILLES))[0];
    expect(enAttente?.status).toBe('pending');
    await new Promise((r) => setTimeout(r, 0));
    vi.setSystemTime(new Date(Date.now() + 60_000));
    await synchroniser(GILLES);
    vi.useRealTimers();

    expect(appels).toHaveLength(2);
    expect(new Set(appels).size).toBe(1);
    expect(appels[0]).toBe(mutation.request_uuid);
    const relue = (await mutationsDe(GILLES))[0];
    expect(relue?.status).toBe('synced');
    expect(relue?.server_reference).toBe(AXXX);
  });

  it('un 5xx repose l’opération sans la perdre', async () => {
    await uneReception();
    vi.stubGlobal('fetch', vi.fn(async () => reponse(503, { error: 'x' })));
    const resultat = await synchroniser(GILLES);
    expect(resultat.reportees).toBe(1);
    expect((await mutationsDe(GILLES))[0]?.status).toBe('pending');
  });

  it('un refus métier passe en erreur et cesse de boucler', async () => {
    await uneReception();
    const faux = vi.fn(async () => reponse(409, {
      success: false, code: 'consolidation_not_open',
      error: 'Ce départ n’est plus ouvert à la réception.',
    }));
    vi.stubGlobal('fetch', faux);

    await synchroniser(GILLES);
    const relue = (await mutationsDe(GILLES))[0];
    expect(relue?.status).toBe('error');
    expect(relue?.last_error_code).toBe('consolidation_not_open');

    // Deuxième passage : rien n'est renvoyé.
    await synchroniser(GILLES);
    expect(faux).toHaveBeenCalledTimes(1);
  });

  it('une session expirée suspend la file entière sans rien jeter', async () => {
    await uneReception();
    await mettreEnFile({
      operation_type: 'expense_create', owner_key: GILLES,
      payload: { amount: 1 }, resume: 'dépense',
    });
    const faux = vi.fn(async () => reponse(401, { error: 'Session expirée.' }));
    vi.stubGlobal('fetch', faux);

    const resultat = await synchroniser(GILLES);
    expect(resultat.authentification_requise).toBe(true);
    // On n'insiste pas : la seconde échouerait pareil.
    expect(faux).toHaveBeenCalledTimes(1);
    const etats = (await mutationsDe(GILLES)).map((m) => m.status);
    expect(etats).toContain('auth_required');
    expect(etats).not.toContain('synced');
  });

  it('ne touche jamais aux opérations d’un autre opérateur', async () => {
    await uneReception();
    const faux = vi.fn(async () => reponse(200, succesReception()));
    vi.stubGlobal('fetch', faux);

    const resultat = await synchroniser(DALANDA);
    expect(resultat.traitees).toBe(0);
    expect(faux).not.toHaveBeenCalled();
    expect((await mutationsDe(GILLES))[0]?.status).toBe('pending');
  });
});

describe('l’invariant central', () => {
  it('ne marque jamais synchronisé pendant que la requête est en vol', async () => {
    // Le mensonge que toute cette mécanique existe pour empêcher. On observe
    // l'état **au moment exact** où le serveur n'a encore rien répondu.
    const mutation = await uneReception();
    let etatPendantLEnvoi: string | undefined;
    vi.stubGlobal('fetch', vi.fn(async () => {
      const relue = (await mutationsDe(GILLES))
        .find((m) => m.local_id === mutation.local_id);
      etatPendantLEnvoi = relue?.status;
      return reponse(200, succesReception());
    }));

    await synchroniser(GILLES);
    expect(etatPendantLEnvoi).toBe('syncing');
    expect(etatPendantLEnvoi).not.toBe('synced');
  });

  it('ne conclut jamais au succès depuis navigator.onLine', async () => {
    // `navigator.onLine` répond « oui » derrière un portail captif qui ne
    // laisse rien passer. Il ne dit rien de la joignabilité d'Odoo.
    vi.stubGlobal('navigator', { onLine: true });
    expect(classer(503, { error: 'x' }, null).issue).toBe('transitoire');
    expect(classer(422, { code: 'y', error: 'z' }, null).issue).toBe('metier');
    expect(classer(401, null, null).issue).toBe('authentification');
  });
});

describe('le délai de reprise', () => {
  it('espace les tentatives automatiques', async () => {
    await uneReception();
    const faux = vi.fn(async () => reponse(503, { error: 'x' }));
    vi.stubGlobal('fetch', faux);

    await synchroniser(GILLES);
    // Immédiatement après, la reprise automatique ne réessaie pas.
    await synchroniser(GILLES);
    expect(faux).toHaveBeenCalledTimes(1);
  });

  it('ne fait jamais taire un geste explicite de l’opérateur', async () => {
    // Sans cette règle, « Synchroniser maintenant » ne ferait rien pendant
    // plusieurs secondes après une coupure, sans rien expliquer.
    await uneReception();
    const faux = vi.fn(async () => reponse(503, { error: 'x' }));
    vi.stubGlobal('fetch', faux);

    await synchroniser(GILLES);
    await synchroniser(GILLES, { ignorerDelai: true });
    expect(faux).toHaveBeenCalledTimes(2);
  });

  it('ne tente jamais deux fois la même opération dans une seule passe', async () => {
    // Une opération reposée en attente redevient éligible immédiatement ; sans
    // garde, une passe forcée la renverrait jusqu'à la limite.
    await uneReception();
    await mettreEnFile({
      operation_type: 'expense_create', owner_key: GILLES,
      payload: { amount: 1 }, resume: 'dépense',
    });
    const faux = vi.fn(async () => reponse(503, { error: 'x' }));
    vi.stubGlobal('fetch', faux);

    await synchroniser(GILLES, { ignorerDelai: true });
    // Deux opérations, deux tentatives : pas une de plus.
    expect(faux).toHaveBeenCalledTimes(2);
  });
});

describe('chaîne réception → paiement', () => {
  it('envoie le parent, puis l’enfant sur le vrai numéro rendu', async () => {
    const parent = await uneReception();
    const enfant = await mettreEnFile({
      operation_type: 'wave_payment', owner_key: GILLES,
      payload: { amount: 100000, currency: 'XOF' }, resume: '100 000 XOF',
      parent_local_id: parent.local_id,
    });

    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      urls.push(url);
      if (url === '/api/intakes') return reponse(200, succesReception());
      return reponse(200, {
        success: true,
        data: { status: 'created', payment: { reference: 'PAY-1' } },
      });
    }));

    await synchroniser(GILLES);
    expect(urls).toEqual([
      '/api/intakes',
      `/api/shipments/${encodeURIComponent(AXXX)}/payments`,
    ]);
    const relues = await mutationsDe(GILLES);
    expect(relues.every((m) => m.status === 'synced')).toBe(true);
    // L'enfant n'a pas changé d'identifiant en route.
    expect(relues.find((m) => m.local_id === enfant.local_id)?.request_uuid)
      .toBe(enfant.request_uuid);
  });

  it('n’envoie pas l’enfant quand le parent est refusé', async () => {
    const parent = await uneReception();
    await mettreEnFile({
      operation_type: 'wave_payment', owner_key: GILLES,
      payload: { amount: 100000 }, resume: 'paiement',
      parent_local_id: parent.local_id,
    });
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      urls.push(url);
      return reponse(409, { success: false, code: 'consolidation_not_open', error: 'x' });
    }));

    await synchroniser(GILLES);
    expect(urls).toEqual(['/api/intakes']);
    const relues = await mutationsDe(GILLES);
    expect(relues.find((m) => m.operation_type === 'intake_create')?.status)
      .toBe('error');
    expect(relues.find((m) => m.operation_type === 'wave_payment')?.status)
      .toBe('blocked');
  });

  it('l’enfant n’est jamais posté sur un numéro inventé', async () => {
    const parent = await uneReception();
    await mettreEnFile({
      operation_type: 'wave_payment', owner_key: GILLES,
      payload: { amount: 1 }, resume: 'paiement', parent_local_id: parent.local_id,
    });
    // Le parent reste en attente : l'enfant ne doit pas être proposé.
    expect((await prochaineAEnvoyer(GILLES))?.local_id).toBe(parent.local_id);
    await marquerSynchronise(parent.local_id, AXXX);
    // Sans résolution de cible, l'enfant ne part pas non plus vers ''.
    const suivante = await prochaineAEnvoyer(GILLES);
    expect(suivante?.operation_type).toBe('wave_payment');
    const faux = vi.fn();
    vi.stubGlobal('fetch', faux);
    if (suivante) {
      const verdict = await tenter({ ...suivante, target_reference: null });
      expect(verdict).toMatchObject({ code: 'missing_target' });
      expect(faux).not.toHaveBeenCalled();
    }
  });
});

describe('coordination entre onglets', () => {
  it('un second travailleur ne double pas les envois', async () => {
    await uneReception();
    let enCours = false;
    let concurrent = false;
    vi.stubGlobal('fetch', vi.fn(async () => {
      if (enCours) concurrent = true;
      enCours = true;
      await new Promise((r) => setTimeout(r, 5));
      enCours = false;
      return reponse(200, succesReception());
    }));

    await Promise.all([synchroniser(GILLES), synchroniser(GILLES)]);
    expect(concurrent).toBe(false);
    expect((await mutationsDe(GILLES)).filter((m) => m.status === 'synced'))
      .toHaveLength(1);
  });
});

describe('ce que la file ne stocke pas', () => {
  it('aucun secret ne descend dans la base locale', async () => {
    await mettreEnFile({
      operation_type: 'wave_payment', owner_key: GILLES,
      payload: {
        amount: 100000, currency: 'XOF', wave_reference: 'TW123456',
        paid_at: '2026-08-29', note: '',
      },
      resume: '100 000 XOF', target_reference: AXXX,
    });
    const rendu = JSON.stringify(await mutationsDe(GILLES)).toLowerCase();
    for (const interdit of ['password', 'api_key', 'apikey', 'bearer', 'otp',
                            'pin', 'session_id', 'cookie', 'secret',
                            'beneficiary', 'payment_method']) {
      expect(rendu).not.toContain(interdit);
    }
  });
});
