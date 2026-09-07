/**
 * L'ajout d'un article arrivé après la facture, vu du comptoir.
 *
 * Ce qui est éprouvé ici tient en une phrase : **l'écran ne décide rien**. Il
 * n'ouvre le geste que si `allowed_actions` le contient, et il ne le déduit
 * jamais de `billing_locked`, de l'état de la facture ou de l'ouverture du
 * départ. Ces trois conditions se combinent, se relisent en base à chaque
 * appel, et changeront ; les recopier dans React fabriquerait un bouton qui
 * promet ce que le serveur refuse — ou qui cache ce qu'il autorise.
 *
 * Les tests couvrent donc les deux sens, y compris le cas piège : un dossier
 * verrouillé et non modifiable **dont le serveur autorise pourtant** l'ajout
 * tardif. C'est exactement la situation où une règle recopiée se tromperait.
 */
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: () => {}, push: () => {}, replace: () => {} }),
}));

const { DossierArticles } = await import('@/features/reception/DossierArticles');

const LIGNE = {
  reference: '22222222-3333-4444-8555-666666666666',
  revision: 'abc123',
  description: 'Savon',
  goods_category: 'Non alimentaire',
  package_type: 'parcel',
  quantity: 1,
  announced_weight_kg: null,
  exact_weight_kg: 13.5,
  length_cm: null,
  width_cm: null,
  height_cm: null,
  volume_cbm: 0,
  billing_method: 'real' as const,
  tariff_family_code: 'non_food',
  customs_value_xof: 25000,
  pricing_status: 'automatic' as const,
  billable_weight_kg: 13.5,
  applied_unit_price_eur: 5,
  transport_amount_eur: 67.5,
};

const FACTURATION = {
  currency: 'EUR',
  primary_invoice_number: 'FAC/2099/00001',
  primary_invoice_state: 'posted',
  primary_invoice_amount: 67.5,
  primary_paid_amount: 67.5,
  primary_remaining_amount: 0,
  total_invoiced_amount: 67.5,
  total_paid_amount: 67.5,
  total_remaining_amount: 0,
  unbilled_lines_count: 0,
  unbilled_amount: 0,
  supplement_count: 0,
  supplement_amount: 0,
  supplements: [],
};

function dossier(options: {
  actions?: readonly string[];
  editable?: boolean;
  raison?: string | null;
  facturation?: Record<string, unknown>;
  lignes?: unknown[];
}) {
  return {
    reference: 'AIR-DSS-CDG-2099-001-A801',
    local_reference: 'A001',
    consolidation_reference: 'AIR-DSS-CDG-2026-002',
    state: 'goods_received',
    received_on: '2026-08-28',
    customer: { name: 'Aissatou Kandji' },
    editable: options.editable ?? false,
    edit_block_reason: options.raison ?? 'billing_locked',
    allowed_transitions: [],
    lines: options.lignes ?? [LIGNE],
    totals: {
      lines_count: 1, weight_kg: 13.5, volume_cbm: 0,
      transport_amount_eur: 67.5, pricing_complete: true,
    },
    payments: [],
    payment_summary: [],
    reconciliation: {
      crm: { state: 'recorded', reference: 'AIR-DSS-CDG-2099-001-A801' },
      sheet: {
        state: 'synced', operator_message: 'Synchronisé avec le tableur.',
        pending_count: 0, failed_count: 0, last_synced_at: null,
      },
      billing: { ...FACTURATION, ...(options.facturation ?? {}) },
      allowed_actions: options.actions ?? [],
    },
  };
}

const rendu = (options: Parameters<typeof dossier>[0]) => renderToStaticMarkup(
  <DossierArticles
    dossier={dossier(options) as never}
    familles={[{ code: 'non_food', name: 'Non alimentaire' }] as never}
    canaux={[] as never}
    collecteur="Gilles"
  />,
);

describe('l’ajout d’un article tardif', () => {
  it('propose le geste quand le serveur l’autorise', () => {
    const html = rendu({ actions: ['add_late_package'] });
    expect(html).toContain('AJOUTER UN ARTICLE TARDIF');
    expect(html).toContain('data-testid="ajout-tardif"');
  });

  it('ne le propose pas quand le serveur ne l’autorise pas', () => {
    const html = rendu({ actions: [] });
    expect(html).not.toContain('AJOUTER UN ARTICLE TARDIF');
  });

  it(
    'suit `allowed_actions` et non le verrou : un dossier non modifiable, '
    + 'facture comptabilisée, garde le geste si le serveur l’ouvre',
    () => {
      // Le cas piège. Un écran qui aurait recopié « pas modifiable → pas
      // d'ajout » cacherait ici un geste que le serveur autorise.
      const html = rendu({
        actions: ['add_late_package'], editable: false, raison: 'billing_locked',
      });
      expect(html).toContain('AJOUTER UN ARTICLE TARDIF');
      // Et l'ajout ordinaire, lui, reste bien fermé : les deux gestes ne se
      // confondent pas.
      expect(html).not.toContain('+ AJOUTER UN ARTICLE<');
      expect(html).toContain('déjà engagé dans la facturation');
    },
  );

  it(
    'et réciproquement : un dossier modifiable sans l’action n’ouvre pas '
    + 'le geste tardif',
    () => {
      const html = rendu({ actions: [], editable: true, raison: null });
      expect(html).toContain('+ AJOUTER UN ARTICLE');
      expect(html).not.toContain('AJOUTER UN ARTICLE TARDIF');
    },
  );

  it('annonce ce que le geste fait, sans promettre que la facture bouge', () => {
    const html = rendu({ actions: ['add_late_package'] });
    expect(html).toContain('sans toucher à la facture déjà émise');
  });

  it('montre le montant non facturé quand le serveur en signale un', () => {
    // La valorisation vient d'Odoo : l'écran ne multiplie aucun poids.
    const html = rendu({
      actions: ['add_late_package'],
      facturation: { unbilled_lines_count: 1, unbilled_amount: 12.5 },
    });
    expect(html).toContain('AJOUTER UN ARTICLE TARDIF');
  });

  it('n’affiche jamais un identifiant Odoo, même sous l’action', () => {
    const html = rendu({ actions: ['add_late_package'] });
    expect(html).not.toContain('invoice_id');
    expect(html).not.toContain('partner_id');
  });
});
