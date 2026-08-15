import type { Metadata } from 'next';

import { Card, Detail, PageHeader, UnavailableState } from '@/features/portal/ui';
import { loadPortal } from '@/features/portal/load';
import { getProfile } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Profil' };
export const dynamic = 'force-dynamic';

/**
 * Profil — lecture seule, et strictement ce que `/me` renvoie.
 *
 * Aucun bouton de modification : la modification est un cycle à part entière. Une
 * mutation demande un contrôle d'origine, une revalidation, une règle d'écriture
 * Odoo (le portail n'a aujourd'hui que `perm_read`), et de décider quels champs
 * un client peut changer lui-même. Poser le bouton d'abord et brancher ensuite,
 * c'est la façon habituelle d'obtenir un formulaire qui écrit sans contrôle.
 *
 * Absents de la projection, donc de cette page : groupes, `company_id` technique,
 * identifiants internes, encours autorisé, propriétés comptables.
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

      <Card>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Detail label="Nom" value={profile.name} />
          <Detail label="Société" value={profile.company} />
          <Detail label="E-mail" value={profile.email} />
          <Detail label="Téléphone" value={profile.phone} />
          <Detail label="Ville" value={profile.city} />
          <Detail label="Pays" value={profile.country} />
        </dl>
      </Card>

      <p className="mt-4 text-sm text-mist-600">
        Pour faire corriger une information, contactez votre interlocuteur
        DallyTrading.
      </p>
    </>
  );
}
