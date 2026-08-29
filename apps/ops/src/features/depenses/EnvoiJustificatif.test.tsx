import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

const { EnvoiJustificatif } = await import('@/features/depenses/EnvoiJustificatif');

const DEPENSE = {
  reference: '11111111-2222-4333-8444-555555555555',
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  expense_date: '2026-08-20',
  category: 'Manutention',
  description: 'Portage entrepôt',
  beneficiary: '',
  amount: 15000,
  currency_code: 'XOF',
  payment_method: 'cash',
  paid_by: 'Gilles',
  state: 'review',
  has_receipt: false,
  can_attach_receipt: true,
};

function rendu(): string {
  return renderToStaticMarkup(
    <EnvoiJustificatif
      depense={DEPENSE}
      onTermine={() => undefined}
      onAnnuler={() => undefined}
      soumettre={async () => ({ ok: true })}
    />,
  );
}

describe('envoi du justificatif', () => {
  const html = rendu();

  it('n’accepte que des photos', () => {
    expect(html).toContain('accept="image/jpeg,image/png,image/webp,image/heic,image/heif"');
  });

  it('propose l’appareil photo arrière du téléphone', () => {
    expect(html).toContain('capture="environment"');
  });

  it('dit que la dépense reste enregistrée si l’envoi échoue', () => {
    expect(html).toContain('déjà enregistrée');
    expect(html).toContain('plus tard');
  });

  it('laisse sortir sans photo', () => {
    expect(html).toContain('PLUS TARD');
  });

  it('n’envoie rien tant qu’aucun fichier n’est choisi', () => {
    // Le bouton part désactivé : un appui à vide ne consomme pas de budget.
    expect(html).toMatch(/ENVOYER LA PHOTO/);
    expect(html).toContain('disabled=""');
  });

  it('ne met jamais la photo dans une adresse', () => {
    expect(html).not.toContain('data:image');
    expect(html).not.toContain('?receipt=');
  });
});
