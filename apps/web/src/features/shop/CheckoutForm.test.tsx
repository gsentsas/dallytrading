import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { CheckoutForm } from './CheckoutForm';
import type { DeliveryMethod } from '@/lib/shop/delivery';
import type { CartView } from '@/lib/shop/dto';

const cart: CartView = {
  lines: [{
    reference: 'article-test',
    name: 'Article test',
    summary: null,
    price: 1000,
    currency: 'XOF',
    stockPolicy: 'on_order',
    stockPolicyLabel: 'Sur commande',
    availability: 'on_order',
    imageVersion: null,
    category: null,
    quantity: 1,
    subtotal: 1000,
  }],
  removed: [],
  itemCount: 1,
  subtotal: 1000,
  currency: 'XOF',
  total: 1000,
  lineCount: 1,
  maxLines: 20,
};

const pickup: DeliveryMethod = {
  code: 'pickup',
  name: 'Retrait sur place',
  kind: 'pickup',
  requiresAddress: false,
  feePolicy: 'free',
  feeAmount: 0,
  currency: 'XOF',
  help: '',
};

const delivery: DeliveryMethod = {
  code: 'delivery_to_confirm',
  name: 'Livraison',
  kind: 'delivery',
  requiresAddress: true,
  feePolicy: 'quote',
  feeAmount: null,
  currency: 'XOF',
  help: 'Tarif à confirmer.',
};

function input(html: string, name: string): string {
  return html.match(new RegExp(`<input[^>]*name="${name}"[^>]*>`))?.[0] ?? '';
}

describe('CheckoutForm — adresse requise', () => {
  it('exige adresse et ville invité quand la livraison utilise les coordonnées', () => {
    const html = renderToStaticMarkup(
      <CheckoutForm
        cart={cart}
        signedIn={false}
        customerName={null}
        methods={[delivery, pickup]}
      />,
    );

    expect(input(html, 'street')).toContain('required');
    expect(input(html, 'city')).toContain('required');
    expect(input(html, 'zip')).not.toContain('required');
  });

  it('ne rend pas adresse et ville obligatoires pour un retrait', () => {
    const html = renderToStaticMarkup(
      <CheckoutForm
        cart={cart}
        signedIn={false}
        customerName={null}
        methods={[pickup, delivery]}
      />,
    );

    expect(input(html, 'street')).not.toContain('required');
    expect(input(html, 'city')).not.toContain('required');
  });
});
