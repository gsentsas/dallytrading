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

      {/*
        * Les trois bénéfices portent les pictogrammes de la maquette — un
        * bouclier, une courbe, une équipe — et non des caractères empruntés à
        * une police, qui se dessinent différemment d'un téléphone à l'autre.
        */}
      <section className="ops-login-benefits" aria-label="Avantages Dally Ops">
        <div>
          <span className="tone-blue" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M12 3.2 19 6v5.4c0 4.2-2.8 7.6-7 9.4-4.2-1.8-7-5.2-7-9.4V6z" /><path d="m8.8 12.1 2.2 2.2 4.2-4.4" /></svg>
          </span>
          <strong>Des opérations<br />sécurisées</strong>
        </div>
        <div>
          <span className="tone-green" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M6.2 18.4v-4.7M12 18.4V7.1M17.8 18.4v-7.6" /></svg>
          </span>
          <strong>Une meilleure<br />fluidité terrain</strong>
        </div>
        <div>
          <span className="tone-purple" aria-hidden="true">
            <svg viewBox="0 0 24 24"><circle cx="9.4" cy="9.2" r="2.7" /><path d="M4.2 18.8c0-2.9 2.3-4.8 5.2-4.8s5.2 1.9 5.2 4.8" /><path d="M16.1 6.9a2.5 2.5 0 0 1 0 4.8M17.1 14.4c2 .5 3 2 3 4.4" /></svg>
          </span>
          <strong>Des équipes<br />toujours connectées</strong>
        </div>
      </section>

      {/* La signature est encadrée de deux filets, comme sur la maquette. */}
      <p className="ops-login-signature"><span>ENSEMBLE, PLUS LOIN</span></p>
    </main>
  );
}
