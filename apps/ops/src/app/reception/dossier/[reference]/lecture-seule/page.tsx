import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { ChargeurFicheLectureSeule } from '@/features/reception/ChargeurFicheLectureSeule';

export const dynamic = 'force-dynamic';

/**
 * La fiche d'un dossier repris, en lecture seule.
 *
 * ## Pourquoi une page distincte de la fiche native
 *
 * Ce ne sont pas les mêmes données ni les mêmes droits. Une page unique qui
 * choisirait son affichage selon l'origine porterait deux contrats et deux
 * domaines de sécurité, et le jour où l'un durcirait, l'autre suivrait mal.
 *
 * ## Ce que cette page n'importe pas
 *
 * Aucun composant de mutation. Ils n'existent pas dans l'arbre rendu : il n'y
 * a donc rien à désactiver, et rien qui puisse être réactivé par mégarde.
 *
 * ## Ce que cette page ne fait plus
 *
 * Elle n'appelle plus Odoo. Le rendu serveur court-circuitait le BFF : le
 * parcours réel n'était donc pas débité, et deux chemins de lecture
 * coexistaient. La page ne porte plus que l'identité, la capacité et la
 * référence ; la lecture passe par `/api/intakes/<ref>/legacy-detail`.
 */
export default async function PageDossierLectureSeule({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const correlationId = newCorrelationId();
  // Pas de `.catch(() => null)` ici : `currentIdentity` rend `null` quand la
  // session manque ou qu'Odoo la refuse, et **lève** pour tout le reste.
  // Avaler cette levée transformait une panne du back en déconnexion, et
  // renvoyait vers l'écran de connexion un opérateur qui n'avait rien perdu.
  // L'erreur remonte donc, et c'est l'absence de session — elle seule — qui
  // conduit à `/connexion`.
  const identite = await currentIdentity(correlationId);
  if (!identite) redirect('/connexion');
  // La même capacité que `/recherche`, d'où l'on vient : cette fiche en est
  // le prolongement en lecture. `intake_create` serait un autre droit — celui
  // d'enregistrer une réception — et rien ici n'écrit.
  if (identite.capabilities.intake_search !== true) redirect('/');

  const { reference } = await params;

  return (
    <main>
      <Link className="retour" href="/recherche">← Recherche</Link>
      <h1>DOSSIER {reference}</h1>
      <ChargeurFicheLectureSeule reference={reference} />
    </main>
  );
}
