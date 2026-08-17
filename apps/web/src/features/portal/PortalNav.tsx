'use client';

/**
 * Navigation de l'espace client.
 *
 * Composant client pour une seule raison : le menu mobile s'ouvre et se ferme.
 * Tout le reste — l'identité affichée, les liens — est calculé côté serveur et
 * passé en props. Le composant ne va chercher aucune donnée.
 *
 * ## Accessibilité, points non évidents
 *
 * `aria-current="page"` plutôt qu'une simple classe CSS : un lecteur d'écran
 * annonce alors la position courante, ce qu'une couleur ne fait pas.
 *
 * Le bouton mobile porte `aria-expanded` et `aria-controls`, et le panneau est
 * réellement retiré du DOM quand il est fermé — plutôt que masqué en CSS, ce qui
 * laisserait ses liens atteignables au clavier depuis une navigation invisible.
 */

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';

import { LogoutButton } from './LogoutButton';

const LINKS = [
  { href: '/espace-client', label: 'Tableau de bord' },
  { href: '/espace-client/devis', label: 'Devis' },
  { href: '/espace-client/commandes', label: 'Commandes' },
  { href: '/espace-client/sourcing', label: 'Sourcing' },
  { href: '/espace-client/trading', label: 'Trading' },
  { href: '/espace-client/expeditions', label: 'Expéditions' },
  { href: '/espace-client/documents', label: 'Documents' },
  { href: '/espace-client/profil', label: 'Profil' },
] as const;

export function PortalNav({
  name,
  company,
}: {
  name: string;
  company: string | null;
}) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // Le tableau de bord ne doit pas rester « courant » sur toutes les sous-pages,
  // puisque son chemin est le préfixe de tous les autres.
  const isCurrent = (href: string) =>
    href === '/espace-client' ? pathname === href : pathname.startsWith(href);

  return (
    <header className="border-b border-mist-300 bg-white">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
        <div className="min-w-0">
          <p className="truncate font-semibold text-navy-900">{name}</p>
          {company && (
            <p className="truncate text-sm text-mist-600">{company}</p>
          )}
        </div>

        <nav aria-label="Espace client" className="hidden lg:block">
          <ul className="flex items-center gap-1">
            {LINKS.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={isCurrent(link.href) ? 'page' : undefined}
                  className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    isCurrent(link.href)
                      ? 'bg-green-700 text-white'
                      : 'text-navy-800 hover:bg-mist-100'
                  }`}
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <div className="hidden lg:block">
          <LogoutButton />
        </div>

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="portal-mobile-nav"
          className="rounded-lg border border-mist-300 px-3 py-2 text-sm font-medium text-navy-800 lg:hidden"
        >
          {open ? 'Fermer' : 'Menu'}
        </button>
      </div>

      {open && (
        <nav
          id="portal-mobile-nav"
          aria-label="Espace client"
          className="border-t border-mist-300 lg:hidden"
        >
          <ul className="mx-auto flex w-full max-w-6xl flex-col gap-1 px-4 py-3 sm:px-6">
            {LINKS.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  onClick={() => setOpen(false)}
                  aria-current={isCurrent(link.href) ? 'page' : undefined}
                  className={`block rounded-lg px-3 py-3 font-medium ${
                    isCurrent(link.href)
                      ? 'bg-green-700 text-white'
                      : 'text-navy-800 hover:bg-mist-100'
                  }`}
                >
                  {link.label}
                </Link>
              </li>
            ))}
            <li className="pt-2">
              <LogoutButton />
            </li>
          </ul>
        </nav>
      )}
    </header>
  );
}
