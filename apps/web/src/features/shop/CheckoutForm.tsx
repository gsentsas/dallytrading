'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';

import { formatPrice } from './ui';
import type { ShopOrder } from '@/lib/shop/checkout-schema';
import type { DeliveryMethod } from '@/lib/shop/delivery';
import type { CartView } from '@/lib/shop/dto';

type Etat =
  | { phase: 'saisie' }
  | { phase: 'envoi' }
  | { phase: 'confirmee'; commande: ShopOrder }
  | { phase: 'refus'; code: string; message: string };

const IDENTITE_VIDE = {
  name: '', email: '', phone: '', street: '', city: '', zip: '',
};

const LIVRAISON_VIDE = {
  name: '', phone: '', street: '', street2: '', city: '', zip: '', country_code: '',
};

export function CheckoutForm({
  cart,
  signedIn,
  customerName,
  methods,
}: {
  cart: CartView;
  signedIn: boolean;
  customerName: string | null;
  methods: readonly DeliveryMethod[];
}) {
  const [methodCode, setMethodCode] = useState(methods[0]?.code ?? '');
  const [identite, setIdentite] = useState(IDENTITE_VIDE);
  const [adresseDistincte, setAdresseDistincte] = useState(false);
  const [livraison, setLivraison] = useState(LIVRAISON_VIDE);
  const [etat, setEtat] = useState<Etat>({ phase: 'saisie' });

  const method = useMemo(
    () => methods.find((item) => item.code === methodCode) ?? methods[0],
    [methodCode, methods],
  );

  async function envoyer(evenement: React.FormEvent) {
    evenement.preventDefault();
    if (etat.phase === 'envoi' || !method) return;
    setEtat({ phase: 'envoi' });

    try {
      const reponse = await fetch('/api/shop/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          deliveryMode: method.code,
          ...(signedIn ? {} : { customer: identite }),
          ...(method.requiresAddress && adresseDistincte
            ? { shipping: livraison }
            : {}),
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

  if (etat.phase === 'confirmee') return <Confirmation commande={etat.commande} />;
  if (!method) return null;

  const enCours = etat.phase === 'envoi';

  return (
    <form onSubmit={envoyer} className="grid gap-8 lg:grid-cols-[3fr_2fr]">
      <div>
        {!signedIn ? (
          <fieldset className="rounded-xl border border-mist-200 bg-white p-6">
            <legend className="px-2 text-sm font-semibold text-navy-900">Vos coordonnées</legend>
            <p className="mb-4 text-sm text-mist-600">
              Vous avez déjà un compte ?{' '}
              <Link href="/connexion" className="font-medium text-navy-800 underline">Connectez-vous</Link>{' '}
              pour retrouver vos commandes dans votre espace client.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Champ nom="name" label="Nom complet" requis valeur={identite.name} onChange={(v) => setIdentite({ ...identite, name: v })} />
              <Champ nom="email" label="E-mail" type="email" requis valeur={identite.email} onChange={(v) => setIdentite({ ...identite, email: v })} />
              <Champ nom="phone" label="Téléphone" type="tel" valeur={identite.phone} onChange={(v) => setIdentite({ ...identite, phone: v })} />
              <Champ nom="street" label="Adresse" valeur={identite.street} onChange={(v) => setIdentite({ ...identite, street: v })} />
              <Champ nom="city" label="Ville" valeur={identite.city} onChange={(v) => setIdentite({ ...identite, city: v })} />
              <Champ nom="zip" label="Code postal" valeur={identite.zip} onChange={(v) => setIdentite({ ...identite, zip: v })} />
            </div>
          </fieldset>
        ) : (
          <div className="rounded-xl border border-mist-200 bg-white p-6">
            <h2 className="text-sm font-semibold text-navy-900">Vos coordonnées</h2>
            <p className="mt-2 text-mist-600">{customerName ?? 'Votre compte'}</p>
            <p className="mt-2 text-sm text-mist-500">
              Cette commande sera rattachée à votre compte. Pour modifier vos coordonnées,{' '}
              <Link href="/espace-client/profil" className="underline">rendez-vous dans votre profil</Link>.
            </p>
          </div>
        )}

        <fieldset className="mt-6 rounded-xl border border-mist-200 bg-white p-6">
          <legend className="px-2 text-sm font-semibold text-navy-900">Mode de remise</legend>
          <div className="grid gap-3">
            {methods.map((option) => (
              <label key={option.code} className="flex cursor-pointer gap-3 rounded-lg border border-mist-200 p-4 hover:bg-mist-50">
                <input
                  type="radio"
                  name="deliveryMode"
                  value={option.code}
                  checked={method.code === option.code}
                  onChange={() => {
                    setMethodCode(option.code);
                    setAdresseDistincte(false);
                  }}
                  className="mt-1"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-navy-900">{option.name}</span>
                    <span className="text-sm font-medium text-navy-800">{libelleFrais(option)}</span>
                  </span>
                  {option.help && <span className="mt-1 block text-sm text-mist-600">{option.help}</span>}
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {method.requiresAddress && (
          <fieldset className="mt-6 rounded-xl border border-mist-200 bg-white p-6">
            <legend className="px-2 text-sm font-semibold text-navy-900">Adresse de livraison</legend>
            <p className="text-sm text-mist-600">
              Par défaut, DallyTrading utilise l’adresse de vos coordonnées ou de votre profil.
            </p>
            <label className="mt-4 flex items-center gap-2 text-sm font-medium text-navy-900">
              <input
                type="checkbox"
                checked={adresseDistincte}
                onChange={(e) => setAdresseDistincte(e.target.checked)}
              />
              Livrer à une autre adresse
            </label>
            {adresseDistincte && (
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <Champ nom="shippingName" label="Destinataire" requis valeur={livraison.name} onChange={(v) => setLivraison({ ...livraison, name: v })} />
                <Champ nom="shippingPhone" label="Téléphone" type="tel" valeur={livraison.phone} onChange={(v) => setLivraison({ ...livraison, phone: v })} />
                <Champ nom="shippingStreet" label="Adresse" requis valeur={livraison.street} onChange={(v) => setLivraison({ ...livraison, street: v })} />
                <Champ nom="shippingStreet2" label="Complément" valeur={livraison.street2} onChange={(v) => setLivraison({ ...livraison, street2: v })} />
                <Champ nom="shippingCity" label="Ville" requis valeur={livraison.city} onChange={(v) => setLivraison({ ...livraison, city: v })} />
                <Champ nom="shippingZip" label="Code postal" valeur={livraison.zip} onChange={(v) => setLivraison({ ...livraison, zip: v })} />
                <Champ nom="shippingCountry" label="Code pays" valeur={livraison.country_code} onChange={(v) => setLivraison({ ...livraison, country_code: v.toUpperCase() })} />
              </div>
            )}
          </fieldset>
        )}
      </div>

      <aside className="rounded-xl border border-mist-200 bg-white p-6">
        <h2 className="text-sm font-semibold text-navy-900">Votre commande</h2>
        <ul className="mt-4 divide-y divide-mist-100">
          {cart.lines.map((ligne) => (
            <li key={ligne.reference} className="flex justify-between gap-3 py-3">
              <span className="min-w-0 text-sm text-navy-900">
                {ligne.name}<span className="block text-mist-500">× {ligne.quantity}</span>
              </span>
              <span className="whitespace-nowrap text-sm font-medium text-navy-900">
                {formatPrice(ligne.subtotal, ligne.currency)}
              </span>
            </li>
          ))}
        </ul>

        <dl className="mt-4 space-y-2 border-t border-mist-200 pt-4 text-sm">
          <div className="flex justify-between text-navy-900">
            <dt>Articles</dt><dd>{formatPrice(cart.total, cart.currency)}</dd>
          </div>
          <div className="flex justify-between text-navy-900">
            <dt>Remise</dt><dd>{libelleFrais(method)}</dd>
          </div>
          {method.feePolicy === 'fixed' && method.currency === cart.currency && method.feeAmount !== null && (
            <div className="flex justify-between font-semibold text-navy-900">
              <dt>Total avec remise</dt>
              <dd>{formatPrice(cart.total + method.feeAmount, cart.currency)}</dd>
            </div>
          )}
        </dl>

        {method.feePolicy === 'quote' && (
          <p className="mt-3 rounded-lg bg-mist-50 p-3 text-xs text-mist-600">
            Le coût de la livraison sera confirmé par DallyTrading avant toute préparation.
          </p>
        )}

        <button type="submit" disabled={enCours} className="mt-6 w-full rounded-lg bg-navy-800 px-5 py-3 text-sm font-semibold text-white hover:bg-navy-900 disabled:cursor-not-allowed disabled:opacity-60">
          {enCours ? 'Enregistrement…' : 'Valider ma commande'}
        </button>

        <p className="mt-3 text-xs text-mist-500">
          Aucun paiement en ligne à cette étape. Les frais affichés ou confirmés viennent d’Odoo.
        </p>

        <p aria-live="polite" className="mt-4 text-sm">
          {etat.phase === 'refus' && (
            <span className="block rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
              {etat.message}
              {etat.code === 'unavailable_products' && <>{' '}<Link href="/boutique/panier" className="font-medium underline">Revoir mon panier</Link></>}
              {etat.code === 'portal_account_exists' && <>{' '}<Link href="/connexion" className="font-medium underline">Se connecter</Link></>}
            </span>
          )}
        </p>
      </aside>
    </form>
  );
}

function libelleFrais(method: DeliveryMethod): string {
  if (method.feePolicy === 'free') return 'Sans frais';
  if (method.feePolicy === 'fixed' && method.feeAmount !== null) {
    return formatPrice(method.feeAmount, method.currency);
  }
  return 'Tarif à confirmer';
}

function Champ({
  nom, label, valeur, onChange, type = 'text', requis = false,
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
      {label}{requis && <span aria-hidden="true"> *</span>}
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

function Confirmation({ commande }: { commande: ShopOrder }) {
  const fee = commande.delivery.fee;
  return (
    <div className="rounded-xl border border-green-200 bg-green-50 p-8">
      <h2 className="text-xl font-semibold text-green-900">Votre demande de commande est enregistrée</h2>
      <p className="mt-3 text-green-900">
        Référence : <strong data-testid="order-reference">{commande.reference}</strong>
      </p>
      <p className="mt-4 text-sm text-green-900">
        Nos équipes vérifient la disponibilité et les prochaines étapes. Aucun paiement n’a été demandé ni enregistré.
      </p>

      <dl className="mt-6 grid gap-2 text-sm text-green-900">
        <div className="flex justify-between"><dt>Mode de remise</dt><dd>{commande.deliveryModeLabel}</dd></div>
        <div className="flex justify-between"><dt>Articles</dt><dd>{commande.lines.length}</dd></div>
        <div className="flex justify-between"><dt>Frais de remise</dt><dd>{fee.amount === null ? 'À confirmer' : formatPrice(fee.amount, fee.currency)}</dd></div>
        <div className="flex justify-between font-semibold">
          <dt>{commande.grandTotal === null ? 'Total articles' : 'Total avec remise'}</dt>
          <dd>{formatPrice(commande.grandTotal ?? commande.amountTotal, commande.currency)}</dd>
        </div>
      </dl>

      <Link href="/boutique" className="mt-6 inline-flex rounded-lg bg-navy-800 px-5 py-2.5 text-sm font-semibold text-white hover:bg-navy-900">Retour à la boutique</Link>
    </div>
  );
}
