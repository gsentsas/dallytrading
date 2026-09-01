'use client';

import {
  useCallback, useEffect, useRef, useState,
  type ChangeEvent, type FormEvent,
} from 'react';

import type { Cliche, ClichesDossier } from '@/lib/ops/photos';

import {
  NATURES,
  cheminPhoto,
  creerSuiviDeGeste,
  dateLisible,
  interpreterEnvoi,
  issueHorsLignePhoto,
  issueReseauPhoto,
  libelleNature,
  naturePardefaut,
  type Nature,
} from './photos-vocabulaire';

/** Ce qu'un appareil photo de téléphone produit. */
const TYPES = 'image/jpeg,image/png,image/webp,image/heic,image/heif';

/**
 * Les preuves photographiques du dossier.
 *
 * ## Deux entrées de fichier, et non une
 *
 * `capture="environment"` ouvre l'appareil photo arrière sans détour — c'est
 * le geste courant au comptoir. Mais sur iOS le même attribut *interdit* la
 * galerie : un opérateur qui a photographié le colis avant d'ouvrir le dossier
 * ne pourrait plus rien envoyer. Deux boutons distincts coûtent une ligne et
 * évitent d'avoir à choisir entre les deux usages.
 *
 * ## L'identifiant du geste
 *
 * Tiré une fois, avant le premier envoi, et conservé tant que rien ne clôt le
 * geste. Une coupure réseau se rejoue donc à l'identique et le serveur
 * reconnaît la reprise. Une nouvelle sélection, un changement de nature, une
 * annulation ou une réussite le terminent — et l'identifiant repart.
 *
 * La clôture est explicite plutôt que déduite du fichier : deux clichés
 * différents peuvent porter le même nom et la même taille, et les confondre
 * ferait passer le second pour un rejeu du premier.
 *
 * ## Ce que l'écran ne décide pas
 *
 * `can_add` et `can_delete` viennent du serveur. Les recalculer ici — d'après
 * l'état du dossier ou le nom de l'auteur — produirait une seconde règle, et
 * l'écran finirait par proposer ce que le serveur refuse.
 */
