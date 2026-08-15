/**
 * Contrôle d'origine pour les requêtes à effet de bord.
 *
 * `SameSite=Lax` bloque déjà l'essentiel des POST inter-sites, mais s'y fier seul
 * revient à faire dépendre la sécurité du navigateur du visiteur : les anciens
 * navigateurs ne l'appliquent pas, et certains contextes (redirections, clients non
 * navigateur) s'en écartent. Le contrôle d'`Origin` est fait côté serveur, donc
 * indépendant du client.
 *
 * Cette primitive est écrite maintenant pour le futur `PATCH /profil` : une
 * mutation réelle en aura besoin, et l'ajouter après coup signifie l'oublier sur
 * une route.
 */

export type OriginCheck =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: 'missing' | 'mismatch' };

/**
 * L'appel vient-il bien de notre propre site ?
 *
 * `Origin` est préféré à `Referer` : il est envoyé sur toutes les requêtes à effet
 * de bord et ne contient jamais de chemin ni de query string — donc jamais de
 * secret. `Referer` ne sert que de repli quand `Origin` est absent.
 *
 * Une origine absente est refusée, pas tolérée : c'est le cas d'un client qui ne se
 * comporte pas comme un navigateur, et une mutation n'a pas de raison d'en venir.
 */
export function checkOrigin(headers: Headers, allowed: string): OriginCheck {
  const origin = headers.get('origin');
  const referer = headers.get('referer');
  const expected = normalise(allowed);

  if (origin) {
    return normalise(origin) === expected
      ? { ok: true }
      : { ok: false, reason: 'mismatch' };
  }
  if (referer) {
    try {
      return normalise(new URL(referer).origin) === expected
        ? { ok: true }
        : { ok: false, reason: 'mismatch' };
    } catch {
      return { ok: false, reason: 'mismatch' };
    }
  }
  return { ok: false, reason: 'missing' };
}

function normalise(value: string): string {
  try {
    const url = new URL(value);
    return `${url.protocol}//${url.host}`.toLowerCase();
  } catch {
    return value.trim().toLowerCase().replace(/\/+$/, '');
  }
}

/**
 * La destination de redirection après connexion est-elle sûre ?
 *
 * Seuls les chemins internes commençant par `/espace-client` sont acceptés. Tout le
 * reste retombe sur `/espace-client`.
 *
 * Les formes refusées ne sont pas évidentes, d'où la liste explicite :
 * `//evil.example` est interprété par les navigateurs comme une URL absolue
 * protocole-relative ; `/\evil.example` l'est aussi par certains ; une URL absolue
 * l'est toujours. Vérifier seulement « commence par / » laisserait passer les deux
 * premières.
 */
export function safeNextPath(candidate: string | null | undefined): string {
  const fallback = '/espace-client';
  if (!candidate) return fallback;
  const value = candidate.trim();
  if (!value.startsWith('/')) return fallback;
  if (value.startsWith('//') || value.startsWith('/\\')) return fallback;
  if (value.includes('://') || /[\r\n]/.test(value)) return fallback;
  if (value !== '/espace-client' && !value.startsWith('/espace-client/')) {
    return fallback;
  }
  return value;
}
