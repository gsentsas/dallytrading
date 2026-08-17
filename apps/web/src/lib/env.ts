/**
 * Validated server-side environment.
 *
 * Two reasons this file exists rather than reading `process.env` inline:
 *
 * 1. **Fail at boot, not mid-request.** A missing ODOO_API_KEY should stop the
 *    server from starting, not surface as a 500 on a customer's quote request.
 * 2. **Keep secrets server-side.** This module throws if it is ever evaluated in
 *    a browser bundle, which turns "we accidentally imported env into a client
 *    component" from a silent credential leak into a build failure (§54).
 */

import { z } from 'zod';

// Anything importing this file lands in the server bundle. If that ever stops
// being true, this is where we find out.
if (typeof window !== 'undefined') {
  throw new Error(
    'env.ts was evaluated in the browser. It holds server-only secrets and must ' +
      'never be imported from a client component.',
  );
}

/** Absolute http(s) URL, without relying on a specific zod minor version. */
const httpUrl = z.string().refine(
  (value) => {
    try {
      const parsed = new URL(value);
      return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch {
      return false;
    }
  },
  { message: 'must be an absolute http(s) URL' },
);

const serverEnvSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  ENVIRONMENT: z
    .enum(['development', 'staging', 'production'])
    .default('development'),

  NEXT_PUBLIC_SITE_URL: httpUrl,

  /** Which OdooGateway implementation to use (see services/odoo). */
  ODOO_GATEWAY_ADAPTER: z
    .enum(['dally_api', 'json2', 'legacy_rpc'])
    .default('dally_api'),

  ODOO_URL: httpUrl,
  ODOO_DATABASE: z.string().min(1),

  /**
   * Server-only. 32 bytes of entropy, generated in Odoo. A short value almost
   * always means a placeholder was left in .env.
   */
  ODOO_API_KEY: z
    .string()
    .min(24, 'ODOO_API_KEY looks like a placeholder (fewer than 24 characters)'),

  /**
   * Capability-scoped keys.
   *
   * An Odoo API key is bound to exactly one acting user, whose groups bound what
   * the call can do. ADR-011 gives each capability its own integration user
   * precisely so that a leaked key cannot reach beyond its own endpoints — the
   * leads user carries `group_dally_commercial`, which implies
   * `group_dally_readonly`, the group that gates `internal_notes`.
   *
   * A single key would therefore either be over-privileged or unable to serve the
   * sourcing and trading forms at all: verified on the live instance,
   * `dally_api_integration` has no ACL on `dally.sourcing.request` or
   * `dally.trade.opportunity`.
   *
   * Each is optional and falls back to ODOO_API_KEY, so an instance that has not
   * split its keys yet keeps working — it simply gets whatever the single key can
   * do, and fails with a clear 403 rather than silently escalating.
   */
  ODOO_API_KEY_SOURCING: z.string().min(24).optional(),
  ODOO_API_KEY_TRADE: z.string().min(24).optional(),
  ODOO_API_KEY_TRACKING: z.string().min(24).optional(),

  /** Milliseconds before an Odoo call is abandoned. */
  ODOO_TIMEOUT_MS: z.coerce.number().int().positive().max(120_000).default(15_000),

  /**
   * Server-only. Seals the portal session cookie (AES-256-GCM).
   *
   * Its only job is to make the cookie unforgeable: the cookie carries an Odoo
   * session id, and a client able to mint one would be handing us an identifier
   * we would then present to Odoo as our own.
   *
   * No default and no fallback. A development default would eventually be the
   * production value, because nothing would ever fail to remind us. Rotating it
   * invalidates every open portal session — that is the intended behaviour, not a
   * side effect: it is the only way to revoke them all at once.
   *
   * Generate with: openssl rand -base64 48
   */
  PORTAL_SESSION_SECRET: z
    .string()
    .min(
      32,
      'PORTAL_SESSION_SECRET must be at least 32 characters (openssl rand -base64 48)',
    ),

  /**
   * Server-only. Seals the shop cart cookie (AES-256-GCM).
   *
   * Deliberately **not** PORTAL_SESSION_SECRET, and this is the whole point of
   * the field existing: the two cookies protect things of very different value.
   * The portal cookie carries an authenticated Odoo session; the cart cookie
   * carries an anonymous list of product references. They also have opposite
   * rotation needs — a cart is disposable and can be rotated freely, whereas
   * rotating the portal secret logs every customer out.
   *
   * Sharing one secret would tie those two decisions together, and the direction
   * it would fail in is the bad one: nobody rotates a secret that also signs
   * everyone out, so the cart secret would end up never rotating either.
   *
   * Generate with: openssl rand -base64 48
   */
  SHOP_CART_SECRET: z
    .string()
    .min(
      32,
      'SHOP_CART_SECRET must be at least 32 characters (openssl rand -base64 48)',
    ),

  /**
   * Optional key carrying `shop:read`.
   *
   * Same reasoning as the other capability-scoped keys: the storefront is the
   * most exposed surface of the site, and a key that only renders a public
   * catalogue should not be able to write a lead or read a customer. Falls back
   * to ODOO_API_KEY so an instance that has not split its keys still works.
   */
  ODOO_API_KEY_SHOP: z.string().min(24).optional(),
});

export type ServerEnv = z.infer<typeof serverEnvSchema>;

let cached: ServerEnv | null = null;

/**
 * Parse and cache the environment.
 *
 * Called lazily rather than at module load so that tooling which imports this
 * file (lint, typecheck) does not require a fully populated .env.
 */
export function getServerEnv(): ServerEnv {
  if (cached) {
    return cached;
  }

  const parsed = serverEnvSchema.safeParse(process.env);

  if (!parsed.success) {
    // List every problem at once: fixing .env one error per restart is painful.
    const details = parsed.error.issues
      .map((issue) => `  - ${issue.path.join('.') || '(root)'}: ${issue.message}`)
      .join('\n');
    throw new Error(
      `Invalid server environment. Check .env against .env.example:\n${details}`,
    );
  }

  cached = parsed.data;
  return cached;
}

/** Reset the cache. Test-only. */
export function resetServerEnvCache(): void {
  cached = null;
}
