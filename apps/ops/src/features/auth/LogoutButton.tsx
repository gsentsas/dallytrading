'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

/**
 * La déconnexion.
 *
 * Elle renvoie vers l'écran de connexion même si l'appel échoue : sur un
 * terminal partagé, laisser un opérateur sur son écran parce que le réseau a
 * hoqueté serait le pire des deux résultats. Le cookie, lui, est effacé côté
 * serveur.
 */
export function LogoutButton() {
  const router = useRouter();
  const [enCours, setEnCours] = useState(false);

  async function deconnecter() {
    setEnCours(true);
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch {
      // Sans effet : la redirection ci-dessous a lieu de toute façon.
    } finally {
      router.replace('/connexion');
      router.refresh();
    }
  }

  return (
    <button type="button" className="secondaire" onClick={deconnecter} disabled={enCours}>
      {enCours ? 'Déconnexion…' : 'Se déconnecter'}
    </button>
  );
}
