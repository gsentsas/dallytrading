import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

function productionSources(root: string): string {
  const files: string[] = [];
  function walk(directory: string) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
        files.push(full);
      }
    }
  }
  walk(root);
  return files.map((file) => fs.readFileSync(file, 'utf8')).join('\n');
}

describe('la frontière du journal officiel', () => {
  const sources = productionSources(path.resolve(process.cwd(), 'src'));

  it('ne laisse aucun POST navigateur fabriquer un événement', () => {
    expect(sources).not.toMatch(/opsPost\s*\([^)]*activity/s);
    expect(sources).not.toMatch(/fetch\s*\([^)]*activity[^)]*POST/s);
  });

  it('ne construit pas le journal officiel depuis IndexedDB ou Google', () => {
    const activitySource = [
      'src/lib/ops/activity.ts',
      'src/features/activity/ActivityTimeline.tsx',
      'src/app/activite/page.tsx',
    ].map((file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8')).join('\n');
    expect(activitySource).not.toMatch(/indexedDB|googleapis|spreadsheets|sheetId/i);
  });

  it('conserve les opérations locales dans la file dédiée, pas dans un faux audit', () => {
    // Le vocabulaire de la file vit dans `lib/offline/types.ts` ; l'écran le
    // rend depuis cette table. Une opération encore locale s'annonce donc
    // « en attente », jamais comme un événement confirmé par le CRM.
    const vocabulaire = fs.readFileSync(
      path.resolve(process.cwd(), 'src/lib/offline/types.ts'), 'utf8');
    expect(vocabulaire).toContain("pending: 'En attente de synchronisation'");
    expect(vocabulaire).toContain("synced: 'Synchronisé avec le CRM'");

    const ecran = fs.readFileSync(
      path.resolve(process.cwd(), 'src/features/offline/EcranSync.tsx'), 'utf8');
    expect(ecran).toContain('LIBELLES_ETAT[mutation.status]');
  });

  it('ne fait jamais lire le journal officiel par le moteur hors connexion', () => {
    // La file locale ignore jusqu'à l'existence du journal : elle ne peut donc
    // pas en fabriquer une ligne, ni en dépendre pour se déclarer synchronisée.
    const offline = productionSources(path.resolve(process.cwd(), 'src/lib/offline'));
    expect(offline).not.toContain('activity');
    expect(offline).not.toContain('audit');
  });
});
