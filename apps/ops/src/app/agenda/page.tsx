import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { Agenda } from '@/features/agenda/Agenda';

export const dynamic = 'force-dynamic';

export default async function PageAgenda() {
  const identity = await currentIdentity(newCorrelationId()).catch(() => null);
  if (!identity) redirect('/connexion');
  if (identity.capabilities.appointment_manage !== true) redirect('/');
  return <main><Link className="retour" href="/">← Accueil</Link><Agenda /></main>;
}
