/**
 * Ce que `/api/me` a le droit de dire au navigateur.
 *
 * L'identité est la seule charge utile que **toutes** les pages lisent. Un
 * identifiant de base qui s'y glisserait descendrait partout, et servirait un
 * jour à désigner quelqu'un depuis le navigateur.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/auth', () => ({ currentIdentity: vi.fn() }));

const { currentIdentity } = await import('@/lib/auth/auth');
const { GET } = await import('@/app/api/me/route');

const IDENTITE = {
  user: { name: 'Gilles Sène', login: 'gilles.banc' },
  role: 'logistician' as const,
  cash_actor: 'Gilles',
  cash_actor_configured: true,
  capabilities: { intake_create: true },
};

beforeEach(() => {
  vi.mocked(currentIdentity).mockReset();
  vi.mocked(currentIdentity).mockResolvedValue(IDENTITE);
});

describe('l’identité servie au navigateur', () => {
  it('nomme l’opérateur sans jamais le numéroter', async () => {
    const reponse = await GET();
    expect(reponse.status).toBe(200);
    const charge = await reponse.json() as { data: typeof IDENTITE };
    expect(Object.keys(charge.data.user).sort()).toEqual(['login', 'name']);
    expect(JSON.stringify(charge.data)).not.toContain('"id"');
  });

  it('n’expose que le verbe de lecture', async () => {
    const route = await import('@/app/api/me/route');
    expect(Object.keys(route).filter((cle) => cle !== 'dynamic')).toEqual(['GET']);
  });

  it('ne met jamais l’identité en cache', async () => {
    expect((await GET()).headers.get('cache-control')).toContain('no-store');
  });
});
