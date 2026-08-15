'use client';

/**
 * Bouton de déconnexion.
 *
 * POST, pas un lien : la déconnexion change l'état côté serveur, et un GET
 * déclencherait la déconnexion depuis n'importe quelle balise `<img>` d'un site
 * tiers.
 *
 * Après la réponse, rechargement complet vers `/connexion`, et non
 * `router.push()`.
 *
 * `router.push()` fait une transition côté client : le Router Cache de Next
 * conserve le payload RSC déjà rendu de `/espace-client`, et un retour arrière
 * réafficherait le contenu privé d'une session qu'on vient de fermer. Un
 * rechargement complet jette ce cache.
 *
 * `replace` plutôt que `assign` : la page privée disparaît de l'historique, donc
 * le bouton « précédent » ne ramène pas dessus.
 */

import { useState } from 'react';

export function LogoutButton() {
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    setBusy(true);
    try {
      await fetch('/api/portal/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
      });
    } catch {
      // Même en cas d'échec réseau, on quitte la page : y rester donnerait
      // l'impression d'être encore connecté.
    }
    window.location.replace('/connexion');
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={busy}
      className="rounded-lg border border-mist-300 px-4 py-2 text-sm font-medium text-navy-800 transition-colors hover:bg-mist-100 disabled:opacity-60"
    >
      {busy ? 'Déconnexion…' : 'Se déconnecter'}
    </button>
  );
}
