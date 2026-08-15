import Link from 'next/link';

/**
 * Introuvable — la même page pour « n'existe pas » et « ne vous appartient pas ».
 *
 * Le texte est délibérément vague sur la cause. Écrire « ce dossier appartient à
 * un autre client » confirmerait que la référence est valide, ce qui est
 * exactement l'information qu'une tentative d'énumération cherche.
 */
export default function NotFound() {
  return (
    <div className="rounded-xl border border-mist-300 bg-white p-8 text-center">
      <h1 className="text-xl font-bold text-navy-900">Dossier introuvable</h1>
      <p className="mt-3 text-mist-600">
        Cette référence ne correspond à aucun de vos dossiers.
      </p>
      <Link
        href="/espace-client"
        className="mt-6 inline-block rounded-lg bg-green-700 px-5 py-3 font-semibold text-white hover:bg-green-800"
      >
        Retour au tableau de bord
      </Link>
    </div>
  );
}
