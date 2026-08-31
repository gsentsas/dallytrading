import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { ENTREES_ACCUEIL, entreesAutorisees } from '@/features/auth/capacites';

describe('entrées de l’accueil', () => {
  it('ne retient que les capacités accordées', () => {
    const entrees = entreesAutorisees({ intake_create: true, payment_create: false });
    expect(entrees.map((entree) => entree.capacite)).toEqual(['intake_create']);
  });

  it('n’affiche rien quand aucune capacité n’est accordée', () => {
    expect(entreesAutorisees({})).toEqual([]);
  });

  it('traite une capacité absente comme refusée', () => {
    // Une capacité inconnue du serveur ne doit pas ouvrir un écran par
    // défaut : l'absence vaut refus.
    expect(entreesAutorisees({ intake_create: undefined as unknown as boolean })).toEqual([]);
  });

  it('ignore une valeur qui n’est pas exactement « true »', () => {
    expect(entreesAutorisees({ intake_create: 1 as unknown as boolean })).toEqual([]);
  });

  it('couvre les sept capacités déclarées par Odoo', () => {
    // L'égalité porte sur l'ensemble entier : ouvrir une capacité de plus doit
    // être une décision, et non l'effet de bord d'un écran ajouté.
    expect(ENTREES_ACCUEIL.map((entree) => entree.capacite).sort()).toEqual([
      'appointment_manage',
      'expense_create',
      'intake_create',
      'intake_search',
      'payment_create',
      'supervise',
      'transfer_create',
    ]);
  });

  it('la recherche de dossier ouvre bien un écran', () => {
    // Une entrée sans écran reste une carte inerte. Celle-ci en a un : le
    // vérifier évite d'annoncer au terrain une action qui ne mène nulle part.
    const recherche = ENTREES_ACCUEIL.find((e) => e.capacite === 'intake_search');
    expect(recherche?.href).toBe('/recherche');
  });

  it('l’encaissement ouvre la recherche de dossier', () => {
    // Un paiement se saisit dans la fiche d'un dossier : il n'existe pas
    // d'écran d'encaissement autonome, et il ne doit pas en exister un. La
    // carte mène donc à la recherche — le seul endroit d'où l'opérateur
    // retrouve un dossier sans avoir à commencer par une réception.
    const encaissement = ENTREES_ACCUEIL.find((e) => e.capacite === 'payment_create');
    expect(encaissement?.href).toBe('/recherche');
  });
});

describe('l’interface ne raisonne jamais en rôles', () => {
  const fichiers = [
    'src/features/auth/capacites.ts',
    'src/app/page.tsx',
    'src/features/auth/LoginForm.tsx',
    'src/features/auth/LogoutButton.tsx',
  ];

  it.each(fichiers)('%s ne teste aucun nom de rôle', (fichier) => {
    // C'est Odoo qui décide de ce qu'un opérateur peut faire. Une interface
    // qui écrit `role === 'supervisor'` fige cette décision côté navigateur et
    // se désynchronise le jour où un rôle change de périmètre.
    const source = readFileSync(
      fileURLToPath(new URL(`../../../${fichier}`, import.meta.url)),
      'utf8',
    ).replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    expect(source).not.toContain("'supervisor'");
    expect(source).not.toContain("'logistician'");
    expect(source).not.toMatch(/\brole\s*===/);
  });
});
