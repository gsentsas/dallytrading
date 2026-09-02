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

const REPRIS: IntakeSearchItem = {
  ...OPS,
  reference: 'A012',
  local_reference: '',
  detail_access: 'readonly',
  detail_access_reason: 'legacy_readonly',
};

/** Un dossier réel, mais qu'aucune URL ne saurait désigner. */
const SANS_REFERENCE: IntakeSearchItem = {
  ...OPS,
  reference: '',
  local_reference: '',
  detail_access: 'unavailable',
  detail_access_reason: 'no_reference',
};

const rendu = (items: readonly IntakeSearchItem[], hasMore = false) =>
  renderToStaticMarkup(<ResultatsRecherche items={items} hasMore={hasMore} />);

describe('la liste des dossiers trouvés', () => {
  it('R21 · ouvre un dossier Ops par sa référence globale', () => {
    const html = rendu([OPS]);
    expect(html).toContain(`href="/reception/dossier/${encodeURIComponent(GLOBALE)}"`);
  });

  it('F02 · ouvre un dossier repris sur sa fiche en lecture seule', () => {
    const html = rendu([REPRIS]);
    expect(html).toContain('href="/reception/dossier/A012/lecture-seule"');
    expect(html).toContain('Lecture seule');
    expect(html).toContain('Dossier historique — lecture seule');
  });

  it('F03 · ne rend aucun lien sans référence globale', () => {
    const html = rendu([SANS_REFERENCE]);
    expect(html).not.toContain('<a');
    expect(html).not.toContain('href=');
    expect(html).toContain('Référence globale indisponible');
  });

  it('deux dossiers sans référence ne se confondent pas dans la liste', () => {
    // Leur `reference` est vide : prise comme clé de liste, elle serait la
    // même pour les deux.
    const html = rendu([SANS_REFERENCE, { ...SANS_REFERENCE, customer_name: 'Autre' }]);
    expect(html).toContain('Mayram Soumaré');
    expect(html).toContain('Autre');
  });

  it('ne dit jamais qu’un dossier historique est introuvable', () => {
    expect(rendu([REPRIS])).not.toContain('introuvable');
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