export function PhotosDossier({
  reference,
  etat,
  peutGerer,
}: {
  reference: string;
  etat: string;
  peutGerer: boolean;
}) {
  const [donnees, setDonnees] = useState<ClichesDossier | null>(null);
  const [chargement, setChargement] = useState(true);
  const [fichier, setFichier] = useState<File | null>(null);
  const [apercu, setApercu] = useState<string | null>(null);
  const [nature, setNature] = useState<Nature>(naturePardefaut(etat));
  const [etatEnvoi, setEtatEnvoi] = useState<
    { nom: 'saisie' } | { nom: 'envoi' } | { nom: 'erreur'; message: string }
  >({ nom: 'saisie' });

  const geste = useRef(creerSuiviDeGeste(() => crypto.randomUUID()));
  const gestesRetrait = useRef<Map<string, string>>(new Map());
  const apercuRef = useRef<string | null>(null);

  /** Une adresse d'objet local libérée dès qu'elle ne montre plus rien. */
  const libererApercu = useCallback(() => {
    if (apercuRef.current) {
      URL.revokeObjectURL(apercuRef.current);
      apercuRef.current = null;
    }
  }, []);

  useEffect(() => libererApercu, [libererApercu]);

  const recharger = useCallback(async () => {
    try {
      const reponse = await fetch(
        `/api/intakes/${encodeURIComponent(reference)}/photos`,
        { cache: 'no-store' });
      const corps = await reponse.json().catch(() => null);
      if (reponse.ok && corps?.success === true) setDonnees(corps.data);
    } finally {
      setChargement(false);
    }
  }, [reference]);

  useEffect(() => { void recharger(); }, [recharger]);

  function choisir(evenement: ChangeEvent<HTMLInputElement>) {
    const choisi = evenement.target.files?.[0] ?? null;
    libererApercu();
    setEtatEnvoi({ nom: 'saisie' });
    // Toute sélection clôt le geste précédent, y compris quand le fichier
    // choisi porte le même nom et la même taille que le précédent.
    geste.current.terminer();
    if (!choisi) {
      setFichier(null);
      setApercu(null);
      return;
    }
    const limite = donnees?.limits.max_file_bytes ?? 10 * 1024 * 1024;
    if (choisi.size > limite) {
      setFichier(null);
      setApercu(null);
      setEtatEnvoi({
        nom: 'erreur',
        message: 'La photo dépasse 10 Mo. Reprenez-la en qualité réduite.',
      });
      return;
    }
    const adresse = URL.createObjectURL(choisi);
    apercuRef.current = adresse;
    setApercu(adresse);
    setFichier(choisi);
  }

  function changerNature(evenement: ChangeEvent<HTMLSelectElement>) {
    // Une autre nature, c'est une autre intention : le serveur la compare.
    geste.current.terminer();
    setNature(evenement.target.value as Nature);
  }

  function annuler() {
    libererApercu();
    setApercu(null);
    setFichier(null);
    geste.current.terminer();
    setEtatEnvoi({ nom: 'saisie' });
  }

  async function envoyer(evenement: FormEvent<HTMLFormElement>) {
    evenement.preventDefault();
    if (!fichier) {
      setEtatEnvoi({ nom: 'erreur', message: 'Choisissez ou prenez une photo.' });
      return;
    }
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      setEtatEnvoi({ nom: 'erreur', message: issueHorsLignePhoto().message });
      return;
    }

    const corps = new FormData();
    corps.append('request_uuid', geste.current.identifiant());
    corps.append('kind', nature);
    corps.append('photo', fichier);

    setEtatEnvoi({ nom: 'envoi' });
    try {
      const reponse = await fetch(
        `/api/intakes/${encodeURIComponent(reference)}/photos`,
        { method: 'POST', body: corps });
      const charge = await reponse.json().catch(() => null);
      const issue = interpreterEnvoi(reponse.ok, charge);
      if (issue.issue === 'ok') {
        annuler();
        await recharger();
        return;
      }
      setEtatEnvoi({ nom: 'erreur', message: issue.message });
    } catch {
      // L'identifiant est conservé : un nouvel appui rejoue le même envoi et
      // ne produit pas une seconde preuve.
      setEtatEnvoi({ nom: 'erreur', message: issueReseauPhoto().message });
    }
  }

  async function retirer(photo: Cliche) {
    let identifiant = gestesRetrait.current.get(photo.photo_uuid);
    if (!identifiant) {
      identifiant = crypto.randomUUID();
      gestesRetrait.current.set(photo.photo_uuid, identifiant);
    }
    try {
      const reponse = await fetch(cheminPhoto(reference, photo.photo_uuid), {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_uuid: identifiant }),
      });
      const charge = await reponse.json().catch(() => null);
      if (reponse.ok && charge?.success === true) {
        gestesRetrait.current.delete(photo.photo_uuid);
        await recharger();
        return;
      }
      setEtatEnvoi({
        nom: 'erreur',
        message: typeof charge?.error === 'string'
          ? charge.error : 'Cette photo n’a pas pu être retirée.',
      });
    } catch {
      setEtatEnvoi({ nom: 'erreur', message: issueReseauPhoto().message });
    }
  }

  if (!peutGerer) return null;

  const photos = donnees?.photos ?? [];

  return (
    <section aria-labelledby="photos-titre" data-testid="photos-dossier">
      <h2 id="photos-titre">PHOTOS</h2>

      {etatEnvoi.nom === 'erreur' ? (
        <p className="erreur" role="alert">{etatEnvoi.message}</p>
      ) : null}

      {chargement ? <p className="attenue">Chargement…</p> : null}

      {!chargement && photos.length === 0 ? (
        <p className="attenue" data-testid="aucune-photo">
          Aucune photo pour ce dossier.
        </p>
      ) : null}

      {photos.map((photo) => (
        <section className="carte" key={photo.photo_uuid} data-testid="photo">
          {/* Lue par la route authentifiée : jamais une adresse de stockage.
              `next/image` est écarté à dessein — son optimiseur irait chercher
              l'image côté serveur, sans le cookie de l'opérateur, et une preuve
              interne n'a pas à être mise en cache par un intermédiaire. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={cheminPhoto(reference, photo.photo_uuid)}
            alt={libelleNature(photo.kind)}
            style={{ width: '100%', height: 'auto', borderRadius: '4px' }}
          />
          <p style={{ margin: '0.4rem 0 0' }}>
            <strong data-testid="photo-nature">{libelleNature(photo.kind)}</strong>
          </p>
          <p className="attenue" style={{ margin: 0 }}>
            <span data-testid="photo-auteur">{photo.created_by}</span>
            {' — '}
            <span data-testid="photo-date">{dateLisible(photo.created_at)}</span>
          </p>
          {photo.can_delete ? (
            <button
              type="button"
              className="secondaire"
              style={{ marginTop: '0.6rem' }}
              onClick={() => { void retirer(photo); }}
            >
              RETIRER CETTE PHOTO
            </button>
          ) : null}
        </section>
      ))}

      {donnees?.can_add ? (
        <form onSubmit={envoyer} noValidate data-testid="formulaire-photo">
          {apercu ? (
            /* Un objet local : il n'y a rien à optimiser, et rien à servir. */
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={apercu}
              alt="Aperçu de la photo à envoyer"
              data-testid="apercu-photo"
              style={{ width: '100%', height: 'auto', borderRadius: '4px' }}
            />
          ) : null}

          <label htmlFor="photo-appareil">
            Prendre une photo
            <input
              id="photo-appareil"
              data-testid="photo-appareil"
              type="file"
              accept={TYPES}
              capture="environment"
              onChange={choisir}
            />
          </label>

          {/* Sans `capture`, iOS rouvre la galerie : les deux usages coexistent. */}
          <label htmlFor="photo-galerie">
            Choisir dans la galerie
            <input
              id="photo-galerie"
              data-testid="photo-galerie"
              type="file"
              accept={TYPES}
              onChange={choisir}
            />
          </label>

          <label htmlFor="photo-nature">
            Nature de la photo
            <select
              id="photo-nature"
              data-testid="choix-nature"
              value={nature}
              onChange={changerNature}
            >
              {NATURES.map((valeur) => (
                <option key={valeur} value={valeur}>{libelleNature(valeur)}</option>
              ))}
            </select>
          </label>

          <button type="submit" disabled={etatEnvoi.nom === 'envoi' || fichier === null}>
            {etatEnvoi.nom === 'envoi' ? 'Envoi…' : 'ENVOYER LA PHOTO'}
          </button>
          {fichier ? (
            <button
              type="button"
              className="secondaire"
              style={{ marginTop: '0.6rem' }}
              onClick={annuler}
            >
              ANNULER
            </button>
          ) : null}
        </form>
      ) : null}

      {donnees && !donnees.can_add ? (
        <p className="attenue" data-testid="ajout-ferme">
          Ce dossier n’accepte plus de nouvelle photo.
        </p>
      ) : null}
    </section>
  );
}
