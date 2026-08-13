'use client';

/**
 * Floating WhatsApp button (§46).
 *
 * The pre-filled message adapts to the page, so a visitor on the sea freight page
 * opens a conversation that already says what they are asking about. That single
 * detail is the difference between a useful lead and a message reading "Bonjour".
 *
 * Renders **nothing** when no number is configured. A WhatsApp button that opens an
 * empty chat is worse than no button: the visitor believes they have made contact.
 */

import { usePathname } from 'next/navigation';
import { CONTACT, toDialable } from '@/config/site';
import { ACTIVITIES } from '@/config/activities';

const DEFAULT_MESSAGE =
  'Bonjour DallyTrading, je souhaite obtenir des informations sur vos services.';

/** Page-specific opening message. */
function messageForPath(pathname: string): string {
  if (pathname.startsWith('/activites/')) {
    const slug = pathname.split('/')[2];
    const activity = ACTIVITIES.find((entry) => entry.slug === slug);
    if (activity) {
      return `Bonjour DallyTrading, je souhaite obtenir un devis pour : ${activity.title}.`;
    }
  }

  const byPath: Record<string, string> = {
    '/devis':
      'Bonjour DallyTrading, je souhaite être accompagné pour ma demande de devis.',
    '/tracking':
      'Bonjour DallyTrading, je souhaite des informations sur le suivi de mon expédition.',
    '/contact': 'Bonjour DallyTrading, je souhaite être contacté.',
    '/a-propos':
      'Bonjour DallyTrading, je souhaite en savoir plus sur votre entreprise.',
    '/activites':
      'Bonjour DallyTrading, je souhaite en savoir plus sur vos activités.',
  };

  return byPath[pathname] ?? DEFAULT_MESSAGE;
}

export function WhatsAppButton() {
  const pathname = usePathname();
  const number = toDialable(CONTACT.whatsapp);

  if (!number) {
    return null;
  }

  const href = `https://wa.me/${number}?text=${encodeURIComponent(
    messageForPath(pathname),
  )}`;

  return (
    <a
      href={href}
      target="_blank"
      // noopener is the one that matters: without it the opened tab can reach back
      // through window.opener. noreferrer also keeps the referrer out of logs.
      rel="noopener noreferrer"
      className="fixed bottom-5 right-5 z-50 inline-flex items-center gap-2 rounded-full bg-green-700 px-4 py-3 font-semibold text-white shadow-lg transition-colors hover:bg-green-800 sm:bottom-6 sm:right-6"
    >
      {/* The WhatsApp glyph, inlined: one fewer request, and it cannot 404. */}
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="currentColor"
        className="h-5 w-5 shrink-0"
      >
        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.347-.347.52-.52.174-.174.232-.298.347-.497.115-.198.058-.372-.058-.52-.115-.149-.643-1.55-.88-2.122-.235-.572-.472-.487-.643-.487h-.552c-.198 0-.52.075-.792.372s-1.04 1.016-1.04 2.479c0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.872.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.29.173-1.414-.074-.124-.272-.198-.57-.347Z" />
        <path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2 22l5.25-1.38a9.87 9.87 0 0 0 4.78 1.22h.01c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.86 9.86 0 0 0 12.04 2Zm0 18.13h-.01a8.2 8.2 0 0 1-4.18-1.14l-.3-.18-3.11.82.83-3.04-.19-.31a8.19 8.19 0 0 1-1.26-4.37c0-4.54 3.7-8.23 8.24-8.23a8.18 8.18 0 0 1 5.82 2.41 8.18 8.18 0 0 1 2.41 5.83c0 4.54-3.7 8.23-8.25 8.23Z" />
      </svg>
      <span className="hidden sm:inline">WhatsApp</span>
      {/* The visible label is hidden on small screens, so the accessible name has
          to come from somewhere: this is it. */}
      <span className="sr-only sm:hidden">
        Nous contacter sur WhatsApp
      </span>
    </a>
  );
}
