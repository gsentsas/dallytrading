import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { LoginForm } from '@/features/auth/LoginForm';

export const dynamic = 'force-dynamic';

export default async function PageConnexion() {
  // Une session encore valide n'a pas à repasser par le formulaire.
  const identite = await currentIdentity(newCorrelationId()).catch(() => null);
  if (identite) redirect('/');

  return (
    <main>
      <h1>Dally Ops</h1>
      <p className="attenue">Application terrain des opérations.</p>
      <LoginForm />
    </main>
  );
}
