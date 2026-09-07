import type { Metadata, Viewport } from 'next';

import { OpsShell } from '@/features/shell/OpsShell';

import './globals.css';
import './brand.css';
import './ui-shell.css';
import './ui-forms.css';
import './ui-operations.css';
import './ui-reception.css';
import './ui-detail.css';
import './ui-polish.css';

export const metadata: Metadata = {
  title: 'Dally Ops',
  description: 'Application terrain des opérations DallyTrading.',
  applicationName: 'Dally Ops',
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
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#16365B',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>
        <OpsShell>{children}</OpsShell>
      </body>
    </html>
  );
}
