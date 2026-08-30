'use client';

/**
 * Ce que le comptoir peut faire du reçu : l'imprimer, le télécharger, le
 * partager.
 *
 * ## Le PDF ne s'obtient jamais par une adresse laissée au navigateur
 *
 * Les octets sont demandés au BFF, qui les tient de la session. Aucune URL
 * publique ne mène au reçu d'un client : personne ne peut en deviner une, et
 * rien ne subsiste dans l'historique.
 *
 * ## L'objet URL créé est toujours révoqué
 *
 * Un `blob:` non révoqué garde le document en mémoire de l'onglet pour toute
 * la durée de la session. Sur un téléphone d'entrepôt partagé, c'est un reçu
 * client qui traîne.
 *
 * ## Le partage échoue silencieusement plus souvent qu'on ne croit
 *
 * `navigator.share` n'existe pas partout, refuse parfois les fichiers, et lève
 * dès que l'utilisateur annule. Chacun de ces cas retombe sur le
 * téléchargement, qui marche partout.
 */

import { useState } from 'react';

import { nomFichierRecu } from '@/lib/ops/recu-vocabulaire';

type Etat = 'repos' | 'travail' | 'erreur';

export function RecuActions({ reference }: { reference: string }) {
  const [etat, setEtat] = useState<Etat>('repos');
  const [message, setMessage] = useState('');

  const nomFichier = nomFichierRecu(reference);

  async function telechargerLesOctets(): Promise<Blob> {
    const reponse = await fetch(
      `/api/intakes/${encodeURIComponent(reference)}/receipt/pdf`,
      { cache: 'no-store' },
    );
    if (!reponse.ok) throw new Error(String(reponse.status));
    return reponse.blob();
  }

  function enregistrer(fichier: Blob) {
    const adresse = URL.createObjectURL(fichier);
    try {
      const lien = document.createElement('a');
      lien.href = adresse;
      lien.download = nomFichier;
      lien.click();
    } finally {
      // Même en cas d'échec : rien ne doit rester en mémoire de l'onglet.
      URL.revokeObjectURL(adresse);
    }
  }

  async function avec(action: (fichier: Blob) => Promise<void> | void) {
    setEtat('travail');
    setMessage('');
    try {
      await action(await telechargerLesOctets());
      setEtat('repos');
    } catch {
      setEtat('erreur');
      setMessage('Le reçu n’a pas pu être obtenu. Vérifiez le réseau et réessayez.');
    }
  }

  const partager = () => avec(async (contenu) => {
    const fichier = new File([contenu], nomFichier, { type: 'application/pdf' });
    const partageur = navigator as Navigator & {
      canShare?: (donnees: { files?: File[] }) => boolean;
    };
    // Trois conditions, et un repli sur le téléchargement dès que l'une manque.
    if (typeof navigator.share !== 'function'
        || typeof partageur.canShare !== 'function'
        || !partageur.canShare({ files: [fichier] })) {
      enregistrer(contenu);
      return;
    }
    try {
      await navigator.share({ files: [fichier], title: `Reçu ${reference}` });
    } catch {
      // Annulation de l'utilisateur ou refus du système : ni l'un ni l'autre
      // n'est une panne, et le reçu doit rester obtenable.
      enregistrer(contenu);
    }
  });

  return (
    <div className="recu-actions">
      <button
        type="button"
        onClick={() => avec(enregistrer)}
        disabled={etat === 'travail'}
      >
        {etat === 'travail' ? 'Préparation…' : 'TÉLÉCHARGER PDF'}
      </button>
      <button
        type="button"
        className="secondaire"
        onClick={partager}
        disabled={etat === 'travail'}
      >
        PARTAGER
      </button>
      <button
        type="button"
        className="secondaire"
        onClick={() => window.print()}
      >
        IMPRIMER
      </button>
      {etat === 'erreur' ? <p className="erreur">{message}</p> : null}
    </div>
  );
}
