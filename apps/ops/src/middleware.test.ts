import { describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';

import { config, middleware } from '@/middleware';

/**
 * R3 · le seul refus que la route ne peut pas voir.
 *
 * App Router décode les segments dynamiques avant d'appeler le gestionnaire.
 * Une séquence pour-cent invalide y échoue, et la réponse était un 500 —
 * mesuré sur la route comme sur la page. Aucune validation écrite dans la
 * route ne pouvait l'intercepter.
 */
const requete = (chemin: string) =>
  new NextRequest(new URL(chemin, 'https://ops.test'));

describe('une URI illisible vaut 400', () => {
  it('sur la route du BFF, en JSON', async () => {
    const reponse = middleware(requete('/api/intakes/A%ZZ/legacy-detail'));
    expect(reponse.status).toBe(400);
    expect(await reponse.json()).toEqual({
      success: false, error: 'Référence de dossier invalide.',
    });
    expect(reponse.headers.get('Cache-Control'))
      .toBe('private, no-store, max-age=0');
  });

  it('sur la page, en texte plutôt qu’en JSON', async () => {
    const reponse = middleware(requete('/reception/dossier/A%ZZ/lecture-seule'));
    expect(reponse.status).toBe(400);
    expect(reponse.headers.get('Content-Type')).toContain('text/plain');
  });

  it('laisse passer une URI lisible', () => {
    for (const chemin of ['/api/intakes/LEGACY-E2E-001/legacy-detail',
                          '/reception/dossier/AIR-DSS-CDG-2026-002-A015/lecture-seule',
                          '/api/intakes/A%2DB/legacy-detail']) {
      expect(middleware(requete(chemin)).status, chemin).toBe(200);
    }
  });
});

describe('sa portée reste étroite', () => {
  it('ne couvre que les deux chemins de la fiche en lecture seule', () => {
    // Un middleware large deviendrait un second endroit où raisonner sur les
    // chemins, et divergerait du premier.
    expect(config.matcher).toEqual([
      '/api/intakes/:reference/legacy-detail',
      '/reception/dossier/:reference/lecture-seule',
    ]);
  });
});
