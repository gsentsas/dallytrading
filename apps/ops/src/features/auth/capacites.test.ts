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

  it('couvre les six capacités déclarées par Odoo', () => {
    expect(ENTREES_ACCUEIL.map((entree) => entree.capacite).sort()).toEqual([
      'appointment_manage',
      'expense_create',
      'intake_create',
      'payment_create',
      'supervise',
      'transfer_create',
    ]);
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
