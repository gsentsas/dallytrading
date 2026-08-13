import Link from 'next/link';
import { Logo } from '@/components/brand/Logo';
import { Container } from '@/components/ui/primitives';
import { ACTIVITIES, activityHref } from '@/config/activities';
import { CONTACT, PARTNER_SEN_CONTAINERS, SOCIALS, toDialable } from '@/config/site';

/**
 * Site footer.
 *
 * A server component: it is pure content and needs no client bundle.
 *
 * Every contact channel is conditional. An unconfigured channel is omitted rather
 * than shown as a placeholder — a fake phone number on a footer is dialled, reaches
 * nobody, and costs the company the lead it was meant to capture.
 */
export function Footer() {
  const phone = toDialable(CONTACT.phone);

  return (
    <footer className="border-t border-mist-200 bg-navy-800 text-navy-100">
      <Container className="py-14">
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-4">
          {/* ─── Brand ──────────────────────────────────────────────── */}
          <div className="lg:col-span-1">
            <Logo size="md" onDark />
            <p className="mt-5 text-sm leading-relaxed text-navy-100">
              Commerce, import-export et logistique. Nous accompagnons particuliers,
              commerçants et entreprises au Sénégal et à l’international.
            </p>
            {SOCIALS.length > 0 && (
              <ul className="mt-5 flex flex-wrap gap-3">
                {SOCIALS.map((social) => (
                  <li key={social.label}>
                    <a
                      href={social.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-navy-100 underline hover:text-green-400"
                    >
                      {social.label}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* ─── Activities ─────────────────────────────────────────── */}
          <nav aria-labelledby="footer-activites" className="lg:col-span-2">
            <h2
              id="footer-activites"
              className="dally-signature text-xs font-semibold text-green-400"
            >
              Nos activités
            </h2>
            <ul className="mt-4 grid gap-2 sm:grid-cols-2">
              {ACTIVITIES.map((activity) => (
                <li key={activity.slug}>
                  <Link
                    href={activityHref(activity)}
                    className="text-sm text-navy-100 hover:text-green-400 hover:underline"
                  >
                    {activity.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>

          {/* ─── Contact and shortcuts ──────────────────────────────── */}
          <div>
            <h2
              id="footer-contact"
              className="dally-signature text-xs font-semibold text-green-400"
            >
              Contact
            </h2>
            <ul className="mt-4 space-y-2 text-sm">
              {phone && CONTACT.phone && (
                <li>
                  <a href={`tel:+${phone}`} className="hover:text-green-400">
                    {CONTACT.phone}
                  </a>
                </li>
              )}
              {CONTACT.email && (
                <li>
                  <a
                    href={`mailto:${CONTACT.email}`}
                    className="break-all hover:text-green-400"
                  >
                    {CONTACT.email}
                  </a>
                </li>
              )}
              {CONTACT.addressLines.map((line) => (
                <li key={line}>{line}</li>
              ))}
              <li>
                {CONTACT.city}, {CONTACT.country}
              </li>
            </ul>

            <h2 className="dally-signature mt-8 text-xs font-semibold text-green-400">
              Raccourcis
            </h2>
            <ul className="mt-4 space-y-2 text-sm">
              <li>
                <Link href="/devis" className="hover:text-green-400">
                  Demander un devis
                </Link>
              </li>
              <li>
                <Link href="/tracking" className="hover:text-green-400">
                  Suivre mon expédition
                </Link>
              </li>
              <li>
                <Link href="/contact" className="hover:text-green-400">
                  Nous contacter
                </Link>
              </li>
              <li>
                <Link href="/a-propos" className="hover:text-green-400">
                  À propos
                </Link>
              </li>
            </ul>
          </div>
        </div>

        {/*
          SEN CONTAINERS: a commercial partnership, stated once and kept secondary
          to the DallyTrading brand (§35). Content only — no model, no API, no CRM
          link anywhere in the system.
        */}
        <div className="mt-12 rounded-xl border border-navy-600 bg-navy-700 p-5">
          <p className="dally-signature text-xs font-semibold text-green-400">
            Partenaire
          </p>
          <p className="mt-2 text-sm text-navy-100">
            <strong className="font-semibold text-white">
              {PARTNER_SEN_CONTAINERS.name}
            </strong>{' '}
            — {PARTNER_SEN_CONTAINERS.role}. {PARTNER_SEN_CONTAINERS.summary}
          </p>
        </div>

        <div className="mt-10 flex flex-col gap-3 border-t border-navy-600 pt-6 text-xs text-navy-200 sm:flex-row sm:items-center sm:justify-between">
          <p>
            © {new Date().getFullYear()} DallyTrading. Tous droits réservés.
          </p>
          <p className="dally-signature">Import • Export • Logistics • Solutions</p>
        </div>
      </Container>
    </footer>
  );
}
