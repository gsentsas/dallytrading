import Link from 'next/link';

import type { Anomalie, ListeAnomalies } from '@/lib/ops/supervision';

/**
 * Ce qui demande une décision humaine, présenté sans rien y ajouter.
 *
 * ## Ce que cet écran ne calcule pas
 *
 * Rien. Ni la gravité, ni le message, ni le fait qu'une anomalie existe. Un
 * navigateur ne sait pas ce qu'une facture comptabilisée couvre, ni ce qu'un
 * départ exige avant de fermer ; le déduire ici produirait une alerte
 * plausible et fausse, et la fausseté serait invisible.
 *
 * ## Ce qu'il n'affiche jamais
 *
 * Aucun identifiant Odoo — le serveur n'en envoie pas. Aucun message de
 * transport non plus : `operator_message` est rédigé pour la personne qui
 * lit, pas pour un journal.
 */

/** Trois mots pour dire l'urgence. La couleur, elle, appartient à l'écran. */
const LIBELLE_GRAVITE: Record<Anomalie['severity'], string> = {
  high: 'À traiter',
  medium: 'À surveiller',
  low: 'Pour information',
};

const CLASSE_GRAVITE: Record<Anomalie['severity'], string> = {
  high: 'alerte',
  medium: '',
  low: 'attenue',
};

export function ListeAnomalies({ liste }: { readonly liste: ListeAnomalies }) {
  if (liste.anomalies.length === 0) {
    return (
      <p className="attenue" data-testid="aucune-anomalie">
        Rien à traiter pour le moment.
      </p>
    );
  }

  return (
    <>
      <p className="attenue" data-testid="compte-anomalies">
        {liste.total === 1 ? '1 point à traiter' : `${liste.total} points à traiter`}
      </p>

      {liste.truncated ? (
        <p className="attenue" data-testid="liste-tronquee">
          Seuls les {liste.anomalies.length} premiers sont affichés.
        </p>
      ) : null}

      {liste.anomalies.map((anomalie) => (
        <section
          className="carte"
          data-testid="anomalie"
          data-type={anomalie.type}
          key={`${anomalie.type}:${anomalie.reference}`}
        >
          <strong>{anomalie.title}</strong>
          <p className="attenue" style={{ margin: '0.2rem 0 0' }}>
            {anomalie.reference}
          </p>
          <p style={{ margin: '0.35rem 0 0' }}>{anomalie.operator_message}</p>
          <p
            className={CLASSE_GRAVITE[anomalie.severity]}
            style={{ margin: '0.35rem 0 0' }}
          >
            {LIBELLE_GRAVITE[anomalie.severity]}
          </p>

          {/*
            Le lien n'apparaît que si le serveur a nommé un dossier à ouvrir.
            Une projection en peine n'en a pas : y renvoyer l'opérateur
            l'enverrait chercher dans une fiche un incident qui n'y est pas.
          */}
          {anomalie.action === 'open_intake' && anomalie.intake_reference ? (
            <p style={{ margin: '0.5rem 0 0' }}>
              <Link
                href={`/reception/dossier/${encodeURIComponent(anomalie.intake_reference)}`}
              >
                OUVRIR LE DOSSIER
              </Link>
            </p>
          ) : null}
        </section>
      ))}
    </>
  );
}
