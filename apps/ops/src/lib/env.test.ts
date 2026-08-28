import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { afterEach, describe, expect, it } from 'vitest';

import { opsEnv, opsUsesHttps, resetOpsEnv } from '@/lib/env';

const SOURCE = readFileSync(fileURLToPath(new URL('./env.ts', import.meta.url)), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/\/\/.*$/gm, '');

afterEach(() => {
  resetOpsEnv();
});

describe('périmètre de la configuration', () => {
  it('ne déclare aucune clé d’intégration privilégiée', () => {
    // Ce que le schéma ne lit pas n'existe pas sur l'objet typé. C'est ce qui
    // rend la passerelle structurellement incapable d'emprunter les droits
    // d'une intégration plutôt que ceux de l'opérateur connecté.
    for (const interdit of [
      'DALLY_FREIGHT_SYNC_API_KEY',
      'DALLY_FREIGHT_BILLING_API_KEY',
      'ODOO_API_KEY',
      'GOOGLE_SERVICE_ACCOUNT',
    ]) {
      expect(SOURCE).not.toContain(interdit);
    }
  });

  it('n’expose aucune de ces clés sur l’objet de configuration', () => {
    process.env.DALLY_FREIGHT_SYNC_API_KEY = 'clé-qui-ne-doit-pas-remonter';
    resetOpsEnv();
    expect(Object.keys(opsEnv())).not.toContain('DALLY_FREIGHT_SYNC_API_KEY');
    delete process.env.DALLY_FREIGHT_SYNC_API_KEY;
  });

  it('n’emprunte pas le secret du portail client', () => {
    // Un secret partagé ferait d'une compromission du portail une
    // compromission des opérations.
    expect(SOURCE).not.toContain('PORTAL_SESSION_SECRET');
    expect(SOURCE).toContain('OPS_SESSION_SECRET');
  });

  it('lit bien les cinq variables attendues', () => {
    expect(Object.keys(opsEnv()).sort()).toEqual([
      'NODE_ENV',
      'ODOO_DATABASE',
      'ODOO_TIMEOUT_MS',
      'ODOO_URL',
      'OPS_PUBLIC_URL',
      'OPS_SESSION_SECRET',
    ]);
  });
});

describe('validation au démarrage', () => {
  it('refuse un secret trop court', () => {
    const precedent = process.env.OPS_SESSION_SECRET;
    process.env.OPS_SESSION_SECRET = 'trop-court';
    resetOpsEnv();
    expect(() => opsEnv()).toThrow(/OPS_SESSION_SECRET/);
    process.env.OPS_SESSION_SECRET = precedent;
  });

  it('ne recopie jamais la valeur fautive dans le message', () => {
    const precedent = process.env.OPS_SESSION_SECRET;
    process.env.OPS_SESSION_SECRET = 'valeur-fautive-reconnaissable';
    resetOpsEnv();
    // Un message d'erreur qui recopie un secret finit dans un journal.
    expect(() => opsEnv()).toThrow(
      expect.objectContaining({
        message: expect.not.stringContaining('valeur-fautive-reconnaissable'),
      }),
    );
    process.env.OPS_SESSION_SECRET = precedent;
  });

  it('déduit l’usage de HTTPS de l’adresse publique', () => {
    expect(opsUsesHttps()).toBe(true);
    process.env.OPS_PUBLIC_URL = 'http://localhost:3020';
    resetOpsEnv();
    expect(opsUsesHttps()).toBe(false);
    process.env.OPS_PUBLIC_URL = 'https://ops.example.test';
  });
});
