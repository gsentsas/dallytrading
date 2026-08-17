'use client';

/**
 * Le bouton « ajouter au panier ».
 *
 * Le seul composant client de la boutique, et pour une raison précise : il doit
 * refléter l'état du panier sans recharger la page. Tout le reste de la vitrine
 * est rendu côté serveur.
 *
 * ## Ce qu'il envoie
 *
 * Une référence et une quantité. Il ne connaît ni prix, ni identifiant de panier,
 * ni identifiant de produit — il n'a rien d'autre à envoyer, et c'est ce qui rend
 * inutile de valider ce qu'il enverrait.
 *
 * ## Ce qu'il ne fait pas
 *
 * Il ne tient pas de copie locale du panier. La réponse du serveur est la seule
 * source affichée : un compteur maintenu côté navigateur divergerait dès qu'un
 * produit serait dépublié entre deux clics, et le client verrait un panier qui
 * n'existe pas.
 */

import { useState, useTransition } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

type Etat = 'repos' | 'ajoute' | 'refuse' | 'panne';

export function AddToCart({
  reference,
  disabled = false,
}: {
  reference: string;
  disabled?: boolean;
}) {
  const [quantite, setQuantite] = useState(1);
  const [etat, setEtat] = useState<Etat>('repos');
  const [enCours, setEnCours] = useState(false);
  const [, demarrerTransition] = useTransition();
  const router = useRouter();

  async function ajouter() {
    setEnCours(true);
    setEtat('repos');
    try {
      const reponse = await fetch('/api/shop/cart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // `same-origin` explicitement : le cookie du panier est indispensable, et
        // le rendre implicite laisserait la requête dépendre du défaut du
        // navigateur.
        credentials: 'same-origin',
        body: JSON.stringify({ reference, quantity: quantite }),
      });
      if (!reponse.ok) {
        // 404 et 422 disent tous deux « cet ajout n'est pas possible ». On ne les
        // distingue pas à l'écran : la différence n'aiderait pas le client, et
        // elle lui apprendrait si une référence existe.
        setEtat(reponse.status >= 500 ? 'panne' : 'refuse');
        return;
      }
      setEtat('ajoute');
      // Rafraîchir la page serveur pour que le compteur d'en-tête et la page
      // panier reflètent l'ajout, sans que ce composant ait à connaître leur
      // existence.
      demarrerTransition(() => router.refresh());
    } catch {
      setEtat('panne');
    } finally {
      setEnCours(false);
    }
  }

  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-sm font-medium text-navy-900">
          Quantité
          <input
            type="number"
            min={1}
            max={999}
            value={quantite}
            onChange={(evenement) => {
              const valeur = Number.parseInt(evenement.target.value, 10);
              // Borné ici comme côté serveur. Le contrôle du navigateur est un
              // confort d'usage, jamais la protection : `min`/`max` sur un input
              // se contourne en une ligne de console.
              setQuantite(
                Number.isFinite(valeur) ? Math.min(Math.max(valeur, 1), 999) : 1,
              );
            }}
            className="mt-1 w-24 rounded-lg border border-mist-300 px-3 py-2 text-navy-900"
          />
        </label>

        <button
          type="button"
          onClick={ajouter}
          disabled={disabled || enCours}
          className="rounded-lg bg-navy-800 px-5 py-2.5 text-sm font-semibold text-white hover:bg-navy-900 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {enCours ? 'Ajout…' : 'Ajouter au panier'}
        </button>
      </div>

      {/* `aria-live` : l'ajout ne change pas la page visuellement ailleurs, donc
          un lecteur d'écran n'aurait aucune façon d'apprendre qu'il a eu lieu. */}
      <p aria-live="polite" className="mt-3 text-sm">
        {etat === 'ajoute' && (
          <span className="text-green-800">
            Ajouté au panier.{' '}
            <Link href="/boutique/panier" className="font-medium underline">
              Voir le panier
            </Link>
          </span>
        )}
        {etat === 'refuse' && (
          <span className="text-amber-900">
            Cet article n’a pas pu être ajouté.
          </span>
        )}
        {etat === 'panne' && (
          <span className="text-amber-900">
            La boutique est momentanément indisponible.
          </span>
        )}
      </p>
    </div>
  );
}
