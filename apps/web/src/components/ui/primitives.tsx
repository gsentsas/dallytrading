import Link from 'next/link';
import type { ReactNode } from 'react';

/**
 * Layout and content primitives.
 *
 * Grouped in one file on purpose: these are a dozen lines each, they are always
 * used together, and splitting them across eight files would add navigation cost
 * without adding clarity. Anything that grows its own state or logic moves out.
 */

/** Consistent page gutter and maximum width. */
export function Container({
  children,
  className = '',
  size = 'default',
}: {
  children: ReactNode;
  className?: string;
  size?: 'default' | 'narrow' | 'wide';
}) {
  const width =
    size === 'narrow' ? 'max-w-3xl' : size === 'wide' ? 'max-w-7xl' : 'max-w-6xl';
  return (
    <div className={`mx-auto ${width} px-4 sm:px-6 ${className}`}>{children}</div>
  );
}

/**
 * A page section.
 *
 * `aria-labelledby` is wired to the heading whenever one is given, so screen
 * readers can list the page's regions instead of a run of unnamed groups.
 */
export function Section({
  children,
  className = '',
  tone = 'white',
  labelledBy,
  id,
}: {
  children: ReactNode;
  className?: string;
  tone?: 'white' | 'mist' | 'navy';
  labelledBy?: string;
  id?: string;
}) {
  const tones = {
    white: 'bg-white',
    mist: 'bg-mist-50',
    navy: 'bg-navy-700 text-white',
  } as const;
  return (
    <section
      id={id}
      aria-labelledby={labelledBy}
      className={`py-14 sm:py-20 ${tones[tone]} ${className}`}
    >
      {children}
    </section>
  );
}

/** Section heading with the brand's leaf accent above it. */
export function SectionHeading({
  id,
  eyebrow,
  title,
  lead,
  onDark = false,
  centered = false,
}: {
  id: string;
  eyebrow?: string;
  title: string;
  lead?: string;
  onDark?: boolean;
  centered?: boolean;
}) {
  return (
    <div className={`${centered ? 'mx-auto text-center' : ''} max-w-3xl`}>
      {eyebrow && (
        <p
          className={`dally-signature text-xs font-semibold ${
            onDark ? 'text-green-400' : 'text-green-700'
          }`}
        >
          {eyebrow}
        </p>
      )}
      <h2
        id={id}
        className={`mt-3 text-2xl font-bold sm:text-3xl ${
          onDark ? 'text-white' : 'text-navy-800'
        }`}
      >
        {title}
      </h2>
      {/* Decorative: the heading already conveys the structure. */}
      <span
        aria-hidden="true"
        className={`dally-swoosh mt-4 block w-16 ${centered ? 'mx-auto' : ''}`}
      />
      {lead && (
        <p
          className={`mt-5 text-base leading-relaxed sm:text-lg ${
            onDark ? 'text-navy-100' : 'text-mist-600'
          }`}
        >
          {lead}
        </p>
      )}
    </div>
  );
}

/**
 * Primary call to action.
 *
 * Uses `green-700`, not the logo's brighter leaf green: white on `#4C9A2A` is
 * 3.5:1, below WCAG AA for a button label. The bright green is kept for the hover
 * state and for graphics.
 */
export function CtaLink({
  href,
  children,
  variant = 'primary',
  className = '',
}: {
  href: string;
  children: ReactNode;
  variant?: 'primary' | 'secondary' | 'ghost' | 'onNavy';
  className?: string;
}) {
  const variants = {
    primary:
      'bg-green-700 text-white hover:bg-green-800 focus-visible:outline-navy-700',
    secondary:
      'bg-navy-700 text-white hover:bg-navy-800',
    ghost:
      'border border-navy-300 text-navy-700 hover:bg-navy-50',
    onNavy:
      'border border-navy-200 text-white hover:bg-navy-600',
  } as const;

  return (
    <Link
      href={href}
      className={`inline-flex items-center justify-center rounded-lg px-6 py-3 text-center font-semibold transition-colors ${variants[variant]} ${className}`}
    >
      {children}
    </Link>
  );
}

/** Content card. Becomes a link when `href` is given. */
export function Card({
  href,
  title,
  children,
  footer,
}: {
  href?: string;
  title: string;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  const body = (
    <>
      <h3 className="font-semibold text-navy-700 group-hover:text-green-700">
        {title}
      </h3>
      {children && (
        <p className="mt-2 text-sm leading-relaxed text-mist-600">{children}</p>
      )}
      {footer && <div className="mt-4">{footer}</div>}
    </>
  );

  const shell =
    'group block h-full rounded-xl border border-mist-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md';

  return href ? (
    <Link href={href} className={shell}>
      {body}
    </Link>
  ) : (
    <div className={shell}>{body}</div>
  );
}

/** Checklist, using the brand's leaf green for the marker. */
export function CheckList({ items }: { items: ReadonlyArray<string> }) {
  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item} className="flex gap-3">
          {/* Decorative marker: the list semantics already convey the structure. */}
          <span
            aria-hidden="true"
            className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-leaf"
          />
          <span className="text-mist-700">{item}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Breadcrumb trail.
 *
 * Paired with BreadcrumbList JSON-LD on the pages that use it, so the same
 * structure is available to users and to search engines.
 */
export function Breadcrumbs({
  trail,
}: {
  trail: ReadonlyArray<{ label: string; href?: string }>;
}) {
  return (
    <nav aria-label="Fil d’Ariane" className="text-sm">
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-mist-600">
        {trail.map((entry, index) => {
          const isLast = index === trail.length - 1;
          return (
            <li key={entry.label} className="flex items-center gap-2">
              {entry.href && !isLast ? (
                <Link href={entry.href} className="hover:text-green-700 hover:underline">
                  {entry.label}
                </Link>
              ) : (
                <span aria-current={isLast ? 'page' : undefined} className="text-navy-700">
                  {entry.label}
                </span>
              )}
              {!isLast && <span aria-hidden="true">/</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Standard CTA row, so every page offers the same three next steps. */
export function CtaRow({
  onDark = false,
  className = '',
}: {
  onDark?: boolean;
  className?: string;
}) {
  return (
    <div className={`flex flex-wrap gap-3 ${className}`}>
      <CtaLink href="/devis">Demander un devis</CtaLink>
      <CtaLink href="/contact" variant={onDark ? 'onNavy' : 'ghost'}>
        Parler à un conseiller
      </CtaLink>
      <CtaLink href="/tracking" variant={onDark ? 'onNavy' : 'ghost'}>
        Suivre mon expédition
      </CtaLink>
    </div>
  );
}
