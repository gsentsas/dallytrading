import Link from 'next/link';

/**
 * Home page — foundation only.
 *
 * Structure, semantics, accessibility and brand tokens are in place; the finished
 * design, imagery and full copy are phase 5. Kept deliberately small so that what
 * is here is correct rather than provisional in ten different ways.
 *
 * Not included, pending confirmation: the "Représentant de SEN CONTAINERS au
 * Sénégal" section described in §35. It makes a public claim about a third party,
 * and the current instruction is to leave every SEN CONTAINERS resource alone —
 * so the wording should be confirmed before it is published.
 */

/** Activities from §33. `href` targets are created in phase 5. */
const ACTIVITIES = [
  {
    title: 'Import & Export',
    description:
      'Accompagnement complet de vos opérations d’importation et d’exportation.',
  },
  {
    title: 'Logistique & Transport',
    description: 'Transport, entreposage et distribution de vos marchandises.',
  },
  {
    title: 'Fret Maritime',
    description: 'Conteneurs complets, groupage et fret conventionnel.',
  },
  {
    title: 'Fret Aérien',
    description: 'Solutions rapides pour vos expéditions urgentes.',
  },
  {
    title: 'Transport de Véhicules',
    description: 'Acheminement de voitures, utilitaires et engins.',
  },
  {
    title: 'Groupage',
    description: 'Partage de conteneur pour les volumes réduits.',
  },
  {
    title: 'Commerce & Trading',
    description: 'Négoce, courtage et représentation commerciale.',
  },
  {
    title: 'Sourcing International',
    description: 'Recherche de fournisseurs et de produits, négociation.',
  },
  {
    title: 'Agrobusiness',
    description: 'Produits agricoles : sourcing, conditionnement et export.',
  },
] as const;

export default function HomePage() {
  return (
    <>
      <header className="bg-navy-700 text-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          <p className="text-lg font-bold tracking-tight">
            DALLYTRADING
            <span className="sr-only">
              {' '}
              — Import, Export, Logistique, Solutions
            </span>
          </p>
          <p
            className="hidden text-xs tracking-[0.2em] text-navy-100 sm:block"
            aria-hidden="true"
          >
            IMPORT • EXPORT • LOGISTICS • SOLUTIONS
          </p>
        </div>
      </header>

      <main id="contenu">
        {/* ─── Hero (§32) ─────────────────────────────────────────── */}
        <section className="bg-navy-700 text-white">
          <div className="mx-auto max-w-6xl px-4 pb-16 pt-10 sm:px-6 sm:pb-24">
            <h1 className="max-w-3xl text-3xl font-bold leading-tight sm:text-4xl lg:text-5xl">
              Votre partenaire pour le commerce, l’import-export et la logistique
            </h1>
            <p className="mt-6 max-w-2xl text-lg text-navy-100">
              DallyTrading accompagne particuliers, commerçants et entreprises dans
              leurs opérations commerciales, logistiques et internationales.
            </p>

            {/* CTA order follows §32: quote first, it is the primary goal. */}
            <div className="mt-10 flex flex-wrap gap-4">
              <Link
                href="/devis"
                className="rounded-lg bg-green-500 px-6 py-3 font-semibold text-white transition-colors hover:bg-green-600"
              >
                Demander un devis
              </Link>
              <Link
                href="/contact"
                className="rounded-lg border border-navy-200 px-6 py-3 font-semibold text-white transition-colors hover:bg-navy-600"
              >
                Parler à un conseiller
              </Link>
              <Link
                href="/tracking"
                className="rounded-lg border border-navy-200 px-6 py-3 font-semibold text-white transition-colors hover:bg-navy-600"
              >
                Suivre mon expédition
              </Link>
            </div>
          </div>
        </section>

        {/* ─── Activities (§33) ───────────────────────────────────── */}
        <section
          aria-labelledby="activites-titre"
          className="mx-auto max-w-6xl px-4 py-16 sm:px-6"
        >
          <h2
            id="activites-titre"
            className="text-2xl font-bold text-navy-800 sm:text-3xl"
          >
            Nos activités
          </h2>
          <p className="mt-3 max-w-2xl text-mist-600">
            Du sourcing à la livraison, nous couvrons l’ensemble de la chaîne
            commerciale et logistique entre le Sénégal et l’international.
          </p>

          <ul className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {ACTIVITIES.map((activity) => (
              <li
                key={activity.title}
                className="rounded-xl border border-mist-200 bg-white p-6 shadow-sm"
              >
                <h3 className="font-semibold text-navy-700">{activity.title}</h3>
                <p className="mt-2 text-sm text-mist-600">{activity.description}</p>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="border-t border-mist-200 bg-white">
        <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
          <p className="font-bold text-navy-700">DALLYTRADING</p>
          <p className="mt-1 text-sm text-mist-600">
            Import • Export • Logistics • Solutions — Dakar, Sénégal
          </p>
          <p className="mt-6 text-xs text-mist-600">
            © {new Date().getFullYear()} DallyTrading. Tous droits réservés.
          </p>
        </div>
      </footer>
    </>
  );
}
