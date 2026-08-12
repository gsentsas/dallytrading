/**
 * In-process rate limiter for public form endpoints (§54).
 *
 * ## Scope, stated plainly
 *
 * This is a first line of defence, not the defence. It holds counters in the
 * memory of a single Node process, which means:
 *
 * - it resets on deploy or restart;
 * - it does not coordinate across processes, so `N` instances allow `N × limit`;
 * - it cannot absorb a real flood — the traffic still reaches Node.
 *
 * It exists because it is free and it stops the common case: one visitor
 * double-clicking, or a naive script hammering the quote form. Volumetric
 * protection belongs at the reverse proxy, and nginx `limit_req` needs a
 * `limit_req_zone` in the `http` block — which Plesk's per-domain "additional
 * directives" field cannot reach, since that is injected into the `server` block.
 * It therefore requires a root-owned file in /etc/nginx/conf.d/. That step is
 * documented in docs/DEPLOYMENT.md and is not yet applied.
 */

interface Bucket {
  count: number;
  /** Epoch ms at which the window resets. */
  resetAt: number;
}

const buckets = new Map<string, Bucket>();

/** Highest number of tracked keys, so the map cannot grow without bound. */
const MAX_TRACKED_KEYS = 10_000;

export interface RateLimitResult {
  readonly allowed: boolean;
  readonly remaining: number;
  /** Seconds until the window resets. Suitable for a Retry-After header. */
  readonly retryAfterSeconds: number;
}

/**
 * Consume one unit from a key's budget.
 *
 * @param key Identifier to limit on, typically the client IP.
 * @param limit Requests allowed per window.
 * @param windowMs Window length in milliseconds.
 */
export function checkRateLimit(
  key: string,
  limit = 5,
  windowMs = 60_000,
): RateLimitResult {
  const now = Date.now();

  // Opportunistic sweep of expired entries. Cheap, and avoids a background timer
  // that would keep the process alive.
  if (buckets.size > MAX_TRACKED_KEYS) {
    for (const [existingKey, bucket] of buckets) {
      if (bucket.resetAt <= now) {
        buckets.delete(existingKey);
      }
    }
    // Still oversized: the sweep found nothing expired, so drop everything
    // rather than leak memory. Being briefly permissive beats exhausting RAM.
    if (buckets.size > MAX_TRACKED_KEYS) {
      buckets.clear();
    }
  }

  const bucket = buckets.get(key);

  if (!bucket || bucket.resetAt <= now) {
    buckets.set(key, { count: 1, resetAt: now + windowMs });
    return { allowed: true, remaining: limit - 1, retryAfterSeconds: 0 };
  }

  if (bucket.count >= limit) {
    return {
      allowed: false,
      remaining: 0,
      retryAfterSeconds: Math.max(1, Math.ceil((bucket.resetAt - now) / 1000)),
    };
  }

  bucket.count += 1;
  return {
    allowed: true,
    remaining: limit - bucket.count,
    retryAfterSeconds: 0,
  };
}

/**
 * Best-effort client IP.
 *
 * Reads X-Forwarded-For, which nginx sets. The value is only trustworthy because
 * our own proxy overwrites what the client sent; the first entry is taken as the
 * originating address. If this app were ever exposed without that proxy, the
 * header would be attacker-controlled and this limiter trivially bypassable.
 */
export function getClientIp(headers: Headers): string {
  const forwarded = headers.get('x-forwarded-for');
  if (forwarded) {
    const first = forwarded.split(',')[0]?.trim();
    if (first) {
      return first;
    }
  }
  return headers.get('x-real-ip')?.trim() ?? 'unknown';
}

/** Clear all counters. Test-only. */
export function resetRateLimits(): void {
  buckets.clear();
}
