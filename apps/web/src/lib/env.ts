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

  /** Milliseconds before an Odoo call is abandoned. */
  ODOO_TIMEOUT_MS: z.coerce.number().int().positive().max(120_000).default(15_000),
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
