import type { Metadata, Viewport } from 'next';
import './globals.css';
import { Header } from '@/components/layout/Header';
import { Footer } from '@/components/layout/Footer';
import { WhatsAppButton } from '@/components/layout/WhatsAppButton';
import { JsonLd } from '@/components/seo/JsonLd';
import { organizationJsonLd, webSiteJsonLd } from '@/lib/seo';
import { BRAND, INDEXABLE, SITE_URL } from '@/config/site';

/**
 * Root layout.
 *
 * `lang="fr"` matters: it drives screen-reader pronunciation and tells search
 * engines the primary language (§50). The /en variant will come through the routing
 * structure, not by changing this value.
 *
 * Organization and WebSite structured data are emitted once here rather than per
 * page. Repeating them on every page would be redundant, and the `@id` references
 * from each page's Service or Breadcrumb data resolve to these.
 */

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default:
      'DallyTrading — Import-Export, Logistique et Fret au Sénégal',
    template: '%s | DallyTrading',
  },
  description:
    'DallyTrading accompagne particuliers, commerçants et entreprises dans leurs ' +
    'opérations commerciales, logistiques et internationales : import-export, fret ' +
    'maritime et aérien, transport de véhicules, groupage, sourcing et trading.',
  applicationName: BRAND.name,
  authors: [{ name: BRAND.name, url: SITE_URL }],
  creator: BRAND.name,
  publisher: BRAND.name,
  formatDetection: { telephone: true, address: false, email: true },
  openGraph: {
    type: 'website',
    locale: 'fr_FR',
    siteName: BRAND.name,
    url: SITE_URL,
  },
  // Gated on the environment: a staging copy indexed by Google competes with
  // production for the same keywords and is painful to undo.
  robots: {
    index: INDEXABLE,
    follow: INDEXABLE,
    googleBot: { index: INDEXABLE, follow: INDEXABLE },
  },
  alternates: {
    canonical: '/',
    languages: { 'fr-FR': '/' },
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // The logo navy, so the browser chrome matches the header on mobile.
  themeColor: '#16365b',
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr">
      <body className="flex min-h-screen flex-col antialiased">
        {/* The first stop for a keyboard user, so they are not forced through the
            whole navigation on every page (§53). */}
        <a
          href="#contenu"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-navy-700 focus:px-4 focus:py-2 focus:text-white"
        >
          Aller au contenu principal
        </a>

        <Header />
        <div className="flex-1">{children}</div>
        <Footer />
        <WhatsAppButton />

        <JsonLd data={[organizationJsonLd(), webSiteJsonLd()]} />
      </body>
    </html>
  );
}
