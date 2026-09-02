import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ChargeurFicheLectureSeule } from '@/features/reception/ChargeurFicheLectureSeule';
import {
  issueDuStatut, lireFicheLegacy, messageDeLecture,
} from '@/features/reception/lecture-seule-vocabulaire';

const CHARGEUR = readFileSync(fileURLToPath(
  new URL('./ChargeurFicheLectureSeule.tsx', import.meta.url)), 'utf8');
const PAGE = readFileSync(fileURLToPath(new URL(
  '../../app/reception/dossier/[reference]/lecture-seule/page.tsx',
  import.meta.url)), 'utf8');

describe('R1 · le parcours réel passe par le BFF', () => {
  it('la page n’appelle plus Odoo depuis le rendu serveur', () => {
    // Le rendu serveur court-circuitait le BFF : ni débit, ni contrat
    // éprouvé, et deux chemins de lecture pour une seule fiche.
    for (const interdit of ['fetchLegacyIntake', 'readOpsSession',
                            'opsGet', '@/lib/auth/odoo-ops']) {
      expect(PAGE, interdit).not.toContain(interdit);
    }
    expect(PAGE).toContain('ChargeurFicheLectureSeule');
  });

  it('le chargeur interroge exactement la route du BFF', () => {
    expect(CHARGEUR).toContain(
      '`/api/intakes/${encodeURIComponent(reference)}/legacy-detail`');
    // Le navigateur ne joint jamais Odoo : la seule frontière est le BFF.
    expect(CHARGEUR).not.toContain('@/lib/auth/odoo-ops');
    expect(CHARGEUR).not.toContain('fetchLegacyIntake');
  });

  it('ne lit jamais en cache, et n’écrit rien', () => {
    expect(CHARGEUR).toContain("cache: 'no-store'");
    for (const interdit of ["method: 'POST'", "method: 'PUT'",
                            "method: 'PATCH'", "method: 'DELETE'",
                            'request_uuid', 'offline', 'IndexedDB', 'queue']) {
      expect(CHARGEUR, interdit).not.toContain(interdit);
    }
  });

  it('affiche un chargement tant que rien n’est revenu', () => {
    const html = renderToStaticMarkup(
      <ChargeurFicheLectureSeule reference="LEGACY-E2E-001" />);
    expect(html).toContain('data-testid="lecture-chargement"');
    expect(html).not.toContain('DOSSIER EN LECTURE SEULE');
  });
});

describe('R1 · les quatre refus restent distincts', () => {
  it('chaque statut appelle son propre geste', () => {
    expect(issueDuStatut(400)).toBe('reference');
    expect(issueDuStatut(401)).toBe('session');
    expect(issueDuStatut(404)).toBe('introuvable');
    expect(issueDuStatut(429)).toBe('debit');
    expect(issueDuStatut(503)).toBe('indisponible');
    expect(issueDuStatut(500)).toBe('indisponible');
  });

  it('les messages ne se confondent pas deux à deux', () => {
    const issues = ['introuvable', 'debit', 'indisponible', 'reseau',
                    'session', 'reference'] as const;
    const messages = issues.map(messageDeLecture);
    expect(new Set(messages).size).toBe(issues.length);
    for (const message of messages) expect(message.length).toBeGreaterThan(0);
  });

  it('une coupure réseau n’est pas un dossier absent', async () => {
    expect(await lireFicheLegacy(async () => { throw new TypeError('fetch'); }))
      .toEqual({ issue: 'reseau' });
    expect(messageDeLecture('reseau')).not.toBe(messageDeLecture('introuvable'));
  });
});

describe('R1 · le cycle de lecture, mesuré et non inspecté', () => {
  const FICHE = { readonly: true, reference: 'LEGACY-E2E-001' };

  it('rend la fiche sur un 200 bien formé', async () => {
    expect(await lireFicheLegacy(async () => ({
      ok: true, statut: 200, corps: { success: true, data: FICHE },
    }))).toEqual({ issue: 'ok', fiche: FICHE });
  });

  it('traduit chaque refus du BFF en son issue', async () => {
    const attendu = [
      [400, 'reference'], [401, 'session'], [404, 'introuvable'],
      [429, 'debit'], [503, 'indisponible'], [500, 'indisponible'],
    ] as const;
    for (const [statut, issue] of attendu) {
      expect(await lireFicheLegacy(async () => ({
        ok: false, statut, corps: { success: false, error: 'x' },
      })), String(statut)).toEqual({ issue });
    }
  });

  it('refuse un 200 sans charge exploitable', async () => {
    for (const corps of [null, {}, { success: false }, { success: true }]) {
      expect(await lireFicheLegacy(async () => ({ ok: true, statut: 200, corps })),
             JSON.stringify(corps)).toEqual({ issue: 'indisponible' });
    }
  });
});

describe('R2 · la capacité est celle de la recherche', () => {
  it('la fiche exige `intake_search`, jamais `intake_create`', () => {
    expect(PAGE).toContain("identite.capabilities.intake_search !== true");
    expect(PAGE).not.toContain('capabilities.intake_create');
  });

  it('elle refuse comme `/recherche` le fait', () => {
    const recherche = readFileSync(fileURLToPath(
      new URL('../../app/recherche/page.tsx', import.meta.url)), 'utf8');
    // La même condition, mot pour mot : deux formulations divergeraient.
    expect(recherche).toContain("identite.capabilities.intake_search !== true");
    expect(PAGE).toContain("redirect('/')");
    expect(PAGE).toContain("redirect('/connexion')");
  });
});
