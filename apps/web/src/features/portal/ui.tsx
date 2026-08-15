/**
 * Petits composants partagés par les pages du portail.
 *
 * Server Components : rien ici n'a d'état ni d'interaction. Les marquer `'use
 * client'` par habitude enverrait ce code au navigateur pour rien.
 *
 * Aucun nouveau système de design : les classes reprennent la charte existante du
 * site (navy / mist / green), afin que l'espace client ressemble à DallyTrading et
 * non à une application greffée.
 */

import Link from 'next/link';

export function PageHeader({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <header className="mb-6">
      <h1 className="text-2xl font-bold text-navy-900 sm:text-3xl">{title}</h1>
      {description && <p className="mt-2 text-mist-600">{description}</p>}
    </header>
  );
}

/**
 * État vide.
 *
 * Ne dit jamais « aucun résultat trouvé pour votre recherche » : il n'y a pas de
 * recherche, et cette formulation laisserait croire qu'un dossier pourrait exister
 * ailleurs. Un client sans devis n'a pas de devis, c'est tout.
 */
export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-mist-300 bg-white p-8 text-center">
      <p className="text-mist-600">{children}</p>
    </div>
  );
}

/**
 * Panne de l'ERP.
 *
 * Ne montre ni le code d'erreur, ni l'URL Odoo, ni l'identifiant de corrélation.
 * Ce dernier existe dans les journaux serveur, où le support le retrouve ; sur la
 * page, il n'aiderait personne et cartographierait notre infrastructure.
 */
export function UnavailableState() {
  return (
    <div
      role="alert"
      className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-900"
    >
      <p className="font-semibold">Service momentanément indisponible</p>
      <p className="mt-2 text-sm">
        Vos données n’ont pas pu être chargées. Merci de réessayer dans quelques
        instants.
      </p>
    </div>
  );
}

export function StatusBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex rounded-full bg-mist-100 px-3 py-1 text-xs font-medium text-navy-800">
      {label}
    </span>
  );
}

export function Detail({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  const shown =
    value === null || value === undefined || value === '' ? '—' : String(value);
  return (
    <div>
      <dt className="text-sm text-mist-600">{label}</dt>
      <dd className="mt-1 font-medium text-navy-800">{shown}</dd>
    </div>
  );
}

export function Card({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-mist-300 bg-white p-6 ${className}`}>
      {children}
    </section>
  );
}

/**
 * Pagination précédent / suivant.
 *
 * Deux liens, pas des boutons : ce sont des navigations, elles doivent
 * fonctionner au clic du milieu, en nouvel onglet, et sans JavaScript. Un
 * `<button onClick={router.push}>` casse les trois.
 *
 * La borne courante est désactivée en la rendant comme un `<span>` plutôt qu'un
 * lien inerte — un lien qui ne mène nulle part reste focalisable et annoncé.
 */
export function Pagination({
  basePath,
  page,
  total,
  pageSize,
}: {
  basePath: string;
  page: number;
  total: number;
  pageSize: number;
}) {
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  if (lastPage <= 1) return null;

  const linkClass =
    'rounded-lg border border-mist-300 px-4 py-2 text-sm font-medium text-navy-800 hover:bg-mist-100';
  const mutedClass =
    'rounded-lg border border-mist-200 px-4 py-2 text-sm text-mist-400';

  return (
    <nav
      aria-label="Pagination"
      className="mt-6 flex items-center justify-between gap-4"
    >
      {page > 1 ? (
        <Link href={`${basePath}?page=${page - 1}`} className={linkClass} rel="prev">
          Page précédente
        </Link>
      ) : (
        <span className={mutedClass}>Page précédente</span>
      )}

      <p aria-live="polite" className="text-sm text-mist-600">
        Page {page} sur {lastPage}
      </p>

      {page < lastPage ? (
        <Link href={`${basePath}?page=${page + 1}`} className={linkClass} rel="next">
          Page suivante
        </Link>
      ) : (
        <span className={mutedClass}>Page suivante</span>
      )}
    </nav>
  );
}

/**
 * Tableau lisible sur mobile.
 *
 * Le conteneur défile horizontalement plutôt que de laisser la page entière le
 * faire : un tableau large qui pousse le `body` rend tout le site bancal sur
 * téléphone, y compris la navigation.
 */
export function TableWrapper({ children }: { children: React.ReactNode }) {
  return <div className="overflow-x-auto">{children}</div>;
}
