'use client';

/**
 * Dernier filet du sous-arbre portail.
 *
 * `error` n'est PAS affiché. Son message peut contenir un chemin interne, un
 * fragment de réponse Odoo, ou une valeur du client — et sur cette page, il
 * partirait vers le navigateur. Next journalise déjà la trace côté serveur, où
 * elle est utile et où elle reste.
 */
export default function PortalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-900"
    >
      <h1 className="font-semibold">Une erreur est survenue</h1>
      <p className="mt-2 text-sm">
        Vos données n’ont pas pu être affichées. Merci de réessayer.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-4 rounded-lg bg-amber-900 px-4 py-2 text-sm font-semibold text-white"
      >
        Réessayer
      </button>
    </div>
  );
}
