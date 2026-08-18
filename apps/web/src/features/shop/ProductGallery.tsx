'use client';

/**
 * La galerie de la fiche produit.
 *
 * `'use client'` est nécessaire ici et nulle part ailleurs dans la vitrine :
 * changer de photo est une interaction, et c'est la seule de cette page. Le
 * catalogue reste entièrement rendu côté serveur.
 *
 * ## Une piste de défilement, pas deux implémentations
 *
 * Le mobile veut un balayage, le bureau une grande image et des vignettes. On
 * pourrait écrire deux composants ; on écrit une piste horizontale à
 * `scroll-snap`, qui **est** déjà un balayage sur mobile, et que les vignettes
 * pilotent sur bureau. Le geste tactile est alors celui du navigateur : pas de
 * gestion de `touchstart`, pas de seuil de vélocité à régler, pas de conflit
 * avec le défilement vertical de la page.
 *
 * L'index actif est déduit de la position de défilement plutôt que maintenu en
 * double : après un balayage, un état séparé aurait à être resynchronisé, et
 * c'est exactement là que ce genre de composant se désaccorde.
 *
 * ## Ce qui reste vrai sans JavaScript
 *
 * Le rendu serveur contient déjà toutes les photos dans la piste. Sans
 * hydratation, la page affiche la première et reste défilable : on perd les
 * boutons et la synchronisation des vignettes, pas les images.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import type { ShopProductDetail } from '@/lib/shop/dto';
import { SHOP_IMAGE_DIMENSIONS } from '@/lib/shop/image';
import { photoPrecedente, photoSuivante, photosDuProduit } from './gallery';

export function ProductGallery({
  product,
}: {
  product: Pick<ShopProductDetail, 'reference' | 'imageVersion' | 'gallery' | 'name'>;
}) {
  const photos = photosDuProduit(product);
  const piste = useRef<HTMLDivElement>(null);
  const [actif, setActif] = useState(0);

  const allerA = useCallback((index: number) => {
    const noeud = piste.current;
    if (!noeud) return;
    noeud.scrollTo({ left: index * noeud.clientWidth, behavior: 'smooth' });
    // Optimiste : le défilement fluide met du temps, et attendre l'événement
    // laisserait la vignette cliquée sans retour visuel pendant ce temps-là.
    setActif(index);
  }, []);

  useEffect(() => {
    const noeud = piste.current;
    if (!noeud) return;
    const surDefilement = () => {
      const largeur = noeud.clientWidth || 1;
      setActif(Math.round(noeud.scrollLeft / largeur));
    };
    noeud.addEventListener('scroll', surDefilement, { passive: true });
    return () => noeud.removeEventListener('scroll', surDefilement);
  }, []);

  if (photos.length === 0) {
    return <SubstitutPhoto />;
  }

  const { width, height } = SHOP_IMAGE_DIMENSIONS.detail;
  const plusieurs = photos.length > 1;

  return (
    <section aria-label="Photos du produit" className="mb-8">
      <div className="relative">
        <div
          ref={piste}
          className="flex snap-x snap-mandatory overflow-x-auto rounded-xl bg-mist-50 [scrollbar-width:none] [&::-webkit-scrollbar]{display:none}"
        >
          {photos.map((photo) => (
            <div
              key={photo.token}
              className="w-full shrink-0 snap-center"
              data-testid="photo-produit"
            >
              {/*
                Un <img> simple, comme la marque et la tuile : ces images
                arrivent déjà redimensionnées par Odoo sous une URL immuable,
                et l'optimiseur de next/image n'ajouterait qu'un cache devant
                un cache.

                La première photo est chargée avec empressement — c'est la plus
                grande image visible au chargement de la fiche, et la retarder
                se voit. Les suivantes sont paresseuses : personne ne les
                regarde tant qu'il n'a pas fait défiler.
              */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={photo.detail}
                alt=""
                aria-hidden="true"
                width={width}
                height={height}
                loading={photo === photos[0] ? 'eager' : 'lazy'}
                decoding="async"
                className="aspect-[4/3] w-full object-cover"
              />
            </div>
          ))}
        </div>

        {plusieurs && (
          <>
            <BoutonNavigation
              cote="gauche"
              onClick={() => allerA(photoPrecedente(actif, photos.length))}
            />
            <BoutonNavigation
              cote="droite"
              onClick={() => allerA(photoSuivante(actif, photos.length))}
            />
          </>
        )}
      </div>

      {plusieurs && (
        <>
          {/*
            Vignettes sur écran large, points sur mobile. Deux rendus du même
            état, et non deux états : `actif` pilote les deux, si bien qu'un
            balayage met à jour les points comme les vignettes.
          */}
          <ul className="mt-3 hidden gap-2 sm:flex" data-testid="vignettes">
            {photos.map((photo, index) => (
              <li key={photo.token}>
                <button
                  type="button"
                  onClick={() => allerA(index)}
                  aria-current={index === actif ? 'true' : undefined}
                  aria-label={`Photo ${index + 1} sur ${photos.length}`}
                  className={`block overflow-hidden rounded-lg border-2 transition ${
                    index === actif
                      ? 'border-navy-800'
                      : 'border-transparent hover:border-mist-300'
                  }`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={photo.card}
                    alt=""
                    aria-hidden="true"
                    width={80}
                    height={80}
                    loading="lazy"
                    decoding="async"
                    className="h-20 w-20 object-cover"
                  />
                </button>
              </li>
            ))}
          </ul>

          <ol className="mt-3 flex justify-center gap-2 sm:hidden" data-testid="indicateurs">
            {photos.map((photo, index) => (
              <li key={photo.token}>
                <button
                  type="button"
                  onClick={() => allerA(index)}
                  aria-current={index === actif ? 'true' : undefined}
                  aria-label={`Photo ${index + 1} sur ${photos.length}`}
                  className={`block h-2 w-2 rounded-full ${
                    index === actif ? 'bg-navy-800' : 'bg-mist-300'
                  }`}
                />
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

function BoutonNavigation({
  cote,
  onClick,
}: {
  cote: 'gauche' | 'droite';
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={cote === 'gauche' ? 'Photo précédente' : 'Photo suivante'}
      className={`absolute top-1/2 -translate-y-1/2 rounded-full bg-white/90 p-2 text-navy-900 shadow hover:bg-white ${
        cote === 'gauche' ? 'left-2' : 'right-2'
      }`}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="h-5 w-5"
        aria-hidden="true"
      >
        <path
          d={cote === 'gauche' ? 'M15 6l-6 6 6 6' : 'M9 6l6 6-6 6'}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}

/**
 * Aucune photo.
 *
 * Même dessin et mêmes proportions que le substitut du catalogue : la fiche
 * garde son allure, et le visiteur ne se demande pas si quelque chose a raté.
 */
function SubstitutPhoto() {
  return (
    <div
      className="mb-8 flex aspect-[4/3] w-full items-center justify-center rounded-xl border border-dashed border-mist-300 bg-mist-50"
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className="h-12 w-12 text-mist-400"
      >
        <path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z" strokeLinejoin="round" />
        <path d="M3 7.5 12 12m0 0 9-4.5M12 12v9" strokeLinejoin="round" />
      </svg>
    </div>
  );
}
