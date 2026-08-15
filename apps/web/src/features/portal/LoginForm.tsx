'use client';

/**
 * Formulaire de connexion à l'espace client.
 *
 * ## Ce que ce composant NE fait pas
 *
 * Il ne stocke rien. Ni dans `localStorage`, ni dans `sessionStorage`, ni dans une
 * variable de module. La session vit uniquement dans un cookie `HttpOnly` que ce
 * code ne peut pas lire — c'est précisément l'intérêt : un script injecté sur la
 * page ne trouve rien à voler.
 *
 * Il ne décide pas non plus de la redirection : `next` a été assaini côté serveur
 * par `safeNextPath`. Le composant le reçoit déjà sûr et se contente de l'utiliser.
 */

import { useState } from 'react';

const GENERIC_ERROR =
  'Identifiants invalides. Vérifiez votre adresse e-mail et votre mot de passe.';

type Status = 'editing' | 'submitting';

export function LoginForm({ next }: { next: string }) {
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<Status>('editing');
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus('submitting');
    setError(null);

    try {
      const response = await fetch('/api/portal/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Le cookie doit être posé par la réponse : sans cela, la connexion
        // « réussit » et la page suivante redemande une authentification.
        credentials: 'same-origin',
        body: JSON.stringify({ login, password }),
      });

      if (response.ok) {
        // Navigation complète plutôt que `router.push` : la page cible est rendue
        // côté serveur et doit être demandée AVEC le cookie tout juste posé. Une
        // transition client réutiliserait le payload RSC obtenu avant connexion,
        // c'est-à-dire la redirection vers /connexion.
        window.location.assign(next);
        return;
      }

      const payload = (await response.json().catch(() => null)) as
        | { error?: { code?: string; message?: string } }
        | null;
      const code = payload?.error?.code;
      setError(
        code === 'rate_limited' || code === 'unavailable'
          ? (payload?.error?.message ?? GENERIC_ERROR)
          : GENERIC_ERROR,
      );
      setStatus('editing');
    } catch {
      setError(
        'La connexion au service a échoué. Vérifiez votre connexion internet et réessayez.',
      );
      setStatus('editing');
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      <div>
        <label htmlFor="portal-login" className="block font-medium text-navy-800">
          Adresse e-mail
          <span aria-hidden="true" className="text-red-700"> *</span>
        </label>
        <input
          id="portal-login"
          name="login"
          type="email"
          autoComplete="username"
          required
          value={login}
          onChange={(event) => setLogin(event.target.value)}
          className="mt-2 w-full rounded-lg border border-mist-300 bg-white p-3"
        />
      </div>

      <div>
        <label htmlFor="portal-password" className="block font-medium text-navy-800">
          Mot de passe
          <span aria-hidden="true" className="text-red-700"> *</span>
        </label>
        <input
          id="portal-password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mt-2 w-full rounded-lg border border-mist-300 bg-white p-3"
        />
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800"
        >
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={status === 'submitting'}
        className="rounded-lg bg-green-700 px-6 py-3 font-semibold text-white transition-colors hover:bg-green-800 disabled:opacity-60"
      >
        {status === 'submitting' ? 'Connexion…' : 'Se connecter'}
      </button>
    </form>
  );
}
