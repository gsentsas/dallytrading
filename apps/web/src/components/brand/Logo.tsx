import Link from 'next/link';
import { BRAND } from '@/config/site';

/**
 * The DallyTrading logo.
 *
 * ## Two parts, handled differently on purpose
 *
 * 1. **The wordmark** — DALLY in navy, TRADING in green, with the signature line
 *    underneath — is rendered as text/SVG here. It is crisp at every size, costs
 *    no request, and is styled from the design tokens, so it can never drift from
 *    the rest of the site.
 *
 * 2. **The emblem** — the circular mark with the vessel, aircraft, truck and leaf
 *    swoosh — is an official brand asset and is **not recreated in code**. An
 *    approximation of a company's own logo is worse than no logo: it looks nearly
 *    right, which is exactly how a wrong version ends up on printed material.
 *
 * The emblem is therefore loaded from a file that the brand owner supplies. Until
 * it exists, the component renders the wordmark alone — never a broken image.
 * See `public/brand/README.md` for where to put it.
 */

/** Path the official emblem is expected at, once supplied. */
const EMBLEM_SRC = '/brand/dallytrading-emblem.png';

/**
 * Whether the emblem file has been supplied.
 *
 * Opt-in rather than opt-out: a missing asset must degrade to the wordmark, not
 * to a broken-image icon in the header of every page.
 */
const HAS_EMBLEM = process.env.NEXT_PUBLIC_BRAND_EMBLEM === 'true';

type Size = 'sm' | 'md' | 'lg';

const WORDMARK_SIZES: Record<Size, string> = {
  sm: 'text-lg',
  md: 'text-xl sm:text-2xl',
  lg: 'text-3xl sm:text-4xl',
};

const SIGNATURE_SIZES: Record<Size, string> = {
  sm: 'text-[0.5rem]',
  md: 'text-[0.55rem] sm:text-[0.6rem]',
  lg: 'text-[0.7rem] sm:text-xs',
};

const EMBLEM_SIZES: Record<Size, number> = { sm: 32, md: 40, lg: 64 };

export function Logo({
  size = 'md',
  showSignature = true,
  onDark = false,
}: {
  size?: Size;
  showSignature?: boolean;
  /** Inverts the wordmark for placement on a navy surface. */
  onDark?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-3">
      {/*
        A plain <img>, not next/image: a fixed-size brand mark gains nothing from the
        optimiser, and next/image would fail the build if the asset has not been
        supplied yet — which is exactly the state this component is built to survive.
      */}
      {HAS_EMBLEM && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={EMBLEM_SRC}
          alt=""
          aria-hidden="true"
          width={EMBLEM_SIZES[size]}
          height={EMBLEM_SIZES[size]}
          className="shrink-0"
        />
      )}
      <span className="flex flex-col leading-none">
        <span className={`font-extrabold tracking-tight ${WORDMARK_SIZES[size]}`}>
          <span className={onDark ? 'text-white' : 'text-navy-700'}>
            {BRAND.wordmark.first}
          </span>
          <span className={onDark ? 'text-green-400' : 'text-green-700'}>
            {BRAND.wordmark.second}
          </span>
        </span>
        {showSignature && (
          <span
            className={`dally-signature mt-1 font-medium ${SIGNATURE_SIZES[size]} ${
              onDark ? 'text-navy-100' : 'text-mist-500'
            }`}
          >
            {BRAND.signature}
          </span>
        )}
      </span>
    </span>
  );
}

/**
 * The logo as a link home.
 *
 * The accessible name is the company name, not "logo": a screen-reader user needs
 * to know where the link goes, and "logo" tells them nothing.
 */
export function LogoLink({
  size = 'md',
  showSignature = true,
  onDark = false,
}: {
  size?: Size;
  showSignature?: boolean;
  onDark?: boolean;
}) {
  return (
    <Link
      href="/"
      aria-label={`${BRAND.name} — retour à l’accueil`}
      className="inline-flex items-center rounded-sm"
    >
      <Logo size={size} showSignature={showSignature} onDark={onDark} />
    </Link>
  );
}

/**
 * Decorative leaf swoosh, echoing the logo's green curve.
 *
 * Always `aria-hidden`: it carries no information.
 */
export function Swoosh({ className = '' }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`dally-swoosh block w-16 ${className}`}
    />
  );
}
