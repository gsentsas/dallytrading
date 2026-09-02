import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

const { ChargementDepart } = await import('@/features/chargement/ChargementDepart');

const SOURCE = readFileSync(
  fileURLToPath(new URL('./ChargementDepart.tsx', import.meta.url)), 'utf8');
const PAGE = readFileSync(fileURLToPath(new URL(
  '../../app/chargement/[reference]/page.tsx', import.meta.url)), 'utf8');
const LISTE = readFileSync(fileURLToPath(new URL(
  '../../app/chargement/page.tsx', import.meta.url)), 'utf8');
const CAPACITES = readFileSync(fileURLToPath(new URL(
  '../auth/capacites.ts', import.meta.url)), 'utf8');

const sansCommentaires = (texte: string) => texte
  .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

const rendu = () => renderToStaticMarkup(
  <ChargementDepart reference="AIR-DSS-CDG-2026-002" />);

describe('la capacité, jamais le rôle', () => {
  it('les deux pages exigent `consolidation_load`', () => {
    expect(PAGE).toContain('identite.capabilities.consolidation_load !== true');
    expect(LISTE).toContain('identite.capabilities.consolidation_load !== true');
  });

  it('l’accueil ouvre l’écran par la même capacité', () => {
    expect(CAPACITES).toContain("capacite: 'consolidation_load'");
    expect(CAPACITES).toContain("href: '/chargement'");
  });

  it('aucun composant ne raisonne sur un nom de rôle', () => {
    const propre = sansCommentaires(SOURCE);
    expect(propre).not.toContain("'supervisor'");
    expect(propre).not.toContain("'logistician'");
    expect(propre).not.toMatch(/\brole\s*===/);
  });
});

describe('ce que l’écran montre au premier rendu', () => {
  it('il s’annonce, et n’invente aucun contenu avant d’avoir lu', () => {
    const html = rendu();
    expect(html).toContain('data-testid="chargement-depart"');
    expect(html).toContain('PILE DU DÉPART');
    expect(html).toContain('Chargement…');
    expect(html).not.toContain('data-testid="aucun-dossier"');
    expect(html).not.toContain('data-testid="chargement-indisponible"');
  });

  it('les trois états de lecture ont un identifiant stable', () => {
    for (const marque of ['chargement-indisponible', 'aucun-dossier',
                          'chargement-ferme', 'chargement-compte']) {
      expect(SOURCE, marque).toContain(`data-testid="${marque}"`);
    }
  });
});

describe('ce que l’écran ne propose jamais', () => {
  it('aucun geste de workflow sur le départ', () => {
    const propre = sansCommentaires(SOURCE);
    for (const interdit of ['close_collection', 'mark_ready', 'record_departure',
                            'action_close', 'action_cancel', 'action_mark',
                            'Clôturer', 'Prêt au départ', 'Faire partir']) {
      expect(propre, interdit).not.toContain(interdit);
    }
  });

  it('aucune quantité n’est saisie au clavier', () => {
    const propre = sansCommentaires(SOURCE);
    expect(propre).not.toContain('<input');
    expect(propre).not.toContain('quantity:');
    expect(propre).not.toContain('type="number"');
  });

  it('aucune route de suppression ni de modification n’est appelée', () => {
    for (const interdit of ["method: 'DELETE'", "method: 'PUT'",
                            "method: 'PATCH'"]) {
      expect(SOURCE, interdit).not.toContain(interdit);
    }
  });

  it('aucun identifiant technique ne circule', () => {
    const propre = sansCommentaires(SOURCE);
    for (const interdit of ['package_id', 'shipment_id', 'consolidation_id',
                            'company_id', 'res_model', 'res_id', 'user_id']) {
      expect(propre, interdit).not.toContain(interdit);
    }
  });

  it('rien n’entre dans la file hors connexion', () => {
    const propre = sansCommentaires(SOURCE);
    for (const interdit of ['offline', 'IndexedDB', 'queue', 'outbox']) {
      expect(propre.toLowerCase(), interdit).not.toContain(interdit.toLowerCase());
    }
  });

  it('ni tableur, ni portail, ni notification', () => {
    const propre = sansCommentaires(SOURCE).toLowerCase();
    for (const interdit of ['sheet', 'portal', 'portail', 'notify', 'sms']) {
      expect(propre, interdit).not.toContain(interdit);
    }
  });
});

describe('l’écran ne recompose aucun compte', () => {
  it('la réponse du serveur remplace l’état, elle ne le corrige pas', () => {
    const bloc = SOURCE.slice(SOURCE.indexOf('async function appliquer('));
    expect(bloc).toContain('setDetail(issue.donnees)');
    // Aucun calcul local : pas d'incrément, pas de recomptage.
    const propre = sansCommentaires(SOURCE);
    expect(propre).not.toMatch(/packages_loaded\s*\+/);
    expect(propre).not.toMatch(/loaded_quantity\s*\+/);
    expect(propre).not.toContain('.filter((');
  });

  it('le compte affiché vient du résumé du serveur', () => {
    expect(SOURCE).toContain('resumeLisible(detail.summary)');
    expect(SOURCE).toContain('resteALire(detail.summary)');
  });

  it('le bouton d’un colis suit `can_load` / `can_unload` du serveur', () => {
    expect(SOURCE).toContain('gesteProposé(colis)');
    expect(SOURCE).toContain('{geste ? (');
  });

  it('aucun second geste ne part pendant qu’un premier est en vol', () => {
    expect(SOURCE).toContain('disabled={enCours !== null}');
  });
});

describe('la page ne double-décode jamais la référence', () => {
  it('elle s’en remet à App Router, qui a déjà décodé', () => {
    // Le commentaire de la page nomme le piège : on regarde le code, pas lui.
    expect(sansCommentaires(PAGE)).not.toContain('decodeURIComponent');
    expect(PAGE).toContain('normaliserReferenceDepart(reference)');
    expect(PAGE).toContain('notFound()');
  });
});
