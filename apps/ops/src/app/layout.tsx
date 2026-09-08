import type { Metadata, Viewport } from 'next';
import Link from 'next/link';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { DallyTradingBrand } from '@/features/brand/DallyTradingBrand';
import { OpsShell } from '@/features/shell/OpsShell';

import './globals.css';
import './brand.css';
import './ui-shell.css';
import './ui-forms.css';
import './ui-operations.css';
import './ui-reception.css';
import './ui-detail.css';
import './ui-polish.css';
import './ui-search.css';
import './ui-secondary.css';
import './ui-flow.css';
import './ui-login-calibration.css';

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

/**
 * L'en-tête de marque, et la cloche qui mène aux éléments à traiter.
 *
 * La cloche est une porte vers la supervision : elle ne s'affiche que si Odoo
 * accorde la capacité. Un logisticien qui la verrait cliquerait vers un écran
 * que le serveur refuse — l'interface promettrait un geste qu'elle ne peut pas
 * tenir, et c'est précisément ce que cette application ne fait pas.
 *
 * Son nom accessible est le nom de la destination, « À traiter » : c'est ainsi
 * qu'un opérateur la désigne, et c'est le contrat que le parcours de bout en
 * bout emprunte depuis l'accueil.
 *
 * Le coût est une lecture d'identité par rendu. Il est assumé : la capacité
 * vient du serveur, elle ne se devine pas côté navigateur.
 */
async function BrandHeader() {
  const identite = await currentIdentity(newCorrelationId()).catch(() => null);
  const superviseur = identite?.capabilities?.supervise === true;

  return (
    <header className="ops-brand-header">
      <DallyTradingBrand />
      {superviseur ? (
      <Link className="ops-notification" href="/traitement" aria-label="À traiter">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M7 10a5 5 0 0 1 10 0c0 4 1.8 5.1 2.2 5.6H4.8C5.2 15.1 7 14 7 10ZM10 19h4"
            fill="none"
            stroke="currentColor"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="1.9"
          />
        </svg>
      </Link>
      ) : null}
    </header>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>
        <OpsShell brandHeader={<BrandHeader />}>{children}</OpsShell>
      </body>
    </html>
  );
}
