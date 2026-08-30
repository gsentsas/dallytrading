import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

const { Agenda } = await import('@/features/agenda/Agenda');

describe('interface Agenda', () => {
  it('offre aujourd’hui, semaine et la création', () => {
    const html = renderToStaticMarkup(<Agenda />);
    expect(html).toContain('AGENDA');
    expect(html).toContain('AUJOURD');
    expect(html).toContain('SEMAINE');
    expect(html).toContain('NOUVEAU RENDEZ-VOUS');
  });

  it('prépare la réception en sessionStorage sans handle dans une URL', () => {
    const source = readFileSync(fileURLToPath(
      new URL('./Agenda.tsx', import.meta.url)), 'utf8');
    expect(source).toContain('sessionStorage.setItem');
    expect(source).toContain("router.push('/reception/colis/preparee')");
    expect(source).not.toMatch(/\?customer_reference=/);
    expect(source).not.toMatch(/\?customer=/);
  });

  it('les contacts sont des liens tel et wa.me sans appel backend', () => {
    const source = Agenda.toString();
    expect(source).toContain('tel:');
    expect(source).toContain('https://wa.me/');
    expect(source).not.toContain('/api/contact');
  });

  it('le clic préparer ne soumet jamais un intake', () => {
    const source = Agenda.toString();
    expect(source).toContain('/prepare-reception');
    expect(source).not.toContain("fetch('/api/intakes'");
  });
});
