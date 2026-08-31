import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResultatsRecherche } from '@/features/recherche/ResultatsRecherche';
import type { IntakeSearchItem } from '@/lib/ops/intake-search';

const GLOBALE = 'AIR-DSS-CDG-2026-002-A001';

const OPS: IntakeSearchItem = {
  reference: GLOBALE,
  local_reference: 'A001',
  customer_name: 'Mayram Soumaré',
  customer_phone: '+221 77 123 45 67',
  state: 'goods_received',
  transport_mode: 'air',
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  received_on: '2026-08-29',
  detail_access: 'full',
  detail_access_reason: null,
};

const ANCIEN: IntakeSearchItem = {
  ...OPS,
  reference: 'A012',
  local_reference: '',
  detail_access: 'unavailable',
  detail_access_reason: 'legacy_not_supported',
};

const rendu = (items: readonly IntakeSearchItem[], hasMore = false) =>
  renderToStaticMarkup(<ResultatsRecherche items={items} hasMore={hasMore} />);

describe('la liste des dossiers trouvés', () => {
  it('R21 · ouvre un dossier Ops par sa référence globale', () => {
    const html = rendu([OPS]);
    expect(html).toContain(`href="/reception/dossier/${encodeURIComponent(GLOBALE)}"`);
  });

  it('R20 · ne rend aucun lien pour un dossier historique', () => {
    const html = rendu([ANCIEN]);
    expect(html).not.toContain('<a');
    expect(html).not.toContain('href=');
    expect(html).toContain('Dossier historique');
    expect(html).toContain('Consultation détaillée non disponible');
  });

  it('ne dit jamais qu’un dossier historique est introuvable', () => {
    expect(rendu([ANCIEN])).not.toContain('introuvable');
  });

  it('M10 · n’utilise jamais la référence locale dans une URL', () => {
    const html = rendu([OPS]);
    expect(html).not.toContain('href="/reception/dossier/A001"');
    expect(html).toContain('A001');
  });

  it('affiche assez de contexte pour distinguer deux A001', () => {
    const second: IntakeSearchItem = {
      ...OPS,
      reference: 'AIR-DSS-CDG-2026-003-A001',
      consolidation_reference: 'AIR-DSS-CDG-2026-003',
      customer_name: 'Ousmane Fall',
    };
    const html = rendu([OPS, second]);
    expect(html).toContain('AIR-DSS-CDG-2026-002');
    expect(html).toContain('AIR-DSS-CDG-2026-003');
    expect(html).toContain('Mayram Soumaré');
    expect(html).toContain('Ousmane Fall');
    expect(html).toContain(`href="/reception/dossier/${encodeURIComponent(GLOBALE)}"`);
    expect(html).toContain(
      `href="/reception/dossier/${encodeURIComponent('AIR-DSS-CDG-2026-003-A001')}"`);
  });

  it('traduit l’état et le mode plutôt que d’afficher un code', () => {
    const html = rendu([OPS]);
    expect(html).toContain('Déposé');
    expect(html).toContain('Aérien');
    expect(html).not.toContain('goods_received');
  });

  it('dit qu’il n’y a rien plutôt que de laisser un vide', () => {
    expect(rendu([])).toContain('Aucun dossier ne correspond');
  });

  it('invite à préciser quand la liste est tronquée', () => {
    expect(rendu([OPS], true)).toContain('Affinez votre recherche');
    expect(rendu([OPS], false)).not.toContain('Affinez votre recherche');
  });
});
