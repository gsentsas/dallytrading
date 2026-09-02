import Link from 'next/link';

import type { IntakeSearchItem } from '@/lib/ops/intake-search';
import {
  cheminFicheDossier, cheminFicheLectureSeule, libelleEtat, libelleMode,
} from './vocabulaire';

/**
 * La liste des dossiers trouvés.
 *
 * ## Trois natures de résultat, une seule liste
 *
 * Un dossier né de Dally Ops s'ouvre en entier : sa carte mène à la fiche
 * complète. Un dossier repris s'ouvre en lecture seule, et le dit. Un dossier
 * sans référence globale ne s'ouvre pas : aucune URL ne saurait le désigner
 * sans risquer d'ouvrir celui d'un autre client — sa carte reste inerte.
 *
 * La distinction n'est pas décidée ici. Elle est lue dans `detail_access`, que
 * le serveur calcule avec le domaine de la fiche elle-même. Reconstituer cette
 * règle dans le navigateur ferait promettre à l'interface un écran que le
 * serveur refuserait — et personne ne le verrait avant le comptoir.
 */
export function ResultatsRecherche(
  { items, hasMore = false }:
  { items: readonly IntakeSearchItem[]; hasMore?: boolean },
) {
  if (items.length === 0) {
    return (
      <p className="attenue" data-test="recherche-vide">
        Aucun dossier ne correspond à cette recherche.
      </p>
    );
  }

  return (
    <ul className="liste-resultats" style={{ listStyle: 'none', padding: 0 }}>
      {items.map((item, rang) => (
        // La référence est vide sur un dossier sans identité globale : deux
        // d'entre eux partageraient la même clé.
        <li key={`${item.reference}-${rang}`} style={{ marginBottom: '0.75rem' }}>
          <CarteDossier item={item} />
        </li>
      ))}
      {hasMore ? (
        <li className="attenue" data-test="recherche-tronquee">
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
        className="carte carte-lien"
        href={cheminFicheLectureSeule(item.reference)}
        data-test="dossier-lecture-seule"
      >
        {contenu}
        <p className="attenue" style={{ margin: '0.5rem 0 0', fontSize: '0.85rem' }}>
          Dossier historique — lecture seule
        </p>
      </Link>
    );
  }

  // Sans référence globale, aucun lien : il existe, mais rien ne peut le
  // désigner sans ambiguïté. Une carte inerte dit la vérité ; un lien
  // ouvrirait le dossier d'un autre client.
  if (item.detail_access !== 'full') {
    return (
      <section className="carte" data-test="dossier-historique">
        {contenu}
        <p className="attenue" style={{ margin: '0.5rem 0 0', fontSize: '0.85rem' }}>
          Référence globale indisponible — consultation détaillée impossible.
        </p>
      </section>
    );
  }

  return (
    <Link
      className="carte carte-lien"
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
    <>
      <strong>{titre}</strong>
      {item.detail_access !== 'full' ? (
        <span className="badge" style={{ marginLeft: '0.5rem' }}>
          {item.detail_access === 'readonly' ? 'Lecture seule' : 'Dossier historique'}
        </span>
      ) : null}
      <p style={{ margin: '0.25rem 0 0' }}>{item.customer_name}</p>
      {item.customer_phone ? (
        <p className="attenue" style={{ margin: 0 }}>{item.customer_phone}</p>
      ) : null}
      <p className="attenue" style={{ margin: '0.25rem 0 0', fontSize: '0.85rem' }}>
        {[
          libelleEtat(item.state),
          libelleMode(item.transport_mode),
          item.consolidation_reference,
          item.received_on,
        ].filter(Boolean).join(' · ')}
      </p>
      {/* La référence globale reste lisible : c'est elle qui identifie le
          dossier sans ambiguïté, et c'est elle qu'on dicte au téléphone. */}
      <p className="reference" style={{ margin: '0.25rem 0 0' }}>{item.reference}</p>
    </>
  );
}
