import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

const { EvenementsDossier } = await import(
  '@/features/reception/EvenementsDossier');
const { determinerAffichageEvenements } = await import(
  '@/features/reception/evenements-vocabulaire');

const SOURCE = readFileSync(
  fileURLToPath(new URL('./EvenementsDossier.tsx', import.meta.url)), 'utf8');
const PAGE = readFileSync(fileURLToPath(new URL(
  '../../app/reception/dossier/[reference]/page.tsx', import.meta.url)), 'utf8');

const rendu = (peutConsigner = true) => renderToStaticMarkup(
  <EvenementsDossier
    reference="AIR-DSS-CDG-2026-902-A001"
    peutConsigner={peutConsigner}
  />,
);

describe('la capacité, jamais le rôle', () => {
  it('sans `event_create`, le bloc n’existe pas du tout', () => {
    expect(rendu(false)).toBe('');
  });

  it('avec la capacité, le bloc s’annonce', () => {
    const html = rendu(true);
    expect(html).toContain('ÉVÉNEMENTS');
    expect(html).toContain('data-testid="evenements-dossier"');
  });

  it('ne raisonne sur aucun nom de rôle', () => {
    const sansCommentaires = SOURCE
      .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    expect(sansCommentaires).not.toContain("'supervisor'");
    expect(sansCommentaires).not.toContain("'logistician'");
    expect(sansCommentaires).not.toMatch(/\brole\s*===/);
  });

  it('la page passe bien la capacité `event_create`', () => {
    expect(PAGE).toContain('identite.capabilities.event_create === true');
  });
});

describe('ÉVÉNEMENTS n’est pas ACTIVITÉ', () => {
  it('les deux blocs coexistent, distincts, dans cet ordre', () => {
    const activite = PAGE.indexOf('activite-dossier-titre');
    const evenements = PAGE.indexOf('<EvenementsDossier');
    expect(activite).toBeGreaterThan(-1);
    expect(evenements).toBeGreaterThan(activite);
  });

  it('le bloc dit ce qu’il est, pour qu’on ne le confonde pas', () => {
    const html = rendu();
    expect(html).toContain('Ce qui est arrivé au colis');
    expect(html).toContain('restent internes');
    expect(html).not.toContain('ACTIVITÉ');
  });
});

describe('ce que l’écran ne propose jamais', () => {
  it('aucune publication, notification, localisation ni date modifiable', () => {
    const sansCommentaires = SOURCE
      .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    for (const interdit of ['visible_to_customer', 'is_automatic', 'notify',
                            'publish', 'location', 'event_date"',
                            'client verra', 'sms', 'e-mail']) {
      expect(sansCommentaires, interdit).not.toContain(interdit);
    }
  });

  it('aucun changement d’état n’est déclenché depuis ce bloc', () => {
    for (const interdit of ['/state', 'target_state', 'expected_state',
                            'advance']) {
      expect(SOURCE, interdit).not.toContain(interdit);
    }
  });

  it('aucun identifiant technique n’est écrit', () => {
    for (const interdit of ['res_model', 'res_id', 'user_id', 'company_id',
                            'shipment_id', '/web/content']) {
      expect(SOURCE, interdit).not.toContain(interdit);
    }
  });

  it('rien n’entre dans la file hors connexion', () => {
    for (const interdit of ['offline', 'IndexedDB', 'queue']) {
      expect(SOURCE, interdit).not.toContain(interdit);
    }
  });

  it('ni tableur, ni portail', () => {
    for (const interdit of ['sheet', 'outbox', 'portal', 'portail']) {
      expect(SOURCE.toLowerCase(), interdit).not.toContain(interdit);
    }
  });
});

describe('le serveur décide, l’écran obéit', () => {
  it('le formulaire n’apparaît que sur `can_add`', () => {
    const affichage = (canAdd: boolean | undefined) =>
      determinerAffichageEvenements({
        chargement: false,
        lectureEchouee: false,
        nombreEvenements: 0,
        canAdd,
        ouvert: true,
      });
    expect(affichage(true).formulaire).toBe(true);
    expect(affichage(false).formulaire).toBe(false);
    expect(affichage(undefined).formulaire).toBe(false);
    expect(affichage(false).ajoutFerme).toBe(true);
  });

  it('le bouton reste gris tant que la demande est invalide', () => {
    expect(SOURCE).toContain('disabled={etat.nom === \'envoi\' || !envoyable}');
    expect(SOURCE).toContain('demandeValide(nature, note)');
  });

  it('la note annonce si elle est obligatoire, d’après le serveur', () => {
    expect(SOURCE).toContain('nature?.note_required');
    expect(SOURCE).toContain('candidate.note_required');
  });

  it('aucune route de suppression ni de modification n’est appelée', () => {
    expect(SOURCE).not.toContain("method: 'DELETE'");
    expect(SOURCE).not.toContain("method: 'PUT'");
    expect(SOURCE).not.toContain("method: 'PATCH'");
  });
});
