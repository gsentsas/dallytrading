import type { Metadata } from 'next';
import {
  Breadcrumbs,
  Container,
  CtaLink,
  Section,
  SectionHeading,
} from '@/components/ui/primitives';
import { JsonLd } from '@/components/seo/JsonLd';
import { ContactForm } from '@/features/contact/ContactForm';
import { CONTACT, SOCIALS, toDialable } from '@/config/site';
import { breadcrumbJsonLd, pageMetadata } from '@/lib/seo';

const TRAIL = [{ label: 'Accueil', href: '/' }, { label: 'Contact' }];

export const metadata: Metadata = pageMetadata({
  title: 'Contact — Écrivez-nous',
  description:
    'Contactez DallyTrading pour vos opérations d’import-export, de fret, de ' +
    'sourcing ou de logistique. Formulaire, téléphone, e-mail et WhatsApp.',
  path: '/contact',
  keywords: [
    'contact DallyTrading',
    'contacter transitaire Dakar',
    'import export Sénégal contact',
  ],
});

/**
 * Contact page.
 *
 * `?sujet=` pre-selects the subject, so a CTA from an activity page arrives with the
 * right context already chosen.
 *
 * Every channel below is conditional on being configured. An unconfigured channel is
 * omitted rather than shown as a placeholder: a fake phone number is dialled, reaches
 * nobody, and costs the company the lead it was meant to capture.
 */
