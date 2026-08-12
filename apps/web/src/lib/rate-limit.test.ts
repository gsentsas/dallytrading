import { afterEach, describe, expect, it, vi } from 'vitest';
import { checkRateLimit, getClientIp, resetRateLimits } from './rate-limit';

describe('checkRateLimit', () => {
  afterEach(() => {
    resetRateLimits();
    vi.useRealTimers();
  });

  it('allows requests up to the limit', () => {
    for (let i = 0; i < 5; i += 1) {
      expect(checkRateLimit('ip-a', 5, 60_000).allowed).toBe(true);
    }
  });

  it('blocks the request past the limit', () => {
    for (let i = 0; i < 5; i += 1) {
      checkRateLimit('ip-b', 5, 60_000);
    }
    const blocked = checkRateLimit('ip-b', 5, 60_000);
    expect(blocked.allowed).toBe(false);
    expect(blocked.remaining).toBe(0);
    expect(blocked.retryAfterSeconds).toBeGreaterThan(0);
  });

  it('counts each key independently', () => {
    for (let i = 0; i < 5; i += 1) {
      checkRateLimit('ip-c', 5, 60_000);
    }
    expect(checkRateLimit('ip-c', 5, 60_000).allowed).toBe(false);
    // One visitor exhausting their budget must not affect anyone else.
    expect(checkRateLimit('ip-d', 5, 60_000).allowed).toBe(true);
  });

  it('reports the remaining budget', () => {
    expect(checkRateLimit('ip-e', 3, 60_000).remaining).toBe(2);
    expect(checkRateLimit('ip-e', 3, 60_000).remaining).toBe(1);
    expect(checkRateLimit('ip-e', 3, 60_000).remaining).toBe(0);
  });

  it('resets after the window elapses', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-12T10:00:00Z'));

    for (let i = 0; i < 5; i += 1) {
      checkRateLimit('ip-f', 5, 60_000);
    }
    expect(checkRateLimit('ip-f', 5, 60_000).allowed).toBe(false);

    vi.setSystemTime(new Date('2026-08-12T10:01:01Z'));
    expect(checkRateLimit('ip-f', 5, 60_000).allowed).toBe(true);
  });

  it('does not reset before the window elapses', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-12T10:00:00Z'));

    for (let i = 0; i < 2; i += 1) {
      checkRateLimit('ip-g', 2, 60_000);
    }
    vi.setSystemTime(new Date('2026-08-12T10:00:59Z'));
    expect(checkRateLimit('ip-g', 2, 60_000).allowed).toBe(false);
  });
});

describe('getClientIp', () => {
  it('takes the first entry of X-Forwarded-For', () => {
    // nginx appends, so the originating client is first.
    const headers = new Headers({ 'x-forwarded-for': '41.82.1.5, 10.0.0.1' });
    expect(getClientIp(headers)).toBe('41.82.1.5');
  });

  it('trims whitespace', () => {
    const headers = new Headers({ 'x-forwarded-for': '  41.82.1.5  ' });
    expect(getClientIp(headers)).toBe('41.82.1.5');
  });

  it('falls back to X-Real-IP', () => {
    const headers = new Headers({ 'x-real-ip': '41.82.1.9' });
    expect(getClientIp(headers)).toBe('41.82.1.9');
  });

  it('returns "unknown" when no header is present', () => {
    // Must not throw: a missing header would otherwise take down the endpoint.
    expect(getClientIp(new Headers())).toBe('unknown');
  });
});
