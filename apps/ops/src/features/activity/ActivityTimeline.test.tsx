import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ActivityTimeline } from '@/features/activity/ActivityTimeline';
import type { ActivityItem } from '@/lib/ops/activity';

const EVENTS: ActivityItem[] = [{
  event: 'intake_line_updated', category: 'correction',
  label: 'Article corrigé', occurred_at: '2026-08-30T08:14:00Z',
  actor: 'Dalanda', dossier_reference: 'AIR-DSS-CDG-2026-002-A168',
  dossier_label: 'A168', summary: '7,8 kg → 8,1 kg',
  changes: [{
    field: 'exact_weight_kg', label: 'Poids exact',
    old_value: '7,8 kg', new_value: '8,1 kg',
  }],
}, {
  event: 'wave_payment_recorded', category: 'payment', label: 'Paiement Wave',
  occurred_at: '2026-08-30T07:45:00Z', actor: 'Gilles',
  dossier_reference: 'AIR-DSS-CDG-2026-002-A168', dossier_label: 'A168',
  summary: '100 000 FCFA', changes: [],
}];

describe('la timeline mobile', () => {
  it('affiche acteur, dossier et correction structurée sans identifiant interne', () => {
    const html = renderToStaticMarkup(
      <ActivityTimeline events={EVENTS} timezone="Africa/Dakar" />);
    for (const text of [
      'Dalanda', 'A168', 'Article corrigé', '7,8 kg', '8,1 kg',
      'Gilles', 'Paiement Wave', '100 000 FCFA',
    ]) expect(html).toContain(text);
    for (const internal of [
      'shipment_id', 'operator_user_id', 'request_uuid', 'dally.shipment',
    ]) expect(html).not.toContain(internal);
  });

  it('affiche l’heure dans le fuseau que le serveur a retenu', () => {
    // Même instant, deux fuseaux : l'écran suit le serveur et non le
    // navigateur, sans quoi la journée affichée et la journée filtrée
    // divergeraient autour de minuit.
    const dakar = renderToStaticMarkup(
      <ActivityTimeline events={EVENTS} timezone="Africa/Dakar" />);
    const paris = renderToStaticMarkup(
      <ActivityTimeline events={EVENTS} timezone="Europe/Paris" />);
    expect(dakar).toContain('>08:14<');
    expect(paris).toContain('>10:14<');
  });

  it('ne vide pas la timeline sur un fuseau inconnu du navigateur', () => {
    const html = renderToStaticMarkup(
      <ActivityTimeline events={EVENTS} timezone="Mars/Olympus" />);
    expect(html).toContain('Dalanda');
    expect(html).toContain('Paiement Wave');
  });

  it('rend un état vide compréhensible', () => {
    expect(renderToStaticMarkup(
      <ActivityTimeline events={[]} timezone="Africa/Dakar" empty="Rien aujourd’hui." />,
    )).toContain('Rien aujourd’hui.');
  });
});
