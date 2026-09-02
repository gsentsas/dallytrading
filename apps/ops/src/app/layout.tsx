import type { Metadata, Viewport } from 'next';

import { DallyTradingBrand } from '@/features/brand/DallyTradingBrand';

import './globals.css';
import './brand.css';

export const metadata: Metadata = {
  title: 'Dally Ops',
  description: 'Application terrain des opérations DallyTrading.',
  applicationName: 'Dally Ops',
  icons: {
    icon: [
      { url: '/icones/dallytrading-ops-192.png', type: 'image/png', sizes: '192x192' },
    ],
    apple: [
      { url: '/icones/dallytrading-ops-192.png', type: 'image/png', sizes: '192x192' },
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