export default async function ContactPage({
  searchParams,
}: {
  searchParams: Promise<{ sujet?: string }>;
}) {
  const { sujet } = await searchParams;
  const phone = toDialable(CONTACT.phone);
  const whatsapp = toDialable(CONTACT.whatsapp);

  const hasAnyChannel =
    phone !== null ||
    whatsapp !== null ||
    CONTACT.email !== null ||
    CONTACT.addressLines.length > 0;

  return (
    <main id="contenu">
      <section
        aria-labelledby="contact-titre"
        className="relative overflow-hidden bg-navy-700 text-white"
      >
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-20 -right-10 h-56 w-96 rotate-6 rounded-[100%] bg-gradient-to-r from-leaf/25 to-leaf-light/10 blur-2xl"
        />
        <Container className="relative py-12 sm:py-16">
          <div className="[&_a]:text-navy-100 [&_a:hover]:text-green-400 [&_span]:text-white">
            <Breadcrumbs trail={TRAIL} />
          </div>
          <p className="dally-signature mt-6 text-xs font-semibold text-green-400">
            Contact
          </p>
          <h1
            id="contact-titre"
            className="mt-3 max-w-3xl text-3xl font-bold leading-tight sm:text-4xl"
          >
            Écrivez-nous
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-navy-100">
            Une question, un projet, une opération à organiser. Décrivez votre besoin :
            nous vous répondons avec une position claire, y compris quand la réponse
            est non.
          </p>
        </Container>
      </section>

      <Section labelledBy="formulaire-titre" tone="white">
        <Container>
          <div className="grid gap-12 lg:grid-cols-[1fr_22rem] lg:items-start">
            {/* ─── Form ─────────────────────────────────────────────── */}
            <div>
              <SectionHeading
                id="formulaire-titre"
                title="Formulaire de contact"
                lead="Nous revenons vers vous avec une référence de suivi, que vous pourrez citer dans tous nos échanges."
              />
              <div className="mt-10">
                <ContactForm {...(sujet ? { initialSubject: sujet } : {})} />
              </div>
            </div>

            {/* ─── Direct channels ──────────────────────────────────── */}
            <aside
              aria-labelledby="coordonnees-titre"
              className="rounded-2xl border border-mist-200 bg-mist-50 p-7"
            >
              <h2 id="coordonnees-titre" className="text-lg font-bold text-navy-800">
                Nos coordonnées
              </h2>
              <span aria-hidden="true" className="dally-swoosh mt-3 block w-12" />

              {hasAnyChannel ? (
                <dl className="mt-6 space-y-5 text-sm">
                  {phone && CONTACT.phone && (
                    <div>
                      <dt className="font-semibold text-navy-700">Téléphone</dt>
                      <dd className="mt-1">
                        <a
                          href={`tel:+${phone}`}
                          className="text-mist-700 hover:text-green-700 hover:underline"
                        >
                          {CONTACT.phone}
                        </a>
                      </dd>
                    </div>
                  )}

                  {whatsapp && (
                    <div>
                      <dt className="font-semibold text-navy-700">WhatsApp</dt>
                      <dd className="mt-1">
                        <a
                          href={`https://wa.me/${whatsapp}?text=${encodeURIComponent(
                            'Bonjour DallyTrading, je souhaite obtenir des informations sur vos services.',
                          )}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-mist-700 hover:text-green-700 hover:underline"
                        >
                          Démarrer une conversation
                        </a>
                      </dd>
                    </div>
                  )}

                  {CONTACT.email && (
                    <div>
                      <dt className="font-semibold text-navy-700">E-mail</dt>
                      <dd className="mt-1">
                        <a
                          href={`mailto:${CONTACT.email}`}
                          className="break-all text-mist-700 hover:text-green-700 hover:underline"
                        >
                          {CONTACT.email}
                        </a>
                      </dd>
                    </div>
                  )}

                  <div>
                    <dt className="font-semibold text-navy-700">Adresse</dt>
                    <dd className="mt-1 text-mist-700">
                      {CONTACT.addressLines.map((line) => (
                        <span key={line} className="block">
                          {line}
                        </span>
                      ))}
                      <span className="block">
                        {CONTACT.city}, {CONTACT.country}
                      </span>
                    </dd>
                  </div>

                  {CONTACT.hours.length > 0 && (
                    <div>
                      <dt className="font-semibold text-navy-700">Horaires</dt>
                      <dd className="mt-1 text-mist-700">
                        {CONTACT.hours.map((line) => (
                          <span key={line} className="block">
                            {line}
                          </span>
                        ))}
                      </dd>
                    </div>
                  )}
                </dl>
              ) : (
                /*
                  No channel configured. Rather than print a plausible-looking
                  placeholder — which a visitor would try and which would fail — the
                  form is presented as the way through.
                */
                <p className="mt-6 text-sm leading-relaxed text-mist-600">
                  Le formulaire ci-contre est la voie la plus directe pour nous
                  joindre : votre message arrive immédiatement à notre équipe
                  commerciale avec une référence de suivi.
                </p>
              )}

              {SOCIALS.length > 0 && (
                <div className="mt-7 border-t border-mist-200 pt-6">
                  <h3 className="text-sm font-semibold text-navy-700">
                    Réseaux sociaux
                  </h3>
                  <ul className="mt-3 flex flex-wrap gap-3">
                    {SOCIALS.map((social) => (
                      <li key={social.label}>
                        <a
                          href={social.href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm text-mist-700 underline hover:text-green-700"
                        >
                          {social.label}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="mt-7 border-t border-mist-200 pt-6">
                <h3 className="text-sm font-semibold text-navy-700">
                  Vous avez déjà une expédition ?
                </h3>
                <p className="mt-2 text-sm text-mist-600">
                  Consultez son avancement avec le lien de suivi reçu par e-mail ou
                  WhatsApp.
                </p>
                <CtaLink href="/tracking" variant="ghost" className="mt-4 w-full">
                  Suivre mon expédition
                </CtaLink>
              </div>
            </aside>
          </div>
        </Container>
      </Section>

      <Section labelledBy="contact-devis" tone="navy">
        <Container>
          <h2 id="contact-devis" className="text-2xl font-bold sm:text-3xl">
            Vous savez déjà ce dont vous avez besoin ?
          </h2>
          <p className="mt-4 max-w-2xl leading-relaxed text-navy-100">
            Le formulaire de devis ne vous posera que les questions utiles à votre
            service, et vous recevrez une référence dès l’envoi.
          </p>
          <div className="mt-8">
            <CtaLink href="/devis">Demander un devis</CtaLink>
          </div>
        </Container>
      </Section>

      <JsonLd data={breadcrumbJsonLd(TRAIL)} />
    </main>
  );
}
