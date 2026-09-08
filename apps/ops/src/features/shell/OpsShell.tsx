'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

type IconName = 'home' | 'folder' | 'plus' | 'truck' | 'grid';

function Icon({ name }: { readonly name: IconName }) {
  const common = {
    fill: 'none',
    stroke: 'currentColor',
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    strokeWidth: 1.9,
  };

  if (name === 'home') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path {...common} d="M3.5 10.7 12 3.8l8.5 6.9v8.8a.7.7 0 0 1-.7.7h-5.1v-6.1H9.3v6.1H4.2a.7.7 0 0 1-.7-.7z" />
      </svg>
    );
  }
  if (name === 'folder') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path {...common} d="M3.4 6.5h6.1l1.7 2h9.4v9.8a1.5 1.5 0 0 1-1.5 1.5H4.9a1.5 1.5 0 0 1-1.5-1.5z" />
      </svg>
    );
  }
  if (name === 'plus') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path {...common} d="M12 5v14M5 12h14" />
      </svg>
    );
  }
  if (name === 'truck') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path {...common} d="M3 6.5h10v9H3zM13 9h4l4 4v2.5h-8zM6.2 18.2a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM17.8 18.2a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect {...common} x="4" y="4" width="5" height="5" rx="1" />
      <rect {...common} x="15" y="4" width="5" height="5" rx="1" />
      <rect {...common} x="4" y="15" width="5" height="5" rx="1" />
      <rect {...common} x="15" y="15" width="5" height="5" rx="1" />
    </svg>
  );
}

const nav = [
  { href: '/', label: 'Accueil', icon: 'home' as const },
  { href: '/recherche', label: 'Dossiers', icon: 'folder' as const },
  { href: '/reception', label: 'Ajouter', icon: 'plus' as const, primary: true },
  { href: '/chargement', label: 'Départs', icon: 'truck' as const },
  { href: '/activite', label: 'Plus', icon: 'grid' as const },
];

export function OpsShell({
  children,
  brandHeader,
}: {
  readonly children: React.ReactNode;
  readonly brandHeader: React.ReactNode;
}) {
  const pathname = usePathname();
  const connexion = pathname === '/connexion';

  if (connexion) {
    return <div className="ops-shell ops-shell-login">{children}</div>;
  }

  return (
    <div className="ops-shell">
      <div className="ops-atmosphere" aria-hidden="true">
        <span className="ops-orbit ops-orbit-one" />
        <span className="ops-orbit ops-orbit-two" />
        <span className="ops-globe" />
      </div>

      {brandHeader}

      <div className="ops-shell-content">{children}</div>

      <nav className="ops-bottom-nav" aria-label="Navigation principale">
        {nav.map((item) => {
          const active = item.href === '/'
            ? pathname === '/'
            : pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              className={`ops-nav-item${item.primary ? ' ops-nav-primary' : ''}${active ? ' is-active' : ''}`}
              href={item.href}
              key={item.label}
              aria-current={active ? 'page' : undefined}
            >
              <span className="ops-nav-icon"><Icon name={item.icon} /></span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
