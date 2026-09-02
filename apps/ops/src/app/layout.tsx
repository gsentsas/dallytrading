import type { Metadata, Viewport } from 'next';

import { DallyTradingBrand } from '@/features/brand/DallyTradingBrand';

import './globals.css';
import './brand.css';

export const metadata: Metadata = {
  title: 'Dally Ops',
  description: 'Application terrain des opérations DallyTrading.',
  applicationName: 'Dally Ops',
  // Toutes ces icônes dérivent du logo complet officiel. L'onglet et l'écran
  // d'accueil montrent donc la même marque que l'en-tête, jamais un
  // monogramme ni un pictogramme alternatif.
  icons: {
    icon: [
      { url: '/icones/dallytrading-ops-favicon-16.png', type: 'image/png', sizes: '16x16' },
      { url: '/icones/dallytrading-ops-favicon-32.png', type: 'image/png', sizes: '32x32' },
      { url: '/icones/dallytrading-ops-192.png', type: 'image/png', sizes: '192x192' },
      { url: '/icones/dallytrading-ops-512.png', type: 'image/png', sizes: '512x512' },
    ],
    apple: [
      { url: '/icones/dallytrading-ops-apple-180.png', type: 'image/png', sizes: '180x180' },
    ],
  },
  appleWebApp: {
    capable: true,
    title: 'Dally Ops',
    statusBarStyle: 'black-translucent',
  },
  // Un outil interne n'a rien à faire dans un index public.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#16365B',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>
        <header className="ops-brand-header">
          <DallyTradingBrand />
        </header>
        {children}
      </body>
    </html>
  );
}
