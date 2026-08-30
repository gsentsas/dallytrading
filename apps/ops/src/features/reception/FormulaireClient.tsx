'use client';

import { useRouter } from 'next/navigation';
import { useRef, useState, type FormEvent } from 'react';

import type { Client, ResultatCreation } from '@/lib/ops/customers';
import { CHIFFRES_MINIMUM, emailUtilisable, telephoneUtilisable } from '@/features/reception/telephone';

type TypeClient = 'individual' | 'business';
type Etat =
  | { nom: 'saisie' }
  | { nom: 'envoi' }
  | { nom: 'abouti'; statut: ResultatCreation['status']; client: Client }
  | { nom: 'erreur'; message: string };

const CHAMPS_VIDES = { name: '', phone: '', email: '', address: '' };

/**
 * Créer un client au comptoir.
 *
 * ## L'identifiant de demande
 *
 * Il est tiré **avant le premier envoi** et conservé tant que la saisie ne
 * change pas. C'est ce qui rend une 4G capricieuse inoffensive : si la réponse
 * se perd et que l'opérateur réappuie, le serveur reconnaît la demande et
 * renvoie le résultat déjà obtenu au lieu de créer une seconde fiche.
 *
 * Modifier un champ le remet à zéro, et c'est voulu : ce n'est plus la même
 * demande. Le rejouer sous le même identifiant serait refusé par le serveur —
 * à juste titre, puisque l'opérateur croirait avoir enregistré ce qu'il vient
 * de corriger.
 */
