import type { Metadata } from 'next';

import { ProfileEditor } from '@/features/portal/ProfileEditor';
import { PageHeader, UnavailableState } from '@/features/portal/ui';
import { loadPortal } from '@/features/portal/load';
import { getProfile } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Profil' };
export const dynamic = 'force-dynamic';

/**
 * Profil — lecture Odoo puis édition via la mutation dédiée.
 *
 * La page reste un Server Component dynamique : chaque navigation/rechargement
 * relit Odoo. Seul le formulaire interactif est envoyé au navigateur, avec la
 * projection déjà validée et aucun identifiant technique.
 */
export default async function ProfilePage() {
  const profile = await loadPortal(() => getProfile(newCorrelationId()));

  if (!profile) {
    return (
      <>
        <PageHeader title="Profil" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Profil"
        description="Vos coordonnées telles qu’enregistrées chez DallyTrading."
      />

      <ProfileEditor initialProfile={profile} />
    </>
  );
}
