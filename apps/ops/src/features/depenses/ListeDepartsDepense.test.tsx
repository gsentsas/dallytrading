import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ListeDepartsDepense } from '@/features/depenses/ListeDepartsDepense';

const DEPART = {
  reference: 'AIR-DSS-CDG-2026-002',
  transport_mode: 'air' as const,
  state: 'departed' as const,
  origin: { city: 'Dakar', location: 'DSS' },
  destination: { city: 'Paris', location: 'CDG' },
};

describe('liste des départs pour une dépense', () => {
  const html = renderToStaticMarkup(<ListeDepartsDepense departs={[DEPART]} />);

  it('nomme le départ et sa route', () => {
    expect(html).toContain('AIR-DSS-CDG-2026-002');
    expect(html).toContain('Dakar');
    expect(html).toContain('Paris');
  });

  it('dit où en est le départ, ce que la liste des réceptions n’a pas à dire', () => {
    // Une dépense se paie après le départ : sans cet état, deux départs de
    // même route seraient indiscernables.
    expect(html).toContain('Parti');
  });

  it('mène vers les dépenses du départ, jamais vers la réception', () => {
    expect(html).toContain('/depenses/AIR-DSS-CDG-2026-002');
    expect(html).not.toContain('/reception');
  });
});
