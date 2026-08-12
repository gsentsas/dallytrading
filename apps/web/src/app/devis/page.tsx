import type { Metadata } from 'next';
import { QuoteForm } from '@/features/quote/QuoteForm';

export const metadata: Metadata = {
  title: 'Demander un devis',
  description:
    'Demandez un devis pour vos opérations d’import-export, de fret maritime ou ' +
    'aérien, de transport de véhicules, de groupage, de sourcing ou de trading. ' +
    'Réponse rapide de nos équipes à Dakar.',
  alternates: { canonical: '/devis' },
};

/**
 * Quote request page.
 *
 * A server component holding a client island: the page shell, metadata and copy
 * are rendered on the server and cost no JavaScript, while only the form itself —
 * which genuinely needs state — ships as a client component.
 */
export default function QuotePage() {
  return (
    <main id="contenu" className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="text-3xl font-bold text-navy-800 sm:text-4xl">
        Demander un devis
      </h1>
      <p className="mt-4 text-mist-600">
        Quelques questions suffisent. Nous ne demandons que ce qui concerne le
        service choisi, et vous recevez une référence de suivi dès l’envoi.
      </p>

      <div className="mt-10">
        <QuoteForm />
      </div>

      <p className="mt-10 text-sm text-mist-600">
        Vous préférez échanger de vive voix ? Écrivez-nous sur WhatsApp ou par
        e-mail depuis la page contact.
      </p>
    </main>
  );
}
