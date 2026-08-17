'use client';

/**
 * Le formulaire de commande.
 *
 * ## Ce qu'il envoie
 *
 * Un mode de remise, et pour un invité son identité. Ni lignes, ni prix, ni
 * identifiant de panier : ceux-là vivent dans le cookie scellé, que le BFF lit.
 * Le formulaire ne décrit donc jamais le contenu de la commande — il ne fait que
 * demander qu'elle soit passée.
 *
 * ## Ce qu'il affiche
 *
 * Le récapitulatif reçu du serveur, déjà tarifé. Rien n'est recalculé ici : un
 * total calculé côté navigateur diverge dès qu'un tarif change entre l'affichage
 * et l'envoi, et le client validerait un montant qui n'est pas celui de sa
 * commande.
 *
 * ## Le client connecté ne saisit rien
 *
 * Son identité vient de sa session, lue par Odoo. Le formulaire ne lui demande
 * donc pas son nom : le lui demander laisserait croire qu'il peut le changer ici,
 * et l'envoyer serait refusé par le serveur.
 */

import { useState } from 'react';
import Link from 'next/link';

import { formatPrice } from './ui';
import type { CartView } from '@/lib/shop/dto';
import type { DeliveryMode, ShopOrder } from '@/lib/shop/checkout-schema';

type Etat =
  | { phase: 'saisie' }
  | { phase: 'envoi' }
  | { phase: 'confirmee'; commande: ShopOrder }
  | { phase: 'refus'; code: string; message: string };

const MODES: ReadonlyArray<{ value: DeliveryMode; label: string; aide: string }> = [
  {
    value: 'pickup',
    label: 'Retrait sur place',
    aide: 'Vous venez chercher votre commande dans nos locaux. Aucun frais.',
  },
  {
    value: 'delivery_to_confirm',
    label: 'Livraison',
    aide:
      'Nous vous communiquons le coût de la livraison selon la destination, ' +
      'avant toute confirmation. Il n’est pas inclus dans le total ci-dessous.',
  },
];

