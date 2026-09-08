import Link from 'next/link';

import type { IntakeSearchItem } from '@/lib/ops/intake-search';
import {
  cheminFicheDossier, cheminFicheLectureSeule, libelleEtat, libelleMode,
} from './vocabulaire';

export function ResultatsRecherche(
  { items, hasMore = false }:
  { items: readonly IntakeSearchItem[]; hasMore?: boolean },
) {
  if (items.length === 0) {
    return (
      <p className="attenue ops-search-empty" data-test="recherche-vide">
        Aucun dossier ne correspond à cette recherche.
      </p>
    );
  }

  return (
    <ul className="liste-resultats ops-search-results">
      {items.map((item, rang) => (
        <li key={`${item.reference}-${rang}`}>
          <CarteDossier item={item} />
        </li>
      ))}
      {hasMore ? (
        <li className="attenue ops-search-truncated" data-test="recherche-tronquee">
          D’autres dossiers correspondent. Affinez votre recherche.
        </li>
      ) : null}
    </ul>
  );
}

function CarteDossier({ item }: { item: IntakeSearchItem }) {
  const contenu = <ContenuDossier item={item} />;

  if (item.detail_access === 'readonly') {
    return (
      <Link
        className="carte carte-lien ops-search-result-card"
        href={cheminFicheLectureSeule(item.reference)}
        data-test="dossier-lecture-seule"
      >
        {contenu}
        <p className="attenue ops-search-result-note">Dossier historique — lecture seule</p>
      </Link>
    );
  }

  if (item.detail_access !== 'full') {
    return (
      <section className="carte ops-search-result-card" data-test="dossier-historique">
        {contenu}
        <p className="attenue ops-search-result-note">
          Référence globale indisponible — consultation détaillée impossible.
        </p>
      </section>
    );
  }

  return (
    <Link
      className="carte carte-lien ops-search-result-card"
      href={cheminFicheDossier(item.reference)}
      data-test="dossier-ouvrable"
    >
      {contenu}
    </Link>
  );
}

function ContenuDossier({ item }: { item: IntakeSearchItem }) {
  const titre = item.local_reference || item.reference;
  return (
    <div className="ops-search-result-content">
      <div className="ops-search-result-topline">
        <strong>{titre}</strong>
        {item.detail_access !== 'full' ? (
          <span className="badge">
            {item.detail_access === 'readonly' ? 'Lecture seule' : 'Dossier historique'}
          </span>
        ) : null}
      </div>
      <p className="ops-search-customer">{item.customer_name}</p>
      {item.customer_phone ? <p className="attenue ops-search-phone">{item.customer_phone}</p> : null}
      <p className="attenue ops-search-meta">
        {[
          libelleEtat(item.state),
          libelleMode(item.transport_mode),
          item.consolidation_reference,
          item.received_on,
        ].filter(Boolean).join(' · ')}
      </p>
      <p className="reference ops-search-reference">{item.reference}</p>
    </div>
  );
}
