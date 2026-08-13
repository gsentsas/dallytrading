'use client';

/**
 * Site header.
 *
 * A client component because the mobile menu and the activities dropdown need
 * state. Everything else on the site stays a server component.
 *
 * Accessibility decisions worth naming:
 *
 * * The activities submenu is a `<details>` on mobile and a hover/focus dropdown on
 *   desktop, both of which work without JavaScript for keyboard users.
 * * `aria-expanded` and `aria-controls` are wired on the mobile toggle, and the
 *   panel closes on route change — a menu left open over the new page is a common
 *   and disorienting bug.
 * * `aria-current="page"` marks the active entry, so a screen-reader user knows
 *   where they are without reading the whole nav.
 */

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useId, useState } from 'react';
import { LogoLink } from '@/components/brand/Logo';
import { ACTIVITIES, activityHref } from '@/config/activities';

const MAIN_NAV = [
  { href: '/', label: 'Accueil' },
  { href: '/a-propos', label: 'À propos' },
  { href: '/activites', label: 'Nos activités', hasSubmenu: true },
  { href: '/tracking', label: 'Suivi' },
  { href: '/contact', label: 'Contact' },
] as const;

export function Header() {
  const pathname = usePathname();
  const panelId = useId();

  // A menu left open over a freshly navigated page is disorienting, and on mobile it
  // hides the content the user just asked for. So it closes on navigation.
  //
  // Done by adjusting state during render rather than in an effect. React documents
  // this pattern for "state that depends on props": the component re-renders
  // immediately with the corrected value, before anything reaches the DOM. An effect
  // would render the stale open menu first, then close it — a visible flash, and a
  // cascading render the linter rightly flags.
  const [menu, setMenu] = useState({ open: false, path: pathname });
  if (menu.path !== pathname) {
    setMenu({ open: false, path: pathname });
  }
  const mobileOpen = menu.open;
  const setMobileOpen = (next: boolean | ((open: boolean) => boolean)) => {
    setMenu((current) => ({
      open: typeof next === 'function' ? next(current.open) : next,
      path: pathname,
    }));
  };

  function isActive(href: string): boolean {
    if (href === '/') return pathname === '/';
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  return (
    <header className="sticky top-0 z-40 border-b border-mist-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <LogoLink size="md" />

        {/* ─── Desktop navigation ─────────────────────────────────── */}
        <nav aria-label="Navigation principale" className="hidden lg:block">
          <ul className="flex items-center gap-1">
            {MAIN_NAV.map((entry) => (
              <li key={entry.href} className="relative">
                {'hasSubmenu' in entry && entry.hasSubmenu ? (
                  // group + focus-within: the panel opens on hover for a mouse and
                  // on focus for a keyboard, with no JavaScript involved.
                  <div className="group">
                    <Link
                      href={entry.href}
                      aria-current={isActive(entry.href) ? 'page' : undefined}
                      className={`inline-flex items-center gap-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                        isActive(entry.href)
                          ? 'text-green-700'
                          : 'text-navy-700 hover:text-green-700'
                      }`}
                    >
                      {entry.label}
                      <span aria-hidden="true" className="text-xs">▾</span>
                    </Link>
                    <div className="invisible absolute left-0 top-full z-50 w-72 opacity-0 transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100">
                      <ul className="mt-1 rounded-xl border border-mist-200 bg-white py-2 shadow-lg">
                        {ACTIVITIES.map((activity) => (
                          <li key={activity.slug}>
                            <Link
                              href={activityHref(activity)}
                              className="block px-4 py-2 text-sm text-navy-700 hover:bg-mist-50 hover:text-green-700"
                            >
                              {activity.label}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                ) : (
                  <Link
                    href={entry.href}
                    aria-current={isActive(entry.href) ? 'page' : undefined}
                    className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                      isActive(entry.href)
                        ? 'text-green-700'
                        : 'text-navy-700 hover:text-green-700'
                    }`}
                  >
                    {entry.label}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </nav>

        <div className="flex items-center gap-2">
          {/* The primary CTA stays visible at every breakpoint (§34). */}
          <Link
            href="/devis"
            className="rounded-lg bg-green-700 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-green-800 sm:px-5"
          >
            <span className="hidden sm:inline">Demander un devis</span>
            <span className="sm:hidden">Devis</span>
          </Link>

          <button
            type="button"
            onClick={() => setMobileOpen((open) => !open)}
            aria-expanded={mobileOpen}
            aria-controls={panelId}
            className="rounded-md border border-mist-300 p-2 text-navy-700 lg:hidden"
          >
            <span className="sr-only">
              {mobileOpen ? 'Fermer le menu' : 'Ouvrir le menu'}
            </span>
            <span aria-hidden="true" className="block text-lg leading-none">
              {mobileOpen ? '✕' : '☰'}
            </span>
          </button>
        </div>
      </div>

      {/* ─── Mobile navigation ──────────────────────────────────────── */}
      {mobileOpen && (
        <nav
          id={panelId}
          aria-label="Navigation principale"
          className="border-t border-mist-200 bg-white lg:hidden"
        >
          <ul className="mx-auto max-w-6xl px-4 py-2 sm:px-6">
            {MAIN_NAV.map((entry) => (
              <li key={entry.href} className="border-b border-mist-100 last:border-0">
                {'hasSubmenu' in entry && entry.hasSubmenu ? (
                  // <details> gives a working disclosure with no JavaScript and
                  // correct semantics for assistive technology.
                  <details>
                    <summary className="cursor-pointer list-none py-3 font-medium text-navy-700">
                      {entry.label}
                      <span aria-hidden="true" className="float-right">▾</span>
                    </summary>
                    <ul className="pb-2 pl-4">
                      <li>
                        <Link
                          href="/activites"
                          className="block py-2 text-sm font-medium text-green-700"
                        >
                          Toutes nos activités
                        </Link>
                      </li>
                      {ACTIVITIES.map((activity) => (
                        <li key={activity.slug}>
                          <Link
                            href={activityHref(activity)}
                            className="block py-2 text-sm text-navy-700"
                          >
                            {activity.label}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : (
                  <Link
                    href={entry.href}
                    aria-current={isActive(entry.href) ? 'page' : undefined}
                    className={`block py-3 font-medium ${
                      isActive(entry.href) ? 'text-green-700' : 'text-navy-700'
                    }`}
                  >
                    {entry.label}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </nav>
      )}
    </header>
  );
}
