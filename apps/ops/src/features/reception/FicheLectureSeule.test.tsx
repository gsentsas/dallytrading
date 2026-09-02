import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { FicheLectureSeule } from '@/features/reception/FicheLectureSeule';
import type { FicheLegacy } from '@/lib/ops/legacy-intake';

const SOURCE = readFileSync(
  fileURLToPath(new URL('./FicheLectureSeule.tsx', import.meta.url)), 'utf8');
const PAGE = readFileSync(fileURLToPath(new URL(
  '../../app/reception/dossier/[reference]/lecture-seule/page.tsx',
  import.meta.url)), 'utf8');

const FICHE: FicheLegacy = {
  readonly: true,
  reference: 'AIR-DSS-CDG-2026-002-A015',
  local_reference: 'A015',
  state: 'goods_received',
  state_label: 'Goods received',
  transport_mode: 'air',
  direction: 'export',
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  received_on: '2026-08-20',
  customer: { name: 'Awa Legacy', phone: '+221 77 400 11 22' },
  lines: [{
    description: 'Carton repris', goods_category: 'Divers',
    package_type: 'parcel', quantity: 2,
    announced_weight_kg: null, exact_weight_kg: 8,
    length_cm: null, width_cm: null, height_cm: null, volume_cbm: 0.02,
  }],
  totals: { lines_count: 1, weight_kg: 8, volume_cbm: 0.02 },
  payments: [{
    amount: 15000, currency_code: 'XOF', payment_date: '2026-08-20',
    payment_method: { code: 'cash', name: 'Espèces' },
    collector: 'Gilles', accounting_status: 'registered',
  }],
  payment_summary: [{ currency_code: 'XOF', amount: 15000 }],
};

const rendu = (fiche: FicheLegacy = FICHE) =>
  renderToStaticMarkup(<FicheLectureSeule fiche={fiche} />);

describe('F04 · l’écran dit ce qu’il est', () => {
  it('annonce la lecture seule avant qu’on cherche un bouton', () => {
    const html = rendu();
    expect(html).toContain('data-testid="bandeau-lecture-seule"');
    expect(html).toContain('DOSSIER EN LECTURE SEULE');
    expect(html).toContain('Aucune modification n’est disponible');
  });
});

describe('F05-F08 · ce que l’opérateur lit', () => {
  it('le client, réduit au nom et au numéro', () => {
    const html = rendu();
    expect(html).toContain('Awa Legacy');
    expect(html).toContain('+221 77 400 11 22');
  });

  it('les colis et les totaux', () => {
    const html = rendu();
    expect(html).toContain('Carton repris');
    expect(html).toContain('data-testid="ls-colis"');
    expect(html).toContain('data-testid="ls-total-poids"');
    expect(html).toContain('8 kg');
  });

  it('les encaissements, sans leur référence technique', () => {
    const html = rendu();
    expect(html).toContain('15000 XOF');
    expect(html).toContain('Espèces');
    expect(html).toContain('data-testid="ls-total-encaisse"');
    expect(html).not.toContain('sheets:');
    expect(html).not.toContain('external_payment_key');
  });

  it('F13 · un dossier sans départ ni date reste lisible', () => {
    const html = rendu({
      ...FICHE, consolidation_reference: '', received_on: '',
      local_reference: '', lines: [], payments: [], payment_summary: [],
      totals: { lines_count: 0, weight_kg: 0, volume_cbm: 0 },
    });
    expect(html).toContain('data-testid="ls-aucun-colis"');
    expect(html).toContain('data-testid="ls-aucun-encaissement"');
    expect(html).not.toContain('data-testid="ls-depart"');
  });
});

describe('F09-F10 · aucune mutation n’existe dans cet écran', () => {
  it('n’importe aucun composant d’écriture', () => {
    for (const interdit of ['PhotosDossier', 'EvenementsDossier', 'EtatDossier',
                            'DossierArticles', 'PaiementDossier']) {
      expect(SOURCE, interdit).not.toContain(interdit);
      expect(PAGE, interdit).not.toContain(interdit);
    }
  });

  it('ne contient ni formulaire, ni bouton, ni appel d’écriture', () => {
    for (const interdit of ['<form', '<button', '<input', '<select', '<textarea',
                            "method: 'POST'", "method: 'PUT'",
                            "method: 'PATCH'", "method: 'DELETE'",
                            'disabled', 'request_uuid']) {
      expect(SOURCE, interdit).not.toContain(interdit);
    }
    const html = rendu();
    for (const interdit of ['<form', '<button', '<input', 'disabled']) {
      expect(html, interdit).not.toContain(interdit);
    }
  });

  it('ne met rien en file hors connexion', () => {
    for (const interdit of ['offline', 'IndexedDB', 'queue', 'serviceWorker']) {
      expect(SOURCE, interdit).not.toContain(interdit);
      expect(PAGE, interdit).not.toContain(interdit);
    }
  });

  it('n’affiche aucun identifiant technique', () => {
    for (const interdit of ['sync_source', 'external_line_key', 'shipment_id',
                            'partner_id', 'res_id', 'res_model']) {
      expect(SOURCE, interdit).not.toContain(interdit);
    }
  });
});

describe('F12 · la page reste mince', () => {
  it('ne porte que l’identité, la capacité et la référence', () => {
    // La lecture appartient au chargeur client, qui passe par le BFF ; les
    // issues d'échec se vérifient dans ChargeurFicheLectureSeule.test.tsx.
    expect(PAGE).toContain("redirect('/connexion')");
    expect(PAGE).toContain("redirect('/')");
    expect(PAGE).toContain('ChargeurFicheLectureSeule');
  });

  it('n’ouvre aucun second chemin de lecture', () => {
    expect(PAGE).not.toContain('fetchLegacyIntake');
    expect(PAGE).not.toContain('fetchIntake(');
  });
});
