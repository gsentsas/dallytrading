/** Lecture serveur des méthodes de remise configurées dans Odoo. */

import { getServerEnv } from '@/lib/env';
import { logger } from '@/lib/logger';
import {
  deliveryMethodsEnvelopeSchema,
  type DeliveryMethod,
} from './delivery';

export class ShopDeliveryGatewayError extends Error {
  constructor(readonly code: 'misconfigured' | 'unavailable' | 'timeout' | 'invalid_response') {
    super(code);
    this.name = 'ShopDeliveryGatewayError';
  }
}

interface Envelope {
  readonly success?: boolean;
  readonly data?: unknown;
}

export class ShopDeliveryGateway {
  async getMethods(correlationId: string): Promise<readonly DeliveryMethod[]> {
    const env = getServerEnv();
    const apiKey = env.ODOO_API_KEY_SHOP_READ;
    if (!apiKey) throw new ShopDeliveryGatewayError('misconfigured');

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), env.ODOO_TIMEOUT_MS);
    try {
      const response = await fetch(
        `${env.ODOO_URL.replace(/\/+$/, '')}/api/v1/shop/delivery-methods`,
        {
          method: 'GET',
          headers: {
            'X-API-Key': apiKey,
            'X-Correlation-Id': correlationId,
          },
          cache: 'no-store',
          signal: controller.signal,
        },
      );
      const text = await response.text();
      let envelope: Envelope | null = null;
      try {
        envelope = text ? (JSON.parse(text) as Envelope) : null;
      } catch {
        throw new ShopDeliveryGatewayError('invalid_response');
      }
      if (!response.ok || envelope?.success !== true) {
        throw new ShopDeliveryGatewayError('unavailable');
      }
      const parsed = deliveryMethodsEnvelopeSchema.safeParse(envelope.data);
      if (!parsed.success) {
        logger.error('Shop delivery methods failed their contract', {
          correlationId,
          issues: String(parsed.error),
        });
        throw new ShopDeliveryGatewayError('invalid_response');
      }
      return parsed.data.methods;
    } catch (error) {
      if (error instanceof ShopDeliveryGatewayError) throw error;
      const aborted = error instanceof Error && error.name === 'AbortError';
      logger.error('Shop delivery methods call failed', { correlationId, aborted });
      throw new ShopDeliveryGatewayError(aborted ? 'timeout' : 'unavailable');
    } finally {
      clearTimeout(timer);
    }
  }
}
