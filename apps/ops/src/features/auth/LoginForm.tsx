'use client';

/**
 * Le formulaire de connexion.
 *
 * Il n'affiche jamais autre chose que le message renvoyé par le serveur, et
 * ne cherche pas à deviner la cause d'un refus : c'est ce qui garantit qu'un
 * identifiant inconnu et un mot de passe faux restent indiscernables depuis
 * le navigateur.
 */

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

export function LoginForm() {
  const router = useRouter();
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoiEnCours, setEnvoiEnCours] = useState(false);

  async function soumettre(evenement: FormEvent<HTMLFormElement>) {
    evenement.preventDefault();
    setErreur(null);
    setEnvoiEnCours(true);
    try {
      const reponse = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login, password }),
      });
      const charge = (await reponse.json().catch(() => null)) as
        | { success?: boolean; error?: string }
        | null;
      if (!reponse.ok || !charge?.success) {
        setErreur(charge?.error ?? 'Identifiants invalides.');
        // Le champ est vidé pour qu'un mot de passe ne reste pas affiché sur
        // un terminal partagé après un échec.
        setPassword('');
        return;
      }
      router.replace('/');
      router.refresh();
    } catch {
      setErreur('Service momentanément indisponible.');
    } finally {
      setEnvoiEnCours(false);
    }
  }

  return (
    <form onSubmit={soumettre} noValidate>
      {erreur ? (
        <p className="erreur" role="alert">
          {erreur}
        </p>
      ) : null}

      <label htmlFor="login">
        Identifiant
        <input
          id="login"
          name="login"
          type="text"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          required
          value={login}
          onChange={(evenement) => setLogin(evenement.target.value)}
        />
      </label>

      <label htmlFor="password">
        Mot de passe
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(evenement) => setPassword(evenement.target.value)}
        />
      </label>

      <button type="submit" disabled={envoiEnCours}>
        {envoiEnCours ? 'Connexion…' : 'Se connecter'}
      </button>
    </form>
  );
}
