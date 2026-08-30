import Link from 'next/link';

import type { ActivityItem } from '@/lib/ops/activity';

/**
 * L'heure telle que le serveur l'a comptée.
 *
 * Le fuseau vient de la charge utile, jamais du navigateur : c'est avec
 * celui-là que la journée a été bornée côté serveur, et un écran qui
 * choisirait le sien afficherait autour de minuit des heures appartenant à un
 * autre jour que celui annoncé en titre.
 */
function heure(value: string, timeZone: string): string {
  try {
    return new Intl.DateTimeFormat('fr-FR', {
      hour: '2-digit', minute: '2-digit', hour12: false, timeZone,
    }).format(new Date(value));
  } catch {
    // Un fuseau inconnu du navigateur ne doit pas vider la timeline.
    return new Intl.DateTimeFormat('fr-FR', {
      hour: '2-digit', minute: '2-digit', hour12: false,
      timeZone: 'Africa/Dakar',
    }).format(new Date(value));
  }
}

export function ActivityTimeline({
  events,
  timezone,
  empty = 'Aucune activité confirmée.',
}: {
  readonly events: readonly ActivityItem[];
  readonly timezone: string;
  readonly empty?: string;
}) {
  if (events.length === 0) return <p className="attenue">{empty}</p>;

  return (
    <ol className="timeline-activite">
      {events.map((event) => (
        <li
          className="carte activite"
          key={`${event.occurred_at}:${event.event}:${event.actor}:${event.summary}`}
        >
          <time dateTime={event.occurred_at}>
            {heure(event.occurred_at, timezone)}
          </time>
          <div>
            <strong className="acteur">{event.actor}</strong>
            {event.dossier_label && event.dossier_reference ? (
              <Link
                className="dossier-activite"
                href={`/reception/dossier/${encodeURIComponent(event.dossier_reference)}`}
              >
                {event.dossier_label}
              </Link>
            ) : null}
            <p className="libelle-activite">{event.label}</p>
            {event.summary ? <p className="resume-activite">{event.summary}</p> : null}
            {event.changes.map((change) => (
              <p className="correction-activite" key={change.field}>
                <span>{change.label}</span>{' '}
                {change.old_value} → {change.new_value}
              </p>
            ))}
          </div>
        </li>
      ))}
    </ol>
  );
}
