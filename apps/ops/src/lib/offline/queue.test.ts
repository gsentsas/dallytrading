import 'fake-indexeddb/auto';

import { beforeEach, describe, expect, it } from 'vitest';

import {
  MAGASIN_MUTATIONS, NOM_BASE, VERSION_SCHEMA, migrer, reinitialiserBase,
  requete, transaction,
} from '@/lib/offline/db';
import {
  brouillonsDe, confirmerBrouillon, empreinteProprietaire, enregistrerBrouillon,
  etatDeLaFile, marquerAuthRequise, marquerBloque, marquerEnCours,
  marquerErreur, marquerSynchronise, mettreEnFile, mutationsDe,
  prochaineAEnvoyer, purger, reessayer, reporter,
  reprendreApresAuthentification, resoudreCible, toutesLesMutations,
} from '@/lib/offline/queue';

const GILLES = 'proprietaire-gilles';
const DALANDA = 'proprietaire-dalanda';

function chargeReception() {
  return {
    consolidation_reference: 'AIR-DSS-CDG-TEST-001',
    customer_reference: '11111111-2222-4333-8444-555555555555',
    received_on: '2026-08-29',
    line: { description: 'Savon' },
  };
}

async function viderBase() {
  reinitialiserBase();
  await new Promise<void>((resoudre) => {
    const demande = indexedDB.deleteDatabase(NOM_BASE);
    demande.onsuccess = () => resoudre();
    demande.onerror = () => resoudre();
    demande.onblocked = () => resoudre();
  });
}

beforeEach(viderBase);

describe('la base locale', () => {
  it('se crée avec ses magasins et ses index', async () => {
    await mettreEnFile({
      operation_type: 'intake_create', owner_key: GILLES,
      payload: chargeReception(), resume: 'Savon',
    });
    const noms = await transaction(MAGASIN_MUTATIONS, 'readonly', (t) =>
      Array.from(t.objectStore(MAGASIN_MUTATIONS).indexNames));
    expect(noms.sort()).toEqual(
      ['par_demande', 'par_parent', 'par_proprietaire', 'par_statut']);
  });

  it('migre depuis une base vide sans rien détruire', () => {
    // La migration est rejouable : chaque étape teste ce qu'elle ajoute.
    const magasins: string[] = [];
    const faux = {
      objectStoreNames: { contains: (nom: string) => magasins.includes(nom) },
      createObjectStore: (nom: string) => {
        magasins.push(nom);
        return { createIndex: () => undefined };
      },
    } as unknown as IDBDatabase;
    migrer(faux, 0);
    expect(magasins.sort()).toEqual(['ops_drafts', 'ops_metadata', 'ops_mutations']);
    // Rejouée sur une base déjà migrée, elle ne recrée rien.
    migrer(faux, VERSION_SCHEMA);
    expect(magasins).toHaveLength(3);
  });

  it('ne requalifie jamais une opération en attente lors d’une migration', async () => {
    const mutation = await mettreEnFile({
      operation_type: 'intake_create', owner_key: GILLES,
      payload: chargeReception(), resume: 'Savon',
    });
    // On rouvre la base comme le ferait un rechargement.
    reinitialiserBase();
    const relue = (await toutesLesMutations())[0];
    expect(relue?.local_id).toBe(mutation.local_id);
    expect(relue?.status).toBe('pending');
    expect(relue?.request_uuid).toBe(mutation.request_uuid);
  });
});

describe('brouillons et confirmation', () => {
  it('conserve un brouillon propre à son appareil', async () => {
    await enregistrerBrouillon({
      local_id: 'L-brouillon', owner_key: GILLES,
      operation_type: 'intake_create', payload: chargeReception(),
      resume: 'Savon en cours',
    });
    const brouillons = await brouillonsDe(GILLES);
    expect(brouillons).toHaveLength(1);
    expect(await brouillonsDe(DALANDA)).toHaveLength(0);
  });

  it('la confirmation fait passer le brouillon en file', async () => {
    await enregistrerBrouillon({
      local_id: 'L-brouillon', owner_key: GILLES,
      operation_type: 'intake_create', payload: chargeReception(), resume: 'Savon',
    });
    const mutation = await confirmerBrouillon('L-brouillon');
    expect(mutation?.status).toBe('pending');
    expect(await brouillonsDe(GILLES)).toHaveLength(0);
  });
});

