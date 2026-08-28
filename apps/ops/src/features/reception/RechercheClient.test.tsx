import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

const { RechercheClient } = await import('@/features/reception/RechercheClient');

function rendu(): string {
  return renderToStaticMarkup(<RechercheClient consolidation="AIR-DSS-CDG-2026-002" />);
}

describe('le formulaire d’identification', () => {
  const html = rendu();

  it('demande un numéro de téléphone', () => {
    // « Quel est votre numéro de téléphone ? » est ce qu'on demande au
    // comptoir : c'est le geste de terrain, pas une contrainte technique.
    expect(html).toContain('Numéro de téléphone');
    expect(html).toContain('type="tel"');
  });

  it('propose l’e-mail en second choix', () => {
    expect(html).toContain('Rechercher par e-mail');
  });

  it('n’offre aucun champ « nom »', () => {
    // Les homonymes sont courants, et une recherche par nom est aussi un moyen
    // de feuilleter le fichier clients.
    expect(html).not.toContain('name="name"');
    expect(html.toLowerCase()).not.toContain('>nom<');
    expect(html).not.toContain('Rechercher par nom');
  });

  it('cherche sur un bouton, pas à la frappe', () => {
    // Chercher à chaque touche enverrait 7, 77, 771, 7712… au serveur.
    expect(html).toContain('Rechercher');
    expect(html).toContain('type="submit"');
  });

  it('n’affiche aucun résultat avant d’avoir cherché', () => {
    expect(html).not.toContain('Client trouvé');
    expect(html).not.toContain('Aucun client trouvé');
    expect(html).not.toContain('Plusieurs fiches');
  });

  it('ne place jamais la consolidation dans un champ caché exploitable', () => {
    expect(html).not.toContain('partner_id');
  });
});

describe('ce que le composant n’expose pas', () => {
  it('ne contient aucun secret ni jeton de session', () => {
    const html = rendu();
    for (const interdit of ['session_id', 'OPS_SESSION_SECRET', 'API_KEY', 'freight:']) {
      expect(html).not.toContain(interdit);
    }
  });

  it('ne prépare aucune requête vers Odoo depuis le navigateur', () => {
    // Le navigateur ne joint jamais Odoo : il poste au BFF.
    const source = RechercheClient.toString();
    expect(source).toContain('/api/customers/search');
    expect(source).not.toContain('/api/v1/ops/');
    expect(source).not.toContain('/web/session');
  });
});
