'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { cleProprietaire } from '@/lib/offline/client';

function UserIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="5" y="10" width="14" height="10" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

function EyeIcon({ hidden }: { readonly hidden: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 12s3.2-5 9-5 9 5 9 5-3.2 5-9 5-9-5-9-5Z" />
      <circle cx="12" cy="12" r="2.2" />
      {hidden ? <path d="m4 4 16 16" /> : null}
    </svg>
  );
}

export function LoginForm() {
  const router = useRouter();
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [passwordVisible, setPasswordVisible] = useState(false);
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
        setPassword('');
        return;
      }
      await cleProprietaire(login).catch(() => undefined);
      router.replace('/');
      router.refresh();
    } catch {
      setErreur('Service momentanément indisponible.');
    } finally {
      setEnvoiEnCours(false);
    }
  }

  return (
    <form className="ops-login-form" onSubmit={soumettre} noValidate>
      {erreur ? <p className="erreur" role="alert">{erreur}</p> : null}

      <label className="ops-login-field" htmlFor="login">
        <span className="ops-login-field-icon"><UserIcon /></span>
        <span className="sr-only">Identifiant</span>
        <input
          id="login"
          name="login"
          type="text"
          placeholder="Identifiant"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          required
          value={login}
          onChange={(evenement) => setLogin(evenement.target.value)}
        />
      </label>

      <label className="ops-login-field" htmlFor="password">
        <span className="ops-login-field-icon"><LockIcon /></span>
        <span className="sr-only">Mot de passe</span>
        <input
          id="password"
          name="password"
          type={passwordVisible ? 'text' : 'password'}
          placeholder="Mot de passe"
          autoComplete="current-password"
          required
          value={password}
          onChange={(evenement) => setPassword(evenement.target.value)}
        />
        <button
          className="ops-password-toggle"
          type="button"
          aria-label={passwordVisible ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
          onClick={() => setPasswordVisible((visible) => !visible)}
        >
          <EyeIcon hidden={!passwordVisible} />
        </button>
      </label>

      <button className="ops-login-submit" type="submit" disabled={envoiEnCours}>
        <span>{envoiEnCours ? 'Connexion…' : 'Se connecter'}</span>
        <span aria-hidden="true">→</span>
      </button>
    </form>
  );
}