export function FormulaireClient({
  consolidation = '', onCustomer,
}: {
  consolidation?: string;
  onCustomer?: (customer: Client) => void;
}) {
  const router = useRouter();
  const [type, setType] = useState<TypeClient>('individual');
  const [champs, setChamps] = useState(CHAMPS_VIDES);
  const [etat, setEtat] = useState<Etat>({ nom: 'saisie' });
  const identifiantDemande = useRef<string | null>(null);

  function modifier(champ: keyof typeof CHAMPS_VIDES, valeur: string) {
    setChamps((precedents) => ({ ...precedents, [champ]: valeur }));
    // La saisie a changé : ce n'est plus la même demande.
    identifiantDemande.current = null;
  }

  function changerType(nouveau: TypeClient) {
    setType(nouveau);
    identifiantDemande.current = null;
  }

  function manquant(): string | null {
    if (!champs.name.trim()) {
      return type === 'individual' ? 'Le nom et prénom sont obligatoires.'
                                   : 'La raison sociale est obligatoire.';
    }
    if (!telephoneUtilisable(champs.phone)) {
      return `Numéro incomplet : ${CHIFFRES_MINIMUM} chiffres au minimum.`;
    }
    if (champs.email.trim() && !emailUtilisable(champs.email)) {
      return 'Adresse e-mail incomplète.';
    }
    if (!champs.address.trim()) return 'L’adresse est obligatoire.';
    return null;
  }

  async function enregistrer(evenement: FormEvent<HTMLFormElement>) {
    evenement.preventDefault();
    const probleme = manquant();
    if (probleme) {
      setEtat({ nom: 'erreur', message: probleme });
      return;
    }

    identifiantDemande.current ??= crypto.randomUUID();
    setEtat({ nom: 'envoi' });

    try {
      const reponse = await fetch('/api/customers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_uuid: identifiantDemande.current,
          customer_type: type,
          name: champs.name.trim(),
          phone: champs.phone.trim(),
          ...(champs.email.trim() ? { email: champs.email.trim() } : {}),
          address: champs.address.trim(),
        }),
      });

      if (reponse.status === 401) {
        router.replace('/connexion');
        return;
      }

      const charge = (await reponse.json().catch(() => null)) as
        | { success?: boolean; data?: ResultatCreation; error?: string; code?: string }
        | null;

      if (reponse.status === 409) {
        // La demande précédente a abouti à autre chose : repartir d'un
        // identifiant neuf, sinon toute nouvelle tentative sera refusée.
        if (charge?.code === 'idempotency_conflict') identifiantDemande.current = null;
        setEtat({ nom: 'erreur', message: charge?.error ?? 'Vérification nécessaire.' });
        return;
      }

      if (!reponse.ok || !charge?.success || !charge.data) {
        setEtat({ nom: 'erreur', message: charge?.error ?? 'Enregistrement impossible.' });
        return;
      }

      setEtat({ nom: 'abouti', statut: charge.data.status, client: charge.data.customer });
    } catch {
      // Le réseau a lâché : l'identifiant est conservé, un nouvel appui
      // rejouera la même demande.
      setEtat({ nom: 'erreur', message: 'Service momentanément indisponible.' });
    }
  }

  if (etat.nom === 'abouti') {
    const nouveau = etat.statut === 'created';
    return (
      <section className="carte" data-testid={nouveau ? 'client-cree' : 'client-existant'}>
        <span className="mode">{nouveau ? 'Client créé' : 'Client déjà existant'}</span>
        <p className="route">{etat.client.name}</p>
        {nouveau ? null : (
          <p className="attenue" style={{ margin: 0 }}>La fiche existante a été retrouvée.</p>
        )}
        <button
          type="button"
          style={{ marginTop: '1rem' }}
          onClick={() => {
            if (onCustomer) {
              onCustomer(etat.client);
              return;
            }
            const cible = new URLSearchParams({
              consolidation, customer: etat.client.reference,
            });
            router.push(`/reception/colis?${cible.toString()}`);
          }}
        >
          {nouveau ? 'Continuer vers les colis' : 'Utiliser ce client'}
        </button>
      </section>
    );
  }

  return (
    <form onSubmit={enregistrer} noValidate>
      {etat.nom === 'erreur' ? <p className="erreur" role="alert">{etat.message}</p> : null}

      <fieldset style={{ border: 0, padding: 0, margin: '0 0 1rem' }}>
        <legend className="attenue" style={{ padding: 0 }}>Type de client</legend>
        <div style={{ display: 'flex', gap: '0.6rem', marginTop: '0.4rem' }}>
          {(['individual', 'business'] as const).map((valeur) => (
            <button
              key={valeur}
              type="button"
              className={type === valeur ? undefined : 'secondaire'}
              aria-pressed={type === valeur}
              onClick={() => changerType(valeur)}
            >
              {valeur === 'individual' ? 'Particulier' : 'Professionnel'}
            </button>
          ))}
        </div>
      </fieldset>

      <label htmlFor="name">
        {type === 'individual' ? 'Nom et prénom' : 'Raison sociale'}
        <input
          id="name"
          name="customer_name"
          type="text"
          autoComplete="off"
          value={champs.name}
          onChange={(evenement) => modifier('name', evenement.target.value)}
        />
      </label>

      <label htmlFor="phone">
        Téléphone
        <input
          id="phone"
          name="phone"
          type="tel"
          inputMode="tel"
          autoComplete="off"
          placeholder="+221 77 123 45 67"
          value={champs.phone}
          onChange={(evenement) => modifier('phone', evenement.target.value)}
        />
      </label>

      <label htmlFor="email">
        E-mail (facultatif)
        <input
          id="email"
          name="email"
          type="email"
          inputMode="email"
          autoCapitalize="none"
          autoComplete="off"
          value={champs.email}
          onChange={(evenement) => modifier('email', evenement.target.value)}
        />
      </label>

      <label htmlFor="address">
        Adresse
        <input
          id="address"
          name="address"
          type="text"
          autoComplete="off"
          placeholder="207 rue Saint-Charles, 75015 Paris"
          value={champs.address}
          onChange={(evenement) => modifier('address', evenement.target.value)}
        />
      </label>

      <button type="submit" disabled={etat.nom === 'envoi'}>
        {etat.nom === 'envoi' ? 'Enregistrement…' : 'Enregistrer le client'}
      </button>
    </form>
  );
}
