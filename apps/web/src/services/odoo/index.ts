/**
 * Gateway entry point.
 *
 * Application code imports `getOdooGateway()` and never a concrete adapter.
 * Swapping the protocol is then a change to `ODOO_GATEWAY_ADAPTER` in `.env`,
 * with no code change anywhere else — which is the whole point of ADR-008.
 */

import { getServerEnv } from '@/lib/env';
import { DallyApiAdapter } from './dally-api.adapter';
import { Json2Adapter } from './json2.adapter';
import { LegacyRpcAdapter } from './legacy-rpc.adapter';
import type { OdooGateway } from './gateway';

let instance: OdooGateway | null = null;

/**
 * Return the configured gateway.
 *
 * Cached per process: the adapter holds only configuration, so building it on
 * every request would just re-read and re-validate the environment.
 */
export function getOdooGateway(): OdooGateway {
  if (instance) {
    return instance;
  }

  const { ODOO_GATEWAY_ADAPTER } = getServerEnv();

  switch (ODOO_GATEWAY_ADAPTER) {
    case 'dally_api':
      instance = new DallyApiAdapter();
      break;
    case 'json2':
      instance = new Json2Adapter();
      break;
    case 'legacy_rpc':
      instance = new LegacyRpcAdapter();
      break;
    default: {
      // Unreachable while the env schema constrains the value, but an
      // exhaustiveness check means adding an adapter to the enum without
      // wiring it here is a compile error rather than a runtime surprise.
      const unexpected: never = ODOO_GATEWAY_ADAPTER;
      throw new Error(`Unsupported ODOO_GATEWAY_ADAPTER: ${String(unexpected)}`);
    }
  }

  return instance;
}

/** Replace the gateway. Test-only. */
export function setOdooGatewayForTests(gateway: OdooGateway | null): void {
  instance = gateway;
}

export type { OdooGateway } from './gateway';
export * from './types';
