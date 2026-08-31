import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: () => {} }) }));

const { EtatDossier } = await import('@/features/reception/EtatDossier');

const rendu = (
  state: string, allowed: readonly string[], peutAvancer = true,
) => renderToStaticMarkup(
  <EtatDossier
    reference="AIR-DSS-CDG-2026-902-A001"
    state={state}
    allowedTransitions={allowed}
    peutAvancer={peutAvancer}
  />,
);

describe('la carte d’état du dossier', () => {
  it('affiche l’état en mots du métier, jamais son code', () => {
    const html = rendu('goods_received', ['preparing']);
    expect(html).toContain('Déposé');
    expect(html).not.toContain('goods_received');
  });

  it('F1/F3 · propose la mise en préparation quand le serveur l’autorise', () => {
    expect(rendu('goods_received', ['preparing'])).toContain('Mettre en préparation');
  });

  it('F4 · propose le passage à prêt quand le serveur l’autorise', () => {
    expect(rendu('preparing', ['ready'])).toContain('Marquer prêt à expédier');
  });

  it('F2 · sans la capacité, aucun bouton — mais l’état reste lisible', () => {
    const html = rendu('goods_received', ['preparing'], false);
    expect(html).toContain('Déposé');
    expect(html).not.toContain('Mettre en préparation');
    expect(html).not.toContain('<button');
  });

  it('F5 · une liste vide n’affiche aucun bouton', () => {
    const html = rendu('ready', []);
    expect(html).toContain('Prêt');
    expect(html).not.toContain('<button');
  });

  it('F6 · n’affiche jamais une étape absente de la réponse serveur', () => {
    const html = rendu('ready', ['departed', 'cancelled']);
    expect(html).not.toContain('<button');
    expect(html.toLowerCase()).not.toContain('départ');
    expect(html.toLowerCase()).not.toContain('annul');
  });

  it('F7 · la confirmation n’est pas affichée avant le clic', () => {
    // Elle existe, mais elle naît du geste : la carte au repos ne la montre pas.
    const html = rendu('preparing', ['ready']);
    expect(html).not.toContain('suivi client');
    expect(html).not.toContain('Confirmer');
  });
});
