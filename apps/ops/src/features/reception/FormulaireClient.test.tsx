import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

const { FormulaireClient } = await import('@/features/reception/FormulaireClient');

function rendu(): string {
  return renderToStaticMarkup(<FormulaireClient consolidation="AIR-DSS-CDG-2026-002" />);
}

describe('le formulaire de création', () => {
  const html = rendu();

  it('propose les deux types de client', () => {
    expect(html).toContain('Particulier');
    expect(html).toContain('Professionnel');
  });

  it('démarre sur « particulier » et demande un nom et prénom', () => {
    expect(html).toContain('Nom et prénom');
    expect(html).not.toContain('Raison sociale');
  });

  it('demande le téléphone et l’adresse', () => {
    expect(html).toContain('Téléphone');
    expect(html).toContain('Adresse');
    expect(html).toContain('type="tel"');
  });

  it('annonce l’e-mail comme facultatif', () => {
    expect(html).toContain('E-mail (facultatif)');
  });

  it('n’expose aucun champ que le serveur refuserait', () => {
    // Un champ accepté ici deviendrait une colonne de res.partner écrite par
    // le navigateur.
    for (const interdit of ['is_company', 'company_id', 'partner_id',
                            'credit_limit', 'user_id', 'company_type']) {
      expect(html).not.toContain(interdit);
    }
  });

  it('n’affiche aucun résultat avant d’avoir enregistré', () => {
    expect(html).not.toContain('Client créé');
    expect(html).not.toContain('Client déjà existant');
  });

  it('propose un bouton d’enregistrement, pas un envoi à la frappe', () => {
    expect(html).toContain('Enregistrer le client');
    expect(html).toContain('type="submit"');
  });
});

describe('l’identifiant de demande', () => {
  const source = FormulaireClient.toString();

  it('est tiré par le navigateur avant le premier envoi', () => {
    expect(source).toContain('crypto.randomUUID()');
    expect(source).toContain('request_uuid');
  });

  it('est conservé d’une tentative à l’autre', () => {
    // `??=` : on ne retire un identifiant neuf que s'il n'y en a pas encore.
    expect(source).toMatch(/identifiantDemande\.current \?\?=/);
  });

  it('est remis à zéro quand la saisie change', () => {
    // Une saisie modifiée n'est plus la même demande : la rejouer sous le même
    // identifiant serait refusée, à juste titre.
    expect(source).toMatch(/identifiantDemande\.current = null/);
  });
});

describe('ce que le composant n’expose pas', () => {
  it('ne contient aucun secret', () => {
    const html = rendu();
    for (const interdit of ['session_id', 'OPS_SESSION_SECRET', 'API_KEY', 'freight:']) {
      expect(html).not.toContain(interdit);
    }
  });

  it('ne parle qu’au BFF', () => {
    const source = FormulaireClient.toString();
    expect(source).toContain('/api/customers');
    expect(source).not.toContain('/api/v1/ops/');
    expect(source).not.toContain('/web/session');
  });

  it('ne met que des références opaques dans l’URL de l’étape suivante', () => {
    const source = FormulaireClient.toString();
    expect(source).toContain('customer: etat.client.reference');
    for (const interdit of ['name:', 'phone:', 'email:']) {
      expect(source).not.toContain(`${interdit} etat.client`);
    }
  });
});
