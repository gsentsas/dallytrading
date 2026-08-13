import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { OdooGateway } from './gateway';
import { OdooGatewayError, type ServiceType } from './types';
import { setOdooGatewayForTests } from './index';
import {
  getServiceCatalogue,
  invalidateServiceCatalogue,
  primeServiceCatalogue,
} from './catalogue-cache';

/**
 * The catalogue cache is what stands between "Odoo is the source of truth" and
 * "the quote form is down whenever Odoo hiccups". These tests pin both halves:
 * it must not hammer Odoo, and it must not fail the page when a usable copy
 * exists.
 */

function service(code: string, sortOrder = 10): ServiceType {
  return {
    code,
    name: code,
    description: '',
    active: true,
    sort_order: sortOrder,
    requires_origin: false,
    requires_destination: false,
    requires_weight: false,
    requires_volume: false,
    requires_vehicle: false,
    requires_budget: false,
    requires_goods: false,
  };
}

/** Minimal gateway double: only listServiceTypes is exercised here. */
function fakeGateway(
  listServiceTypes: OdooGateway['listServiceTypes'],
): OdooGateway {
  const notUsed = () => {
    throw new Error('not used in these tests');
  };
  return {
    listServiceTypes,
    createLead: notUsed as unknown as OdooGateway['createLead'],
    createQuoteRequest: notUsed as unknown as OdooGateway['createQuoteRequest'],
    createSourcingRequest:
      notUsed as unknown as OdooGateway['createSourcingRequest'],
    getShipmentByTracking:
      notUsed as unknown as OdooGateway['getShipmentByTracking'],
    healthCheck: notUsed as unknown as OdooGateway['healthCheck'],
  };
}

describe('getServiceCatalogue', () => {
  beforeEach(() => {
    invalidateServiceCatalogue();
  });

  afterEach(() => {
    setOdooGatewayForTests(null);
    invalidateServiceCatalogue();
    vi.useRealTimers();
  });

  it('fetches from the gateway on a cold cache', async () => {
    const list = vi.fn().mockResolvedValue([service('freight_sea')]);
    setOdooGatewayForTests(fakeGateway(list));

    const result = await getServiceCatalogue('cid-1');

    expect(list).toHaveBeenCalledTimes(1);
    expect(result.stale).toBe(false);
    expect(result.services.map((s) => s.code)).toEqual(['freight_sea']);
  });

  it('serves a fresh cache without calling the gateway again', async () => {
    const list = vi.fn().mockResolvedValue([service('freight_sea')]);
    setOdooGatewayForTests(fakeGateway(list));

    await getServiceCatalogue('cid-1');
    await getServiceCatalogue('cid-2');
    await getServiceCatalogue('cid-3');

    expect(list).toHaveBeenCalledTimes(1);
  });

  it('refetches once the TTL has elapsed', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-12T10:00:00Z'));

    const list = vi.fn().mockResolvedValue([service('freight_sea')]);
    setOdooGatewayForTests(fakeGateway(list));

    await getServiceCatalogue('cid-1');
    vi.setSystemTime(new Date('2026-08-12T10:06:00Z')); // TTL is 5 minutes
    await getServiceCatalogue('cid-2');

    expect(list).toHaveBeenCalledTimes(2);
  });

  it('shares one in-flight fetch between concurrent callers', async () => {
    // A cold cache under load must not become a stampede against Odoo.
    let resolveList: (value: ServiceType[]) => void = () => {};
    const list = vi.fn().mockReturnValue(
      new Promise<ServiceType[]>((resolve) => {
        resolveList = resolve;
      }),
    );
    setOdooGatewayForTests(fakeGateway(list));

    const calls = Promise.all([
      getServiceCatalogue('cid-1'),
      getServiceCatalogue('cid-2'),
      getServiceCatalogue('cid-3'),
    ]);
    resolveList([service('freight_sea')]);
    const results = await calls;

    expect(list).toHaveBeenCalledTimes(1);
    expect(results.every((result) => result.services.length === 1)).toBe(true);
  });

  it('serves a stale copy when the gateway fails', async () => {
    primeServiceCatalogue([service('freight_sea')], Date.now() - 10 * 60 * 1000);
    setOdooGatewayForTests(
      fakeGateway(vi.fn().mockRejectedValue(
        new OdooGatewayError('unavailable', 'down', 504),
      )),
    );

    const result = await getServiceCatalogue('cid-1');

    expect(result.stale).toBe(true);
    expect(result.services.map((s) => s.code)).toEqual(['freight_sea']);
  });

  it('throws when the gateway fails and no copy is held', async () => {
    // Deliberately no hardcoded fallback list: it would be the second business
    // list this design removes, and would offer withdrawn services.
    setOdooGatewayForTests(
      fakeGateway(vi.fn().mockRejectedValue(
        new OdooGatewayError('unavailable', 'down', 504),
      )),
    );

    await expect(getServiceCatalogue('cid-1')).rejects.toThrow();
  });

  it('throws when the held copy is older than the stale window', async () => {
    primeServiceCatalogue(
      [service('freight_sea')], Date.now() - 48 * 60 * 60 * 1000,
    );
    setOdooGatewayForTests(
      fakeGateway(vi.fn().mockRejectedValue(
        new OdooGatewayError('unavailable', 'down', 504),
      )),
    );

    await expect(getServiceCatalogue('cid-1')).rejects.toThrow();
  });

  it('treats an empty catalogue as a failure rather than caching it', async () => {
    // An empty list would render a form with no service to choose; the likeliest
    // cause is a misconfiguration, not a company that offers nothing.
    setOdooGatewayForTests(fakeGateway(vi.fn().mockResolvedValue([])));

    await expect(getServiceCatalogue('cid-1')).rejects.toThrow();
  });

  it('does not cache a failure', async () => {
    const list = vi
      .fn()
      .mockRejectedValueOnce(new OdooGatewayError('unavailable', 'down', 504))
      .mockResolvedValueOnce([service('freight_sea')]);
    setOdooGatewayForTests(fakeGateway(list));

    await expect(getServiceCatalogue('cid-1')).rejects.toThrow();
    const result = await getServiceCatalogue('cid-2');

    expect(result.services.map((s) => s.code)).toEqual(['freight_sea']);
    expect(list).toHaveBeenCalledTimes(2);
  });
});
