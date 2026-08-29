'use client';

import { useCallback, useEffect, useState } from 'react';

import { cleProprietaireLocale, synchroniserMaintenant } from '@/lib/offline/client';
import { mutationsDe, reessayer } from '@/lib/offline/queue';
import { LIBELLES_ETAT, LIBELLES_OPERATION } from '@/lib/offline/types';
import type { MutationLocale } from '@/lib/offline/types';

/** « 29 août, 14:05 » — assez pour retrouver une saisie dans sa journée. */
const QUAND = new Intl.DateTimeFormat('fr-FR', {
  day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit',
});

/**
 * L'écran de synchronisation.
 *
 * Il montre ce que le CRM n'a pas encore confirmé, et pourquoi. Aucun détail
 * technique : un code HTTP ou un nom de modèle ne dit rien à un logisticien et
 * l'empêcherait de voir ce qui, lui, est actionnable.
 */
export function EcranSync() {
  const [lignes, setLignes] = useState<MutationLocale[] | null>(null);
  const [occupe, setOccupe] = useState(false);

  // L'opérateur est lu dans la base locale, pas demandé au serveur : cet
  // écran doit s'ouvrir précisément quand le serveur est injoignable.
  const lire = useCallback(async () => {
    const cle = await cleProprietaireLocale();
    return cle ? mutationsDe(cle) : [];
  }, []);

  const rafraichir = useCallback(async () => {
    setLignes(await lire());
  }, [lire]);

  useEffect(() => {
    // La lecture est asynchrone et l'écran peut disparaître entre-temps : le
    // drapeau évite d'écrire dans un composant démonté.
    let vivant = true;
    lire()
      .then((valeurs) => { if (vivant) setLignes(valeurs); })
      .catch(() => undefined);
    return () => { vivant = false; };
  }, [lire]);

  async function synchroniser() {
    setOccupe(true);
    try {
      const cle = await cleProprietaireLocale();
      if (cle) await synchroniserMaintenant(cle);
      await rafraichir();
    } finally {
      setOccupe(false);
    }
  }

  async function relancer(localId: string) {
    await reessayer(localId);
    await synchroniser();
  }

  if (!lignes) return <p className="attenue">Lecture des opérations…</p>;

  const enCours = lignes.filter((m) => m.status !== 'synced');
  const terminees = lignes.filter((m) => m.status === 'synced');

  return (
    <>
      <button type="button" onClick={() => void synchroniser()} disabled={occupe}>
        {occupe ? 'Synchronisation…' : 'SYNCHRONISER MAINTENANT'}
      </button>

      {enCours.length === 0 ? (
        <p className="attenue" data-testid="file-vide" style={{ marginTop: '1rem' }}>
          Aucune opération en attente.
        </p>
      ) : (
        enCours.map((mutation) => (
          <section className="carte" key={mutation.local_id} data-testid="operation-file">
            <strong>{LIBELLES_OPERATION[mutation.operation_type]}</strong>
            <p className="attenue" style={{ margin: '0.2rem 0 0' }}>
              {QUAND.format(new Date(mutation.created_at))}
            </p>
            {mutation.resume ? (
              <p style={{ margin: '0.2rem 0 0' }}>{mutation.resume}</p>
            ) : null}
            <p
              className={mutation.status === 'error' || mutation.status === 'blocked'
                ? 'alerte' : 'attenue'}
              style={{ margin: '0.3rem 0 0' }}
              data-testid={`etat-${mutation.status}`}
            >
              {LIBELLES_ETAT[mutation.status]}
            </p>
            {mutation.last_error_message && mutation.status !== 'pending' ? (
              <p className="attenue" style={{ margin: '0.2rem 0 0' }}>
                {mutation.last_error_message}
              </p>
            ) : null}
            {mutation.status === 'error' ? (
              <button
                type="button"
                className="secondaire"
                style={{ marginTop: '0.6rem' }}
                onClick={() => void relancer(mutation.local_id)}
              >
                RÉESSAYER
              </button>
            ) : null}
          </section>
        ))
      )}

      {terminees.length > 0 ? (
        <>
          <h2 style={{ fontSize: '1.1rem', margin: '1.25rem 0 0.5rem' }}>
            SYNCHRONISÉES
          </h2>
          {terminees.map((mutation) => (
            <section className="carte" key={mutation.local_id} data-testid="operation-synchronisee">
              <strong>{LIBELLES_OPERATION[mutation.operation_type]}</strong>
              {mutation.server_reference ? (
                <p className="reference" style={{ margin: '0.2rem 0 0' }}>
                  {mutation.server_reference}
                </p>
              ) : null}
              <p className="attenue" style={{ margin: '0.2rem 0 0' }}>
                ✓ {LIBELLES_ETAT.synced}
              </p>
            </section>
          ))}
        </>
      ) : null}
    </>
  );
}
