import type { Metadata, Viewport } from 'next';
import './globals.css';

/**
 * Root layout.
 *
 * `lang="fr"` is set here and matters: it drives screen-reader pronunciation and
 * tells search engines the primary language (§50). The /en variant comes later
 * via the routing structure, not by changing this value.
 */

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? 'https://dallytrading.com';

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default:
      'DallyTrading — Import, Export, Logistique et Solutions Business au Sénégal',
    template: '%s | DallyTrading',
  },
  description:
    'DallyTrading accompagne particuliers, commerçants et entreprises dans leurs ' +
    'opérations commerciales, logistiques et internationales : import-export, fret ' +
    'maritime et aérien, transport de véhicules, groupage, sourcing et trading.',
  applicationName: 'DallyTrading',
  // Keywords carry no ranking weight today, but the terms in §49 belong in the
  // page copy — which is where they are, not only here.
  openGraph: {
    type: 'website',
    locale: 'fr_FR',
    siteName: 'DallyTrading',
    url: SITE_URL,
    title: 'DallyTrading — Import • Export • Logistics • Solutions',
    description:
      'Votre partenaire pour le commerce, l’import-export et la logistique au Sénégal.',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'DallyTrading — Import • Export • Logistics • Solutions',
    description:
      'Votre partenaire pour le commerce, l’import-export et la logistique au Sénégal.',
  },
  robots: {
    // Indexing is enabled only once the real content is in place; until then the
    // site should not be crawled with placeholder copy.
    index: false,
    follow: false,
  },
  alternates: {
    canonical: '/',
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#1e3352',
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr">
      <body className="min-h-screen antialiased">
        {/* Skip link: the first stop for a keyboard user, so they are not forced
            through the whole navigation on every page (§53). */}
        <a
          href="#contenu"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-navy-700 focus:px-4 focus:py-2 focus:text-white"
        >
          Aller au contenu principal
        </a>
        {children}
      </body>
    </html>
  );
}