describe('l’identifiant de demande', () => {
  it('est tiré à l’entrée en file, avant toute tentative réseau', async () => {
    const mutation = await mettreEnFile({
      operation_type: 'intake_create', owner_key: GILLES,
      payload: chargeReception(), resume: 'Savon',
    });
    expect(mutation.request_uuid).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
    expect(mutation.attempt_count).toBe(0);
    expect(mutation.last_attempt_at).toBeNull();
  });

  it('ne change pas d’une tentative à l’autre', async () => {
    const mutation = await mettreEnFile({
      operation_type: 'intake_create', owner_key: GILLES,
      payload: chargeReception(), resume: 'Savon',
    });
    await marquerEnCours(mutation.local_id);
    await reporter(mutation.local_id, 'timeout', 'x');
    await marquerEnCours(mutation.local_id);
    await reporter(mutation.local_id, 'network', 'x');
    const relue = await mutationsDe(GILLES);
    expect(relue[0]?.request_uuid).toBe(mutation.request_uuid);
    expect(relue[0]?.attempt_count).toBe(2);
  });

  it('survit à un rechargement complet', async () => {
    const mutation = await mettreEnFile({
      operation_type: 'wave_payment', owner_key: GILLES,
      payload: { amount: 100000, currency: 'XOF' }, resume: '100 000 XOF',
      target_reference: 'AIR-DSS-CDG-TEST-001-A001',
    });
    reinitialiserBase();
    const relue = (await mutationsDe(GILLES))[0];
    expect(relue).toMatchObject({
      local_id: mutation.local_id,
      request_uuid: mutation.request_uuid,
      status: 'pending',
      target_reference: 'AIR-DSS-CDG-TEST-001-A001',
    });
    expect(relue?.payload).toEqual({ amount: 100000, currency: 'XOF' });
  });

  it('deux opérations ne peuvent pas partager un identifiant', async () => {
    const mutation = await mettreEnFile({
      operation_type: 'expense_create', owner_key: GILLES,
      payload: {}, resume: 'x',
    });
    await expect(transaction(MAGASIN_MUTATIONS, 'readwrite', (t) =>
      requete(t.objectStore(MAGASIN_MUTATIONS).add({
        ...mutation, local_id: 'autre',
      })))).rejects.toThrow();
  });
});

describe('la machine d’états', () => {
  async function unePending() {
    return mettreEnFile({
      operation_type: 'intake_create', owner_key: GILLES,
      payload: chargeReception(), resume: 'Savon',
    });
  }

  it('pending → syncing marque une tentative réelle', async () => {
    const mutation = await unePending();
    const apres = await marquerEnCours(mutation.local_id);
    expect(apres?.status).toBe('syncing');
    expect(apres?.attempt_count).toBe(1);
    expect(apres?.last_attempt_at).not.toBeNull();
  });

  it('synced ne s’écrit qu’avec une référence serveur en main', async () => {
    const mutation = await unePending();
    await marquerEnCours(mutation.local_id);
    const apres = await marquerSynchronise(
      mutation.local_id, 'AIR-DSS-CDG-TEST-001-A169');
    expect(apres?.status).toBe('synced');
    expect(apres?.server_reference).toBe('AIR-DSS-CDG-TEST-001-A169');
  });

  it('un report repose l’opération sans toucher à son identifiant', async () => {
    const mutation = await unePending();
    await marquerEnCours(mutation.local_id);
    const apres = await reporter(mutation.local_id, 'timeout', 'trop long');
    expect(apres?.status).toBe('pending');
    expect(apres?.request_uuid).toBe(mutation.request_uuid);
    expect(apres?.next_retry_at).toBeGreaterThan(mutation.created_at);
  });

  it('un refus métier ne boucle pas', async () => {
    const mutation = await unePending();
    await marquerErreur(mutation.local_id, 'consolidation_not_open', 'fermé');
    const relue = (await mutationsDe(GILLES))[0];
    expect(relue?.status).toBe('error');
    // Une opération en erreur n'est plus proposée à l'envoi.
    expect(await prochaineAEnvoyer(GILLES)).toBeNull();
  });

  it('une session expirée suspend sans rien jeter', async () => {
    const mutation = await unePending();
    await marquerAuthRequise(mutation.local_id);
    expect((await mutationsDe(GILLES))[0]?.status).toBe('auth_required');
    expect(await prochaineAEnvoyer(GILLES)).toBeNull();

    const reprises = await reprendreApresAuthentification(GILLES);
    expect(reprises).toBe(1);
    expect((await prochaineAEnvoyer(GILLES))?.local_id).toBe(mutation.local_id);
  });

  it('un réessai manuel repart sans délai', async () => {
    const mutation = await unePending();
    await marquerErreur(mutation.local_id, 'x', 'y');
    const apres = await reessayer(mutation.local_id);
    expect(apres?.status).toBe('pending');
    expect(apres?.attempt_count).toBe(0);
    expect(await prochaineAEnvoyer(GILLES)).not.toBeNull();
  });
});

