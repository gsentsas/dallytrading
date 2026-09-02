import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { fetchLegacyIntake } from '@/lib/ops/legacy-intake';
import { newCorrelationId } from '@/lib/logger';
import { FicheLectureSeule } from '@/features/reception/FicheLectureSeule';

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
 * La capacité vérifiée est `intake_create`, la même que la fiche native :
 * c'est le droit d'entrer dans le parcours de réception, pas celui d'écrire
 * sur ce dossier-ci — sur lequel personne n'écrit.
 */
export default async function PageDossierLectureSeule({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_create !== true) redirect('/');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  const { reference } = await params;
  const fiche = await fetchLegacyIntake(
    decodeURIComponent(reference), session.odooSessionId, correlationId,
  ).catch(() => null);
  // Un dossier natif, une référence inconnue et une panne se ressemblent ici :
  // dans les trois cas la recherche est le bon point de retour.
  if (!fiche) redirect('/recherche');

  return (
    <main>
      <Link className="retour" href="/recherche">← Recherche</Link>
      <h1>DOSSIER {fiche.local_reference || fiche.reference}</h1>
      <FicheLectureSeule fiche={fiche} />
    </main>
  );
}
