import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it, vi } from 'vitest';

/**
 * CR1 · une panne du back n'est pas une déconnexion.
 *
 * `currentIdentity` rend `null` quand la session manque ou qu'Odoo la refuse,
 * et **lève** pour tout le reste. Un `.catch(() => null)` détruisait cette
 * distinction : un opérateur encore connecté était renvoyé vers l'écran de
 * connexion pendant une indisponibilité d'Odoo.
 */

vi.mock('@/lib/auth/auth', () => ({ currentIdentity: vi.fn() }));
vi.mock('next/navigation', () => ({
  redirect: vi.fn((cible: string) => { throw new Error(`REDIRECT:${cible}`); }),
}));

const { currentIdentity } = await import('@/lib/auth/auth');
const { OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const PageDossierLectureSeule = (await import(
  '@/app/reception/dossier/[reference]/lecture-seule/page')).default;

const SOURCE = readFileSync(fileURLToPath(new URL(
  './[reference]/lecture-seule/page.tsx', import.meta.url)), 'utf8');

const identite = (capabilities: Record<string, boolean>) => ({
  user: { name: 'Gilles', login: 'gilles.banc' },
  role: 'logistician' as const,
  cash_actor: 'Gilles', cash_actor_configured: true,
  capabilities,
});

const rendre = () => PageDossierLectureSeule({
  params: Promise.resolve({ reference: 'LEGACY-E2E-001' }),
});

describe('C1.1/C1.2 · session et capacité', () => {
  it('C1.1 · sans session, renvoie vers la connexion', async () => {
    vi.mocked(currentIdentity).mockResolvedValue(null);
    await expect(rendre()).rejects.toThrow('REDIRECT:/connexion');
  });

  it('C1.2 · avec `intake_search`, la page se rend', async () => {
    vi.mocked(currentIdentity).mockResolvedValue(
      identite({ intake_search: true, intake_create: false }));
    await expect(rendre()).resolves.toBeTruthy();
  });

  it('R2 · sans `intake_search`, refuse comme /recherche', async () => {
    vi.mocked(currentIdentity).mockResolvedValue(
      identite({ intake_search: false, intake_create: true }));
    await expect(rendre()).rejects.toThrow('REDIRECT:/');
  });
});

describe('C1.3/C1.4 · une panne ne devient jamais un logout', () => {
  it('C1.3 · une indisponibilité d’Odoo remonte, sans redirection', async () => {
    const panne = new OpsGatewayError('unavailable');
    vi.mocked(currentIdentity).mockRejectedValue(panne);
    await expect(rendre()).rejects.toBe(panne);
  });

  it('C1.4 · une erreur générique remonte aussi', async () => {
    const panne = new Error('socket hang up');
    vi.mocked(currentIdentity).mockRejectedValue(panne);
    await expect(rendre()).rejects.toBe(panne);
  });

  it('la page n’avale plus aucune erreur d’identité', () => {
    const code = SOURCE.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
    expect(code).not.toContain('.catch(');
  });
});
