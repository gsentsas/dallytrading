import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/**
 * Le navigateur n'écrit jamais dans Google Sheets.
 *
 * ## Pourquoi ce garde-fou existe
 *
 * Le classeur est alimenté par une projection Odoo → Apps Script, et par elle
 * seule. Un appel depuis l'application terrain court-circuiterait la source de
 * vérité : deux écrivains, deux vérités, et un rapprochement impossible.
 *
 * Il exigerait surtout un identifiant Google **dans le navigateur** — c'est-à-dire
 * lisible par quiconque ouvre les outils de développement sur un téléphone
 * d'entrepôt souvent partagé.
 */

// Depuis `src/lib/offline/`, la racine du projet est trois crans plus haut.
const RACINE = fileURLToPath(new URL('../../..', import.meta.url));

function fichiers(dossier: string): string[] {
  return readdirSync(dossier).flatMap((entree) => {
    const chemin = join(dossier, entree);
    if (entree === 'node_modules' || entree === '.next') return [];
    if (statSync(chemin).isDirectory()) return fichiers(chemin);
    // Les tests ne partent pas dans le navigateur — et celui-ci nomme
    // justement ce qu'il interdit.
    if (/\.test\.tsx?$/.test(entree)) return [];
    return /\.(ts|tsx|js|mjs|json|webmanifest)$/.test(entree) ? [chemin] : [];
  });
}

describe('l’application terrain n’atteint jamais Google', () => {
  const sources = fichiers(join(RACINE, 'src'))
    .concat(fichiers(join(RACINE, 'public')));

  it('inspecte réellement des fichiers', () => {
    // Sans quoi ce test passerait en ne regardant rien.
    expect(sources.length).toBeGreaterThan(20);
  });

  it('la file hors connexion ignore complètement la projection Sheet', () => {
    // L'invariant qui sépare les deux mondes : une réception est « synchronisée
    // avec le CRM » dès qu'Odoo a confirmé. La projection vers le classeur est
    // un état administratif distinct, traité plus tard par Apps Script.
    //
    // Si le moteur hors connexion venait à attendre la projection, une panne
    // Google remettrait le téléphone en « non synchronisé » alors que le colis
    // est bel et bien enregistré.
    const moteur = fichiers(join(RACINE, 'src', 'lib', 'offline'))
      .map((chemin) => readFileSync(chemin, 'utf8'))
      .join('\n');
    expect(moteur.length).toBeGreaterThan(0);
    for (const interdit of ['sheet-outbox', 'sheet_outbox', 'outbox', 'Sheet',
                            'projection']) {
      expect(moteur).not.toContain(interdit);
    }
  });

  it.each([
    'sheets.googleapis.com',
    'docs.google.com',
    'script.google.com',
    'googleapis.com/auth/spreadsheets',
    'private_key',
    'client_secret',
    'service_account',
    'DALLY_FREIGHT_SHEET_API_KEY',
  ])('ne mentionne jamais %s', (interdit) => {
    const fautifs = sources.filter((chemin) =>
      readFileSync(chemin, 'utf8').includes(interdit));
    expect(fautifs).toEqual([]);
  });
});
