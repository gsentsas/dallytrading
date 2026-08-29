import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/**
 * La frontière entre ce qui tourne sur le serveur et ce qui part dans le
 * navigateur.
 *
 * ## Ce qui a rendu ce test nécessaire
 *
 * `lib/env.ts` refuse de s'exécuter dans un navigateur, et il a raison : il
 * porte la configuration, et une configuration n'a rien à faire dans une page.
 * Mais le refus est une erreur d'exécution, pas une erreur de compilation. Un
 * composant client qui importe une simple constante depuis `lib/ops/…` embarque
 * toute la chaîne jusqu'à `lib/env.ts` — la compilation réussit, le parcours
 * échoue, et personne ne le voit avant d'ouvrir la page.
 *
 * C'est exactement ce qui est arrivé en écrivant l'écran des dépenses.
 * Le parcours de bout en bout l'a rattrapé ; ce test le rattrape plus tôt.
 *
 * ## La règle
 *
 * Un fichier `'use client'` ne prend, dans `@/lib/…`, que des **types** — un
 * `import type` disparaît à la compilation — ou l'un des modules explicitement
 * reconnus sûrs des deux côtés. Élargir cette liste doit être une décision,
 * pas un effet de bord.
 */

/** Les modules de `lib` sans aucune dépendance serveur. */
const MODULES_SURS = new Set(['@/lib/ops/expenses-vocabulaire']);

const RACINE = fileURLToPath(new URL('.', import.meta.url));

function fichiers(dossier: string): string[] {
  return readdirSync(dossier).flatMap((entree) => {
    const chemin = join(dossier, entree);
    if (statSync(chemin).isDirectory()) return fichiers(chemin);
    return /\.tsx?$/.test(entree) && !/\.test\.tsx?$/.test(entree) ? [chemin] : [];
  });
}

/** Les imports de valeur — `import type` exclu — visant `@/lib/…`. */
function importsDeValeurLib(source: string): string[] {
  const cibles: string[] = [];
  // `[^;]` borne la clause à une seule instruction : sans cela, un `import`
  // antérieur s'apparierait au `from '@/lib/…'` d'une ligne suivante.
  const motif = /import\s+(type\s+)?([^;]*?)\s+from\s+'(@\/lib\/[^']+)'/g;
  let trouve: RegExpExecArray | null;
  while ((trouve = motif.exec(source)) !== null) {
    const typeEnTete = Boolean(trouve[1]);
    const clause = trouve[2] ?? '';
    const cible = trouve[3] ?? '';
    if (typeEnTete) continue;
    // `import { type X, type Y }` n'emporte rien non plus.
    const specificateurs = clause.replace(/^\{|\}$/g, '').split(',')
      .map((s) => s.trim()).filter(Boolean);
    const tousTypes = specificateurs.length > 0
      && specificateurs.every((s) => s.startsWith('type '));
    if (tousTypes) continue;
    cibles.push(cible);
  }
  return cibles;
}

describe('les composants client n’embarquent aucun module serveur', () => {
  const clients = fichiers(RACINE).filter((chemin) =>
    /^\s*'use client';/.test(readFileSync(chemin, 'utf8')));

  it('en trouve au moins un à contrôler', () => {
    // Sans quoi ce test passerait en n'inspectant rien.
    expect(clients.length).toBeGreaterThan(0);
  });

  it.each(clients)('%s ne prend que des types dans @/lib', (chemin) => {
    const interdits = importsDeValeurLib(readFileSync(chemin, 'utf8'))
      .filter((cible) => !MODULES_SURS.has(cible));
    expect(interdits).toEqual([]);
  });
});
