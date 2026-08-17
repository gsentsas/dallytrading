'use client';

/**
 * Les lignes du panier, modifiables.
 *
 * Composant client parce qu'une modification de quantité doit se voir sans
 * recharger la page. Il reçoit le panier **déjà tarifé par le serveur** et ne
 * recalcule rien : les sous-totaux et le total affichés viennent d'Odoo.
 *
 * ## Il ne tient pas de copie locale
 *
 * Chaque modification renvoie le panier complet, et c'est cette réponse qui est
 * affichée. Recalculer localement « quantité × prix » serait plus fluide et
 * fabriquerait des montants faux dès qu'un tarif change entre deux clics — ou
 * qu'un produit est dépublié, cas où le serveur retire la ligne et où une copie
 * locale continuerait de la compter.
 */

import { useState } from 'react';
import Link from 'next/link';

import { formatPrice } from './ui';
import type { CartView } from '@/lib/shop/dto';

export function CartLines({ initial }: { initial: CartView }) {
  const [panier, setPanier] = useState<CartView>(initial);
  const [enCours, setEnCours] = useState<string | null>(null);
  const [panne, setPanne] = useState(false);

  async function fixer(reference: string, quantity: number) {
    setEnCours(reference);
    setPanne(false);
    try {
      const reponse = await fetch('/api/shop/cart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ reference, quantity }),
      });
      if (!reponse.ok) {
        setPanne(true);
        return;
      }
      const charge = (await reponse.json()) as { data: CartView };
      setPanier(charge.data);
    } catch {
      setPanne(true);
    } finally {
      setEnCours(null);
    }
  }

  async function vider() {
    setEnCours('*');
    setPanne(false);
    try {
      const reponse = await fetch('/api/shop/cart', {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (!reponse.ok) {
        setPanne(true);
        return;
      }
      const charge = (await reponse.json()) as { data: CartView };
      setPanier(charge.data);
    } catch {
      setPanne(true);
    } finally {
      setEnCours(null);
    }
  }

  if (panier.lines.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-mist-300 bg-white p-10 text-center">
        <p className="text-mist-600">Votre panier est vide.</p>
        <Link
          href="/boutique"
          className="mt-4 inline-flex rounded-lg bg-navy-800 px-5 py-2.5 text-sm font-semibold text-white hover:bg-navy-900"
        >
          Voir le catalogue
        </Link>
      </div>
    );
  }

  return (
    <div>
      {/*
        Les références retirées sont annoncées. Sans ce message, une ligne
        disparaîtrait sans explication et le total ne correspondrait plus à ce
        que le client se rappelle avoir choisi. Le nom du produit n'est pas
        affiché : il n'est plus publié, donc nous n'avons plus à le nommer.
      */}
      {panier.removed.length > 0 && (
        <p
          role="status"
          className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
        >
          {panier.removed.length === 1
            ? 'Un article n’est plus disponible et a été retiré de votre panier.'
            : `${panier.removed.length} articles ne sont plus disponibles et ont été retirés de votre panier.`}
        </p>
      )}

      <ul className="divide-y divide-mist-200 rounded-xl border border-mist-200 bg-white">
        {panier.lines.map((ligne) => (
          <li
            key={ligne.reference}
            className="flex flex-wrap items-center justify-between gap-4 p-5"
          >
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-navy-900">
                <Link href={`/boutique/${ligne.reference}`} className="hover:underline">
                  {ligne.name}
                </Link>
              </p>
              <p className="mt-1 text-sm text-mist-500">
                {formatPrice(ligne.price, ligne.currency)} l’unité ·{' '}
                {ligne.stockPolicyLabel}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <label className="sr-only" htmlFor={`qte-${ligne.reference}`}>
                Quantité pour {ligne.name}
              </label>
              <input
                id={`qte-${ligne.reference}`}
                type="number"
                min={1}
                max={999}
                defaultValue={ligne.quantity}
                disabled={enCours !== null}
                onBlur={(evenement) => {
                  const valeur = Number.parseInt(evenement.target.value, 10);
                  if (!Number.isFinite(valeur) || valeur === ligne.quantity) return;
                  void fixer(ligne.reference, Math.min(Math.max(valeur, 1), 999));
                }}
                className="w-20 rounded-lg border border-mist-300 px-3 py-2 text-navy-900"
              />
              <p className="w-32 text-right font-semibold text-navy-900">
                {formatPrice(ligne.subtotal, ligne.currency)}
              </p>
              <button
                type="button"
                onClick={() => void fixer(ligne.reference, 0)}
                disabled={enCours !== null}
                className="text-sm text-mist-600 underline hover:text-navy-900 disabled:opacity-50"
              >
                Retirer
              </button>
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
        <button
          type="button"
          onClick={() => void vider()}
          disabled={enCours !== null}
          className="text-sm text-mist-600 underline hover:text-navy-900 disabled:opacity-50"
        >
          Vider le panier
        </button>

        <div className="text-right">
          <p className="text-sm text-mist-600">
            {panier.itemCount} article{panier.itemCount > 1 ? 's' : ''}
          </p>
          <p className="text-2xl font-bold text-navy-900">
            {formatPrice(panier.total, panier.currency)}
          </p>
          {/*
            Dire explicitement ce que le total ne contient pas. Aucun frais de
            livraison n'est décidé à ce stade, et afficher un montant provisoire
            « à titre indicatif » reviendrait à inventer un tarif.
          */}
          <p className="mt-1 text-xs text-mist-500">
            Hors frais de livraison, communiqués selon la destination.
          </p>
        </div>
      </div>

      <p aria-live="polite" className="mt-4 text-sm">
        {panne && (
          <span className="text-amber-900">
            Votre panier n’a pas pu être mis à jour. Merci de réessayer.
          </span>
        )}
      </p>
    </div>
  );
}
