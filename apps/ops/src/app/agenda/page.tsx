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

  return (
    <main className="ops-operation-page ops-agenda-page">
      <Link className="retour ops-back-link" href="/">← Accueil</Link>
      <header className="ops-operation-heading">
        <span className="ops-operation-heading-icon tone-blue" aria-hidden="true">▦</span>
        <div>
          <p className="ops-eyebrow">PLANNING</p>
          {/* Le titre visuel n'est pas un titre de document : l'agenda porte
              deja son <h1> « AGENDA », restyle en etiquette. Deux elements de
              titre pour une page dupliqueraient le nom accessible. */}
          <p className="ops-visual-title">Agenda</p>
          <p>Organiser les passages et rendez-vous de l’équipe.</p>
        </div>
      </header>
      <Agenda />
    </main>
  );
}
