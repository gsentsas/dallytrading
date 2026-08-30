/**
 * Ce que le Service Worker refuse de garder.
 *
 * Le reçu d'un client nomme une personne, dit ce qu'elle transporte et ce
 * qu'elle a payé. Sur un téléphone d'entrepôt qui passe de main en main, une
 * copie laissée dans un cache partagé par tout le navigateur serait relisible
 * par l'opérateur suivant — sans session, sans trace, et longtemps après.
 *
 * Le test charge le vrai fichier `public/sw.js` et lui présente de vraies
 * requêtes. Rejouer sa logique dans le test ne prouverait que la fidélité de
 * la copie.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import vm from 'node:vm';

import { describe, expect, it } from 'vitest';

const ORIGINE = 'https://ops.dallytrading.test';
const AXXX = 'AIR-DSS-CDG-2026-001-A001';

interface Evenement {
  readonly request: { url: string; method: string; mode: string };
  respondWith(promesse: unknown): void;
}

/** Charge le worker et rend de quoi lui envoyer des requêtes. */
function chargerWorker() {
  const source = readFileSync(
    join(process.cwd(), 'public', 'sw.js'), 'utf8');

  const ecoutes: Record<string, (e: unknown) => void> = {};
  const cachesOuverts: string[] = [];
  const self = {
    location: { origin: ORIGINE },
    addEventListener: (nom: string, rappel: (e: unknown) => void) => {
      ecoutes[nom] = rappel;
    },
    skipWaiting: () => {},
    clients: { claim: () => Promise.resolve() },
  };
  const contexte = vm.createContext({
    self,
    caches: {
      open: (nom: string) => {
        cachesOuverts.push(nom);
        return Promise.resolve({ put: () => Promise.resolve(), add: () => Promise.resolve() });
      },
      match: () => Promise.resolve(undefined),
      keys: () => Promise.resolve([]),
      delete: () => Promise.resolve(true),
    },
    fetch: () => Promise.resolve({ status: 200, type: 'basic', clone: () => ({}) }),
    Response: { error: () => ({}) },
    URL,
    Promise,
  });
  vm.runInContext(source, contexte);

  return {
    cachesOuverts,
    /** Vrai si le worker a pris la main sur la requête. */
    intercepte(url: string, mode = 'cors', method = 'GET'): boolean {
      let pris = false;
      const evenement: Evenement = {
        request: { url, method, mode },
        respondWith: () => { pris = true; },
      };
      ecoutes['fetch']?.(evenement);
      return pris;
    },
  };
}

describe('le Service Worker et le reçu client', () => {
  it('ne prend jamais la main sur le PDF du reçu', () => {
    const worker = chargerWorker();
    expect(worker.intercepte(`${ORIGINE}/api/intakes/${AXXX}/receipt/pdf`))
      .toBe(false);
    expect(worker.cachesOuverts).toEqual([]);
  });

  it('ne prend jamais la main sur le contrat du reçu', () => {
    const worker = chargerWorker();
    expect(worker.intercepte(`${ORIGINE}/api/intakes/${AXXX}/receipt`))
      .toBe(false);
    expect(worker.cachesOuverts).toEqual([]);
  });

  it('ne garde aucune réponse d’API, quelle qu’elle soit', () => {
    const worker = chargerWorker();
    for (const chemin of [
      '/api/intakes', `/api/intakes/${AXXX}`, `/api/intakes/${AXXX}/payments`,
      '/api/customers/search', '/api/me', '/api/expenses',
    ]) {
      expect(worker.intercepte(`${ORIGINE}${chemin}`), chemin).toBe(false);
    }
    expect(worker.cachesOuverts).toEqual([]);
  });

  it('n’ouvre pas non plus la page d’un reçu comme navigation hors ligne', () => {
    const worker = chargerWorker();
    expect(worker.intercepte(`${ORIGINE}/dossiers/${AXXX}/recu`, 'navigate'))
      .toBe(false);
  });

  it('garde bien la coquille, faute de quoi ce test ne prouverait rien', () => {
    const worker = chargerWorker();
    expect(worker.intercepte(`${ORIGINE}/_next/static/chunks/main.js`)).toBe(true);
    expect(worker.intercepte(`${ORIGINE}/synchronisation`, 'navigate')).toBe(true);
  });
});