export function CheckoutForm({
  cart,
  signedIn,
  customerName,
}: {
  cart: CartView;
  signedIn: boolean;
  customerName: string | null;
}) {
  const [mode, setMode] = useState<DeliveryMode>('pickup');
  const [identite, setIdentite] = useState({
    name: '',
    email: '',
    phone: '',
    street: '',
    city: '',
    zip: '',
  });
  const [etat, setEtat] = useState<Etat>({ phase: 'saisie' });

  async function envoyer(evenement: React.FormEvent) {
    evenement.preventDefault();
    if (etat.phase === 'envoi') return;
    setEtat({ phase: 'envoi' });

    try {
      const reponse = await fetch('/api/shop/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          deliveryMode: mode,
          // Le bloc n'est envoyé que pour un invité. Un client connecté qui
          // l'enverrait serait refusé par Odoo — c'est là que la règle vit.
          ...(signedIn ? {} : { customer: identite }),
        }),
      });
      const charge = (await reponse.json()) as
        | { success: true; data: { order: ShopOrder } }
        | { success: false; error: { code: string; message: string } };

      if (!reponse.ok || charge.success !== true) {
        const detail = charge.success === false ? charge.error : null;
        setEtat({
          phase: 'refus',
          code: detail?.code ?? 'unavailable',
          message: detail?.message ?? 'La commande n’a pas pu être enregistrée.',
        });
        return;
      }
      setEtat({ phase: 'confirmee', commande: charge.data.order });
    } catch {
      setEtat({
        phase: 'refus',
        code: 'unavailable',
        message: 'La commande n’a pas pu être enregistrée. Merci de réessayer.',
      });
    }
  }

  if (etat.phase === 'confirmee') {
    return <Confirmation commande={etat.commande} />;
  }

  const enCours = etat.phase === 'envoi';

  return (
    <form onSubmit={envoyer} className="grid gap-8 lg:grid-cols-[3fr_2fr]">
      <div>
        {!signedIn && (
          <fieldset className="rounded-xl border border-mist-200 bg-white p-6">
            <legend className="px-2 text-sm font-semibold text-navy-900">
              Vos coordonnées
            </legend>
            <p className="mb-4 text-sm text-mist-600">
              Vous avez déjà un compte ?{' '}
              <Link href="/connexion" className="font-medium text-navy-800 underline">
                Connectez-vous
              </Link>{' '}
              pour retrouver vos commandes dans votre espace client.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Champ
                nom="name" label="Nom complet" requis
                valeur={identite.name}
                onChange={(v) => setIdentite({ ...identite, name: v })}
              />
              <Champ
                nom="email" label="E-mail" type="email" requis
                valeur={identite.email}
                onChange={(v) => setIdentite({ ...identite, email: v })}
              />
              <Champ
                nom="phone" label="Téléphone" type="tel"
                valeur={identite.phone}
                onChange={(v) => setIdentite({ ...identite, phone: v })}
              />
              <Champ
                nom="street" label="Adresse"
                valeur={identite.street}
                onChange={(v) => setIdentite({ ...identite, street: v })}
              />
              <Champ
                nom="city" label="Ville"
                valeur={identite.city}
                onChange={(v) => setIdentite({ ...identite, city: v })}
              />
              <Champ
                nom="zip" label="Code postal"
                valeur={identite.zip}
                onChange={(v) => setIdentite({ ...identite, zip: v })}
              />
            </div>
          </fieldset>
        )}

        {signedIn && (
          <div className="rounded-xl border border-mist-200 bg-white p-6">
            <h2 className="text-sm font-semibold text-navy-900">Vos coordonnées</h2>
            <p className="mt-2 text-mist-600">
              {customerName ?? 'Votre compte'}
            </p>
            <p className="mt-2 text-sm text-mist-500">
              Cette commande sera rattachée à votre compte. Pour modifier vos
              coordonnées,{' '}
              <Link href="/espace-client/profil" className="underline">
                rendez-vous dans votre profil
              </Link>
              .
            </p>
          </div>
        )}

        <fieldset className="mt-6 rounded-xl border border-mist-200 bg-white p-6">
          <legend className="px-2 text-sm font-semibold text-navy-900">
            Mode de remise
          </legend>
          <div className="grid gap-3">
            {MODES.map((option) => (
              <label
                key={option.value}
                className="flex cursor-pointer gap-3 rounded-lg border border-mist-200 p-4 hover:bg-mist-50"
              >
                <input
                  type="radio"
                  name="deliveryMode"
                  value={option.value}
                  checked={mode === option.value}
                  onChange={() => setMode(option.value)}
                  className="mt-1"
                />
                <span>
                  <span className="block font-medium text-navy-900">{option.label}</span>
                  <span className="mt-1 block text-sm text-mist-600">{option.aide}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      <aside className="rounded-xl border border-mist-200 bg-white p-6">
        <h2 className="text-sm font-semibold text-navy-900">Votre commande</h2>
        <ul className="mt-4 divide-y divide-mist-100">
          {cart.lines.map((ligne) => (
            <li key={ligne.reference} className="flex justify-between gap-3 py-3">
              <span className="min-w-0 text-sm text-navy-900">
                {ligne.name}
                <span className="block text-mist-500">× {ligne.quantity}</span>
              </span>
              <span className="whitespace-nowrap text-sm font-medium text-navy-900">
                {formatPrice(ligne.subtotal, ligne.currency)}
              </span>
            </li>
          ))}
        </ul>

        <div className="mt-4 border-t border-mist-200 pt-4">
          <div className="flex justify-between font-semibold text-navy-900">
            <span>Total</span>
            <span>{formatPrice(cart.total, cart.currency)}</span>
          </div>
          {/*
            Dire explicitement ce que le total ne contient pas. Aucun frais de
            livraison n'est décidé à ce stade, et un montant « indicatif »
            reviendrait à inventer un tarif.
          */}
          <p className="mt-2 text-xs text-mist-500">
            Hors frais de livraison, communiqués selon la destination.
          </p>
        </div>

        <button
          type="submit"
          disabled={enCours}
          className="mt-6 w-full rounded-lg bg-navy-800 px-5 py-3 text-sm font-semibold text-white hover:bg-navy-900 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {enCours ? 'Enregistrement…' : 'Valider ma commande'}
        </button>

        <p className="mt-3 text-xs text-mist-500">
          Aucun paiement en ligne : nous vous recontactons pour finaliser la
          commande et convenir du règlement.
        </p>

        <p aria-live="polite" className="mt-4 text-sm">
          {etat.phase === 'refus' && (
            <span className="block rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
              {etat.message}
              {etat.code === 'unavailable_products' && (
                <>
                  {' '}
                  <Link href="/boutique/panier" className="font-medium underline">
                    Revoir mon panier
                  </Link>
                </>
              )}
              {etat.code === 'portal_account_exists' && (
                <>
                  {' '}
                  <Link href="/connexion" className="font-medium underline">
                    Se connecter
                  </Link>
                </>
              )}
            </span>
          )}
        </p>
      </aside>
    </form>
  );
}

function Champ({
  nom,
  label,
  valeur,
  onChange,
  type = 'text',
  requis = false,
}: {
  nom: string;
  label: string;
  valeur: string;
  onChange: (valeur: string) => void;
  type?: string;
  requis?: boolean;
}) {
  return (
    <label className="flex flex-col text-sm font-medium text-navy-900">
      {label}
      {requis && <span className="sr-only"> (requis)</span>}
      {requis && <span aria-hidden="true"> *</span>}
      <input
        name={nom}
        type={type}
        required={requis}
        value={valeur}
        onChange={(evenement) => onChange(evenement.target.value)}
        className="mt-1 rounded-lg border border-mist-300 px-3 py-2 font-normal text-navy-900"
      />
    </label>
  );
}

/**
 * La confirmation.
 *
 * Dit explicitement que rien n'est confirmé côté vendeur : la commande est un
 * brouillon que le personnel reprend. Laisser croire à une commande ferme
 * créerait une attente que rien ne tient.
 */
function Confirmation({ commande }: { commande: ShopOrder }) {
  return (
    <div className="rounded-xl border border-green-200 bg-green-50 p-8">
      <h2 className="text-xl font-semibold text-green-900">
        Votre demande de commande est enregistrée
      </h2>
      <p className="mt-3 text-green-900">
        Référence : <strong data-testid="order-reference">{commande.reference}</strong>
      </p>
      <p className="mt-4 text-sm text-green-900">
        Nos équipes vérifient la disponibilité et vous recontactent pour confirmer
        la commande, le coût de la remise et les modalités de règlement. Aucun
        paiement n’a été demandé ni enregistré.
      </p>

      <dl className="mt-6 grid gap-2 text-sm text-green-900">
        <div className="flex justify-between">
          <dt>Mode de remise</dt>
          <dd>{commande.deliveryModeLabel}</dd>
        </div>
        <div className="flex justify-between">
          <dt>Articles</dt>
          <dd>{commande.lines.length}</dd>
        </div>
        <div className="flex justify-between font-semibold">
          <dt>Total</dt>
          <dd>{formatPrice(commande.amountTotal, commande.currency)}</dd>
        </div>
      </dl>

      <Link
        href="/boutique"
        className="mt-6 inline-flex rounded-lg bg-navy-800 px-5 py-2.5 text-sm font-semibold text-white hover:bg-navy-900"
      >
        Retour à la boutique
      </Link>
    </div>
  );
}
