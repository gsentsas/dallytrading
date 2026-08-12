import type { PublicShipment } from '@/services/odoo/types';

/**
 * Presentation of a tracked shipment.
 *
 * A pure server component: it receives the payload the gateway returned and
 * renders it. It performs no filtering of its own — filtering here would mean the
 * data had already left the server, which is exactly the mistake the module's
 * allowlist exists to prevent (§44). Whatever reaches this component is, by
 * construction, publishable.
 */

function formatDate(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit', month: 'long', year: 'numeric',
  }).format(date);
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit', month: 'long', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  }).format(date);
}

export function TrackingResult({ shipment }: { shipment: PublicShipment }) {
  return (
    <section aria-labelledby="resultat-titre" className="mt-10">
      <div className="rounded-xl border border-mist-200 bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 id="resultat-titre" className="text-sm text-mist-600">
              Expédition
            </h2>
            <p className="font-mono text-xl font-bold text-navy-800">
              {shipment.reference}
            </p>
          </div>
          <span className="rounded-full bg-navy-700 px-4 py-1.5 text-sm font-medium text-white">
            {shipment.statusLabel}
          </span>
        </div>

        <dl className="mt-6 grid gap-x-8 gap-y-4 sm:grid-cols-2">
          <Detail label="Mode de transport" value={shipment.transportModeLabel} />
          <Detail label="Trajet"
                  value={
                    shipment.origin && shipment.destination
                      ? `${shipment.origin} → ${shipment.destination}`
                      : (shipment.origin ?? shipment.destination ?? '—')
                  } />
          <Detail label="Départ" value={formatDate(shipment.departureDate)} />
          <Detail
            label={shipment.actualArrival ? 'Arrivée' : 'Arrivée estimée'}
            value={formatDate(shipment.actualArrival ?? shipment.estimatedArrival)}
          />
          {shipment.goodsDescription && (
            <Detail label="Marchandise" value={shipment.goodsDescription} />
          )}
          {shipment.packagesCount > 0 && (
            <Detail label="Colis" value={String(shipment.packagesCount)} />
          )}
          {shipment.containerNumber && (
            <Detail label="Conteneur" value={shipment.containerNumber} mono />
          )}
          {shipment.carrierTrackingNumber && (
            <Detail label="Référence transporteur"
                    value={shipment.carrierTrackingNumber} mono />
          )}
        </dl>

        {shipment.lastUpdate && (
          <p className="mt-6 text-sm text-mist-600">
            Dernière mise à jour : {formatDateTime(shipment.lastUpdate)}
          </p>
        )}
      </div>

      {/* Timeline */}
      <h3 className="mt-10 text-lg font-bold text-navy-800">Suivi</h3>
      {shipment.timeline.length === 0 ? (
        <p className="mt-3 text-mist-600">
          Aucun événement n’a encore été publié pour cette expédition. Le suivi
          s’enrichira au fur et à mesure de son acheminement.
        </p>
      ) : (
        <ol className="mt-4 space-y-0">
          {shipment.timeline.map((event, index) => {
            const isLast = index === shipment.timeline.length - 1;
            return (
              <li key={`${event.date}-${index}`} className="flex gap-4">
                {/* Decorative rail. aria-hidden: the ordered list already conveys
                    the sequence to assistive technology. */}
                <div
                  className="flex flex-col items-center"
                  aria-hidden="true"
                >
                  <span
                    className={`mt-1.5 h-3 w-3 flex-none rounded-full ${
                      isLast ? 'bg-green-500' : 'bg-navy-300'
                    }`}
                  />
                  {!isLast && <span className="w-px flex-1 bg-mist-200" />}
                </div>
                <div className={isLast ? 'pb-2' : 'pb-8'}>
                  <p className="font-medium text-navy-800">
                    {event.description ?? event.statusLabel}
                  </p>
                  <p className="mt-1 text-sm text-mist-600">
                    {formatDateTime(event.date)}
                    {event.location ? ` — ${event.location}` : ''}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function Detail({
  label, value, mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-sm text-mist-600">{label}</dt>
      <dd className={`mt-0.5 text-navy-800 ${mono ? 'font-mono' : ''}`}>
        {value}
      </dd>
    </div>
  );
}
