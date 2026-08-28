'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import type { Client, ResultatRecherche } from '@/lib/ops/customers';
import {
  CHIFFRES_MINIMUM,
  emailUtilisable,
  telephoneUtilisable,
} from '@/features/reception/telephone';

type Mode = 'phone' | 'email';
type Etat =
  | { nom: 'saisie' }
  | { nom: 'recherche' }
  | { nom: 'trouve'; client: Client }
  | { nom: 'introuvable' }
  | { nom: 'ambigu' }
  | { nom: 'erreur'; message: string };

/**
 * Identifier le client au comptoir.
 *
 * ## Pourquoi un bouton et non une recherche à la frappe
 *
 * Chercher à chaque touche enverrait `7`, `77`, `771`, `7712`… au serveur :
 * autant de requêtes, autant de lignes de journal, et un préfixe court est
 * exactement ce qu'on refuse de chercher. Un bouton rend aussi le geste
 * prévisible sur un téléphone tenu d'une main.
 *
 * ## Pourquoi pas de champ « nom »
 *
 * Parce qu'il n'existe pas côté serveur, et pour deux raisons qui tiennent
 * ensemble : les homonymes sont courants, et une recherche par nom est un
 * moyen de feuilleter le fichier clients.
 */
export function RechercheClient({ consolidation }: { consolidation: string }) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>('phone');
  const [valeur, setValeur] = useState('');
  const [etat, setEtat] = useState<Etat>({ nom: 'saisie' });

  const utilisable = mode === 'phone' ? telephoneUtilisable(valeur) : emailUtilisable(valeur);

  function changerDeMode(nouveau: Mode) {
    setMode(nouveau);
    setValeur('');
    setEtat({ nom: 'saisie' });
  }

  async function chercher(evenement: FormEvent<HTMLFormElement>) {
    evenement.preventDefault();
    if (!utilisable) {
      setEtat({
        nom: 'erreur',
        message: mode === 'phone'
          ? `Numéro incomplet : ${CHIFFRES_MINIMUM} chiffres au minimum.`
          : 'Adresse e-mail incomplète.',
      });
      return;
    }

    setEtat({ nom: 'recherche' });
    try {
      const reponse = await fetch('/api/customers/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          mode === 'phone' ? { phone: valeur.trim() } : { email: valeur.trim() },
        ),
      });

      if (reponse.status === 401) {
        router.replace('/connexion');
        return;
      }

      const charge = (await reponse.json().catch(() => null)) as
        | { success?: boolean; data?: ResultatRecherche; error?: string }
        | null;

      if (!reponse.ok || !charge?.success || !charge.data) {
        setEtat({ nom: 'erreur', message: charge?.error ?? 'Recherche impossible.' });
        return;
      }

      if (charge.data.status === 'match') setEtat({ nom: 'trouve', client: charge.data.customer });
      else if (charge.data.status === 'ambiguous') setEtat({ nom: 'ambigu' });
      else setEtat({ nom: 'introuvable' });
    } catch {
      setEtat({ nom: 'erreur', message: 'Service momentanément indisponible.' });
    }
  }

  if (etat.nom === 'trouve') {
    const client = etat.client;
    return (
      <section className="carte" data-testid="client-trouve">
        <span className="mode">Client trouvé</span>
        <p className="route">{client.name}</p>
        {client.phone ? <p className="attenue" style={{ margin: 0 }}>{client.phone}</p> : null}
        {client.email ? <p className="attenue" style={{ margin: 0 }}>{client.email}</p> : null}
        {client.address ? <p className="attenue" style={{ margin: 0 }}>{client.address}</p> : null}

        <button
          type="button"
          style={{ marginTop: '1rem' }}
          onClick={() => {
            // Seule la référence opaque voyage. Ni nom, ni téléphone, ni
            // adresse ne doivent apparaître dans une barre d'adresse.
            const cible = new URLSearchParams({
              consolidation,
              customer: client.reference,
            });
            router.push(`/reception/colis?${cible.toString()}`);
          }}
        >
          Utiliser ce client
        </button>
        <button
          type="button"
          className="secondaire"
          style={{ marginTop: '0.6rem' }}
          onClick={() => {
            setEtat({ nom: 'saisie' });
            setValeur('');
          }}
        >
          Ce n’est pas le bon client
        </button>
      </section>
    );
  }

  return (
    <>
      <form onSubmit={chercher} noValidate>
        {etat.nom === 'erreur' ? (
          <p className="erreur" role="alert">{etat.message}</p>
        ) : null}

        {etat.nom === 'ambigu' ? (
          // Aucune identité affichée : deux fiches veulent dire qu'on ignore
          // laquelle est devant le comptoir.
          <p className="erreur" role="alert" data-testid="ambigu">
            Plusieurs fiches correspondent. Vérifiez les coordonnées du client ou
            demandez une correction au responsable.
          </p>
        ) : null}

        {mode === 'phone' ? (
          <label htmlFor="phone">
            Numéro de téléphone
            <input
              id="phone"
              name="phone"
              type="tel"
              inputMode="tel"
              autoComplete="off"
              placeholder="+221 77 123 45 67"
              value={valeur}
              onChange={(evenement) => setValeur(evenement.target.value)}
            />
          </label>
        ) : (
          <label htmlFor="email">
            Adresse e-mail
            <input
              id="email"
              name="email"
              type="email"
              inputMode="email"
              autoComplete="off"
              autoCapitalize="none"
              placeholder="client@example.com"
              value={valeur}
              onChange={(evenement) => setValeur(evenement.target.value)}
            />
          </label>
        )}

        <button type="submit" disabled={etat.nom === 'recherche'}>
          {etat.nom === 'recherche' ? 'Recherche…' : 'Rechercher'}
        </button>
      </form>

      <button
        type="button"
        className="secondaire"
        style={{ marginTop: '0.75rem' }}
        onClick={() => changerDeMode(mode === 'phone' ? 'email' : 'phone')}
      >
        {mode === 'phone' ? 'Rechercher par e-mail' : 'Rechercher par téléphone'}
      </button>

      {etat.nom === 'introuvable' ? (
        <section className="carte" style={{ marginTop: '1rem' }} data-testid="introuvable">
          <strong>Aucun client trouvé.</strong>
          <button
            type="button"
            style={{ marginTop: '0.9rem' }}
            onClick={() => {
              const cible = new URLSearchParams({ consolidation });
              router.push(`/reception/client/nouveau?${cible.toString()}`);
            }}
          >
            Créer un nouveau client
          </button>
        </section>
      ) : null}
    </>
  );
}
