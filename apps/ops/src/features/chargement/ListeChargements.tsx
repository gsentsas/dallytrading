import Link from 'next/link';

import type { DepartChargement } from '@/lib/ops/loading';
import { LIBELLE_MODE, enJour, enRoute } from '@/features/reception/format';

import { departComplet, resteALire, resumeLisible } from './chargement-vocabulaire';

/**
 * Les départs à préparer, en cartes.
 *
 * Chaque carte répond à une seule question : *où en est ce départ ?* Le compte
 * est donné en clair — « 12 sur 18 colis » — et non en pourcentage : au quai,
 * ce qu'on vérifie, c'est une pile, pas un taux.
 *
 * L'ordre vient du serveur, les collectes qui ferment d'abord. Retrier ici
 * ferait diverger ce que l'opérateur voit de ce que le serveur a décidé.
 */
export function ListeChargements(
  { consolidations }: { consolidations: readonly DepartChargement[] },
) {
  return (
    <>
      {consolidations.map((depart) => {
        const complet = departComplet(depart.summary);
        const reste = resteALire(depart.summary);
        const prevu = enJour(depart.scheduled_departure || null);
        return (
          <section className="carte" key={depart.reference} data-testid="depart-chargement">
            <span className="mode">
              {LIBELLE_MODE[depart.transport_mode] ?? depart.transport_mode}
            </span>
            <p className="reference">{depart.reference}</p>
            <p className="route">{enRoute(depart.origin, depart.destination)}</p>

            <p style={{ margin: '0.4rem 0 0' }} data-testid="depart-compte">
              <strong>{resumeLisible(depart.summary)}</strong>
              {complet ? ' — complet' : ''}
            </p>
            {reste ? (
              <p className="attenue" style={{ margin: 0 }} data-testid="depart-reste">
                {reste}
              </p>
            ) : null}
            <p className="attenue" style={{ margin: 0 }}>{depart.state_label}</p>
            {prevu ? (
              <p className="attenue" style={{ margin: 0 }}>Départ prévu : {prevu}</p>
            ) : null}

            <Link
              className="bouton-lien"
              href={`/chargement/${encodeURIComponent(depart.reference)}`}
            >
              {depart.can_load ? 'Préparer' : 'Consulter'}
            </Link>
          </section>
        );
      })}
    </>
  );
}
