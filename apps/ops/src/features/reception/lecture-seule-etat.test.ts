import { describe, expect, it } from 'vitest';

import {
  chargementDe, chargerFiche, etatApplicable,
  type EtatLecture,
} from '@/features/reception/lecture-seule-vocabulaire';
import type { FicheLegacy } from '@/lib/ops/legacy-intake';

/**
 * CR2 · la fiche obsolète et la course entre deux références.
 *
 * Deux défauts distincts, prouvés séparément : l'état d'un dossier ne doit
 * pas s'afficher sous un autre, et une réponse lente ne doit pas réécrire ce
 * qu'une réponse plus récente a déjà posé.
 */
const ficheDe = (reference: string) =>
  ({ readonly: true, reference } as unknown as FicheLegacy);

const CHARGEE_A: EtatLecture = {
  reference: 'A', phase: 'fiche', fiche: ficheDe('A'),
};

describe('C2.1/C2.2 · une fiche ne s’affiche jamais sous un autre dossier', () => {
  it('la fiche de A disparaît dès que le dossier demandé devient B', () => {
    expect(etatApplicable(CHARGEE_A, 'B')).toEqual(chargementDe('B'));
  });

  it('un échec sur B n’est pas masqué par la fiche de A', () => {
    // Le rendu lit `phase` : sans cette remise à zéro, il voyait une fiche et
    // s'arrêtait là, sans jamais atteindre le message d'erreur.
    const echecB: EtatLecture = { reference: 'B', phase: 'issue', issue: 'introuvable' };
    expect(etatApplicable(echecB, 'B')).toBe(echecB);
    expect(etatApplicable(CHARGEE_A, 'B').phase).toBe('chargement');
  });

  it('l’état de A reste valable tant que A est demandé', () => {
    expect(etatApplicable(CHARGEE_A, 'A')).toBe(CHARGEE_A);
  });
});

describe('C2.3/C2.4/C2.5 · un résultat périmé ne pose rien', () => {
  const reponse = (statut: number, corps: unknown) =>
    async () => ({ ok: statut < 400, statut, corps });

  it('C2.3 · une réponse lente pour A n’écrase pas B', async () => {
    const poses: EtatLecture[] = [];
    let obsolete = false;
    const lecteurA = chargerFiche(
      'A',
      () => new Promise((resoudre) => {
        setTimeout(() => resoudre({
          ok: true, statut: 200,
          corps: { success: true, data: ficheDe('A') },
        }), 20);
      }),
      (etat) => poses.push(etat),
      () => obsolete,
    );
    // B arrive avant : A devient périmé.
    obsolete = true;
    await lecteurA;
    expect(poses, 'A ne doit rien poser après avoir été dépassé').toEqual([]);
  });

  it('C2.4 · après démontage, aucun état n’est posé', async () => {
    const poses: EtatLecture[] = [];
    await chargerFiche('A', reponse(200, { success: true, data: ficheDe('A') }),
                       (etat) => poses.push(etat), () => true);
    expect(poses).toEqual([]);
  });

  it('C2.5 · un refus périmé ne remplace pas l’état courant', async () => {
    const poses: EtatLecture[] = [];
    await chargerFiche('A', reponse(404, { success: false }),
                       (etat) => poses.push(etat), () => true);
    expect(poses).toEqual([]);
  });

  it('une lecture encore valable pose bien son résultat, avec sa référence', async () => {
    const poses: EtatLecture[] = [];
    await chargerFiche('B', reponse(200, { success: true, data: ficheDe('B') }),
                       (etat) => poses.push(etat), () => false);
    expect(poses).toHaveLength(1);
    expect(poses[0]?.reference).toBe('B');
    expect(poses[0]?.phase).toBe('fiche');
  });

  it('un refus encore valable pose son issue, jamais une fiche', async () => {
    const poses: EtatLecture[] = [];
    await chargerFiche('B', reponse(429, { success: false }),
                       (etat) => poses.push(etat), () => false);
    expect(poses[0]).toEqual({ reference: 'B', phase: 'issue', issue: 'debit' });
  });
});
