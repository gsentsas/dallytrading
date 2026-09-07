import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { LoginForm } from '@/features/auth/LoginForm';

export const dynamic = 'force-dynamic';

export default async function PageConnexion() {
  const identite = await currentIdentity(newCorrelationId()).catch(() => null);
  if (identite) redirect('/');

  return (
    <main className="ops-login-page">
      <div className="ops-login-atmosphere" aria-hidden="true">
        <span className="ops-login-orbit ops-login-orbit-one" />
        <span className="ops-login-orbit ops-login-orbit-two" />
        <span className="ops-login-globe" />
      </div>

      <p className="ops-login-kicker">
        PLUS PROCHES<br />DE VOS OPÉRATIONS<br />PARTOUT SUR LE TERRAIN
      </p>

      <section className="ops-login-brand" aria-labelledby="ops-login-title">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/brand/dallytrading-logo.png" alt="DallyTrading" width={640} height={460} />
        <h1 id="ops-login-title">Dally Ops</h1>
        <p>L’application terrain de vos opérations</p>
      </section>

      <LoginForm />

      <section className="ops-login-benefits" aria-label="Avantages Dally Ops">
        <div><span className="tone-blue">✓</span><strong>Des opérations<br />sécurisées</strong></div>
        <div><span className="tone-green">▮▮▮</span><strong>Une meilleure<br />fluidité terrain</strong></div>
        <div><span className="tone-purple">●●●</span><strong>Des équipes<br />toujours connectées</strong></div>
      </section>

      <p className="ops-login-signature">ENSEMBLE, PLUS LOIN</p>
    </main>
  );
}