describe('isolation entre opérateurs', () => {
  it('n’envoie jamais l’opération d’un autre', async () => {
    await mettreEnFile({
      operation_type: 'intake_create', owner_key: GILLES,
      payload: chargeReception(), resume: 'Savon de Gilles',
    });
    expect(await prochaineAEnvoyer(DALANDA)).toBeNull();
    expect(await prochaineAEnvoyer(GILLES)).not.toBeNull();
  });

  it('signale à l’autre qu’une opération étrangère attend, sans la nommer', async () => {
    await mettreEnFile({
      operation_type: 'intake_create', owner_key: GILLES,
      payload: chargeReception(), resume: 'Savon de Gilles',
    });
    const etat = await etatDeLaFile(DALANDA);
    expect(etat.etrangeres).toBe(1);
    expect(etat.en_attente).toBe(0);
  });

  it('l’empreinte de propriétaire ne contient pas l’identifiant de connexion', async () => {
    const empreinte = await empreinteProprietaire('gilles.banc');
    expect(empreinte).toMatch(/^[0-9a-f]{32}$/);
    expect(empreinte).not.toContain('gilles');
    // Stable : la reconnexion du même opérateur retrouve ses opérations.
    expect(await empreinteProprietaire('gilles.banc')).toBe(empreinte);
    expect(await empreinteProprietaire('dalanda.banc')).not.toBe(empreinte);
  });
});

describe('dépendances parent / enfant', () => {
  async function couple() {
    const parent = await mettreEnFile({
      operation_type: 'intake_create', owner_key: GILLES,
      payload: chargeReception(), resume: 'Réception',
    });
    const enfant = await mettreEnFile({
      operation_type: 'wave_payment', owner_key: GILLES,
      payload: { amount: 100000, currency: 'XOF' }, resume: '100 000 XOF',
      parent_local_id: parent.local_id,
    });
    return { parent, enfant };
  }

  it('l’enfant n’est jamais proposé avant son parent', async () => {
    const { parent } = await couple();
    expect((await prochaineAEnvoyer(GILLES))?.local_id).toBe(parent.local_id);
  });

  it('l’enfant seul candidat n’est pas proposé si le parent n’est pas synchronisé', async () => {
    // Le test précédent ne suffit pas : le parent y sort en tête par ordre de
    // création, même sans la garde. Ici le parent est écarté de la file, et
    // l'enfant reste malgré tout non envoyable — sans quoi il serait posté sur
    // un dossier qui n'existe pas.
    const { parent, enfant } = await couple();
    await marquerErreur(parent.local_id, 'consolidation_not_open', 'fermé');
    const suivante = await prochaineAEnvoyer(GILLES);
    expect(suivante).toBeNull();
    expect(suivante?.local_id).not.toBe(enfant.local_id);
  });

  it('le parent synchronisé débloque l’enfant avec la vraie référence', async () => {
    const { parent, enfant } = await couple();
    await marquerSynchronise(parent.local_id, 'AIR-DSS-CDG-TEST-001-A169');
    await resoudreCible(enfant.local_id, 'AIR-DSS-CDG-TEST-001-A169');
    const suivante = await prochaineAEnvoyer(GILLES);
    expect(suivante?.local_id).toBe(enfant.local_id);
    expect(suivante?.target_reference).toBe('AIR-DSS-CDG-TEST-001-A169');
    // L'identifiant de l'enfant n'a pas bougé.
    expect(suivante?.request_uuid).toBe(enfant.request_uuid);
  });

  it('un parent définitivement refusé bloque l’enfant sans l’envoyer', async () => {
    const { parent, enfant } = await couple();
    await marquerErreur(parent.local_id, 'consolidation_not_open', 'fermé');
    await marquerBloque(enfant.local_id, 'parent refusé');
    const relu = (await mutationsDe(GILLES)).find((m) => m.local_id === enfant.local_id);
    expect(relu?.status).toBe('blocked');
    expect(relu?.target_reference).toBeNull();
    expect(await prochaineAEnvoyer(GILLES)).toBeNull();
  });
});

describe('purge locale', () => {
  it('efface les opérations synchronisées anciennes, jamais les autres', async () => {
    const vieille = await mettreEnFile({
      operation_type: 'expense_create', owner_key: GILLES,
      payload: { amount: 1 }, resume: 'vieille',
    });
    await marquerSynchronise(vieille.local_id, 'REF-1');
    const attente = await mettreEnFile({
      operation_type: 'expense_create', owner_key: GILLES,
      payload: { amount: 2 }, resume: 'en attente',
    });

    const effacees = await purger(Date.now() + 48 * 3600_000);
    expect(effacees).toBe(1);
    const restantes = await mutationsDe(GILLES);
    expect(restantes.map((m) => m.local_id)).toEqual([attente.local_id]);
  });

  it('conserve un parent tant qu’un enfant l’attend', async () => {
    const parent = await mettreEnFile({
      operation_type: 'intake_create', owner_key: GILLES,
      payload: chargeReception(), resume: 'Réception',
    });
    await marquerSynchronise(parent.local_id, 'AIR-A169');
    await mettreEnFile({
      operation_type: 'wave_payment', owner_key: GILLES,
      payload: {}, resume: 'paiement', parent_local_id: parent.local_id,
    });
    expect(await purger(Date.now() + 48 * 3600_000)).toBe(0);
  });
});
