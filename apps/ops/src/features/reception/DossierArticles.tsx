'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import type { Dossier, LigneLue } from '@/lib/ops/intake-lines';
import type { FamilleTarifaire } from '@/lib/ops/intakes';
import type { CanalPaiement } from '@/lib/ops/payments';
import { FormulairePaiement } from '@/features/reception/FormulairePaiement';
import { FormulaireWave } from '@/features/reception/FormulaireWave';
import type { ContexteWave } from '@/lib/ops/wave-payments';
import { FormulaireColis, type IssueSoumission } from '@/features/reception/FormulaireColis';

type Vue =
  | { nom: 'liste' }
  | { nom: 'ajout' }
  | { nom: 'correction'; ligne: LigneLue }
  | { nom: 'paiement' }
  | { nom: 'wave'; contexte: ContexteWave };

/** « 13,50 kg » — la virgule décimale que lit le terrain. */
function poids(valeur: number): string {
  return `${new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2, maximumFractionDigits: 3,
  }).format(valeur)} kg`;
}

/** « 44 280 FCFA » ou « 67,50 € », selon la devise réellement encaissée. */
function montantDevise(valeur: number, devise: string): string {
  return new Intl.NumberFormat('fr-FR', {
    style: 'currency', currency: devise,
    maximumFractionDigits: devise === 'XOF' ? 0 : 2,
  }).format(valeur);
}

const LIBELLE_COMPTABLE: Record<string, string> = {
  registered: 'Comptabilisé',
  pending: 'En attente de facturation',
  needs_review: 'Comptabilisation à vérifier par un responsable',
};

function argent(valeur: number | null): string {
  // « À définir » et non « 0 € » : un montant absent n'est pas un montant nul.
  if (valeur === null) return 'À définir';
  return new Intl.NumberFormat('fr-FR', {
    style: 'currency', currency: 'EUR',
  }).format(valeur);
}

/**
 * Le dossier et ses articles.
 *
 * Après chaque mutation, l'écran recharge le dossier depuis le serveur au lieu
 * de recalculer un total localement : les poids, les volumes et la
 * tarification appartiennent à Odoo, et deux arithmétiques finiraient par
 * diverger.
 */
export function DossierArticles({
  dossier,
  familles,
  canaux,
  collecteur,
}: {
  dossier: Dossier;
  familles: FamilleTarifaire[];
  canaux: CanalPaiement[];
  collecteur: string;
}) {
  const router = useRouter();
  const [vue, setVue] = useState<Vue>({ nom: 'liste' });
  const [erreurWave, setErreurWave] = useState<string | null>(null);

  async function envoyer(
    url: string,
    methode: 'POST' | 'PUT',
    corps: unknown,
  ): Promise<IssueSoumission> {
    const reponse = await fetch(url, {
      method: methode,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corps),
    });
    if (reponse.status === 401) {
      router.replace('/connexion');
      return { ok: false, message: 'Session expirée.' };
    }
    const charge = (await reponse.json().catch(() => null)) as
      | { success?: boolean; error?: string; code?: string }
      | null;
    if (!reponse.ok || !charge?.success) {
      return {
        ok: false,
        message: charge?.error ?? 'Enregistrement impossible.',
        ...(charge?.code ? { code: charge.code } : {}),
      };
    }
    setVue({ nom: 'liste' });
    router.refresh();
    return { ok: true };
  }

  /**
   * Ouvre l'encaissement Wave.
   *
   * Le contexte — bénéficiaire, client, devises disponibles — est relu au
   * serveur à l'ouverture plutôt que déduit ici : l'écran ne doit pas annoncer
   * un bénéficiaire que le serveur ne créditerait pas.
   */
  async function ouvrirWave() {
    const reponse = await fetch(
      `/api/shipments/${encodeURIComponent(dossier.reference)}/wave-context`);
    if (reponse.status === 401) {
      router.replace('/connexion');
      return;
    }
    const charge = (await reponse.json().catch(() => null)) as
      | { success?: boolean; data?: ContexteWave; error?: string }
      | null;
    if (!reponse.ok || !charge?.success || !charge.data) {
      setErreurWave(charge?.error ?? 'Service momentanément indisponible.');
      return;
    }
    setErreurWave(null);
    setVue({ nom: 'wave', contexte: charge.data });
  }

  if (vue.nom === 'wave') {
    return (
      <FormulaireWave
        contexte={vue.contexte}
        onAnnuler={() => setVue({ nom: 'liste' })}
        soumettre={(demande) => envoyer(
          `/api/shipments/${encodeURIComponent(dossier.reference)}/payments`,
          'POST',
          demande,
        )}
      />
    );
  }

  if (vue.nom === 'paiement') {
    return (
      <FormulairePaiement
        canaux={canaux}
        collecteur={collecteur}
        onAnnuler={() => setVue({ nom: 'liste' })}
        soumettre={(demande) => envoyer(
          `/api/intakes/${encodeURIComponent(dossier.reference)}/payments`,
          'POST',
          demande,
        )}
      />
    );
  }

  if (vue.nom === 'ajout') {
    return (
      <FormulaireColis
        consolidation={dossier.consolidation_reference}
        customer=""
        familles={familles}
        libelleBouton="ENREGISTRER L’ARTICLE"
        onAnnuler={() => setVue({ nom: 'liste' })}
        soumettre={(ligne, requestUuid) => envoyer(
          `/api/intakes/${encodeURIComponent(dossier.reference)}/lines`,
          'POST',
          { request_uuid: requestUuid, line: ligne },
        )}
      />
    );
  }

  if (vue.nom === 'correction') {
    const ligne = vue.ligne;
    return (
      <FormulaireColis
        consolidation={dossier.consolidation_reference}
        customer=""
        familles={familles}
        libelleBouton="ENREGISTRER LES CORRECTIONS"
        onAnnuler={() => setVue({ nom: 'liste' })}
        valeursInitiales={{
          packageType: ligne.package_type as never,
          goodsCategory: ligne.goods_category,
          description: ligne.description,
          quantity: String(ligne.quantity),
          announcedWeight: ligne.announced_weight_kg === null
            ? '' : String(ligne.announced_weight_kg),
          exactWeight: String(ligne.exact_weight_kg),
          length: ligne.length_cm === null ? '' : String(ligne.length_cm),
          width: ligne.width_cm === null ? '' : String(ligne.width_cm),
          height: ligne.height_cm === null ? '' : String(ligne.height_cm),
          billingMethod: ligne.billing_method,
          tariffFamilyCode: ligne.tariff_family_code,
          customsValue: String(ligne.customs_value_xof),
        }}
        soumettre={(saisie, requestUuid) => envoyer(
          `/api/intakes/${encodeURIComponent(dossier.reference)}`
            + `/lines/${encodeURIComponent(ligne.reference)}`,
          'PUT',
          {
            request_uuid: requestUuid,
            // La version lue à l'affichage : le serveur refuse si elle a
            // changé depuis, plutôt que d'écraser le travail d'un collègue.
            expected_revision: ligne.revision,
            line: { ...(saisie as object), line_uuid: ligne.reference },
          },
        )}
      />
    );
  }

  return (
    <>
      <h2 style={{ fontSize: '1.1rem', margin: '1.25rem 0 0.5rem' }}>
        ARTICLES REÇUS
      </h2>

      {dossier.lines.map((ligne, rang) => (
        <section className="carte" key={ligne.reference} data-testid="article">
          <strong>{rang + 1}. {ligne.description}</strong>
          <p className="attenue" style={{ margin: '0.2rem 0 0' }}>
            {ligne.quantity} × · {poids(ligne.exact_weight_kg)} · {ligne.goods_category}
          </p>
          <p style={{ margin: '0.2rem 0 0' }}>
            {ligne.pricing_status === 'quote'
              ? 'Tarification : Sur devis'
              : `Transport : ${argent(ligne.transport_amount_eur)}`}
          </p>
          {ligne.pricing_status === 'manual_required' ? (
            <p className="alerte">⚠ TARIF À VALIDER</p>
          ) : null}
          {dossier.editable ? (
            <button
              type="button"
              className="secondaire"
              style={{ marginTop: '0.6rem' }}
              onClick={() => setVue({ nom: 'correction', ligne })}
            >
              MODIFIER
            </button>
          ) : null}
        </section>
      ))}

      <section className="carte" data-testid="totaux">
        <p className="attenue" style={{ margin: 0 }}>
          {dossier.totals.lines_count} article(s) · {poids(dossier.totals.weight_kg)}
        </p>
        <p style={{ margin: '0.25rem 0 0' }}>
          Total transport : {argent(dossier.totals.transport_amount_eur)}
        </p>
      </section>

      <h2 style={{ fontSize: '1.1rem', margin: '1.25rem 0 0.5rem' }}>PAIEMENTS</h2>

      {dossier.payments.length === 0 ? (
        <p className="attenue" data-testid="aucun-paiement">
          Aucun paiement enregistré
        </p>
      ) : (
        dossier.payments.map((paiement) => (
          <section className="carte" key={paiement.reference} data-testid="paiement">
            <strong>
              {montantDevise(paiement.amount, paiement.currency_code)}
            </strong>
            <p className="attenue" style={{ margin: '0.2rem 0 0' }}>
              {paiement.payment_method.name} · {paiement.collector}
              {' · '}
              {paiement.payment_date}
            </p>
            <p
              className={paiement.accounting_status === 'needs_review'
                ? 'alerte' : 'attenue'}
              style={{ margin: '0.25rem 0 0' }}
            >
              {paiement.accounting_status === 'needs_review' ? '⚠ ' : ''}
              {LIBELLE_COMPTABLE[paiement.accounting_status]}
            </p>
          </section>
        ))
      )}

      {dossier.payment_summary.length > 1 ? (
        <section className="carte" data-testid="resume-paiements">
          {/* Un total par devise : aucune conversion n'est faite ici. */}
          {dossier.payment_summary.map((ligne) => (
            <p key={ligne.currency_code} style={{ margin: 0 }}>
              {montantDevise(ligne.amount, ligne.currency_code)}
            </p>
          ))}
        </section>
      ) : null}

      {erreurWave ? (
        <p className="erreur" role="alert">{erreurWave}</p>
      ) : null}

      <button
        type="button"
        style={{ marginTop: '0.75rem' }}
        onClick={() => { void ouvrirWave(); }}
      >
        PAIEMENT WAVE
      </button>

      <button
        type="button"
        className="secondaire"
        style={{ marginTop: '0.6rem' }}
        onClick={() => setVue({ nom: 'paiement' })}
      >
        + ENREGISTRER UN PAIEMENT
      </button>

      {dossier.editable ? (
        <button
          type="button"
          style={{ marginTop: '1rem' }}
          onClick={() => setVue({ nom: 'ajout' })}
        >
          + AJOUTER UN ARTICLE
        </button>
      ) : (
        <p className="alerte" data-testid="blocage">
          {dossier.edit_block_reason === 'billing_locked'
            ? 'Ce dossier est déjà engagé dans la facturation. '
              + 'Les articles ne peuvent plus être modifiés.'
            : 'Ce dossier n’est plus modifiable.'}
        </p>
      )}

      <button
        type="button"
        className="secondaire"
        style={{ marginTop: '0.6rem' }}
        onClick={() => router.push('/')}
      >
        TERMINER LA SAISIE
      </button>
    </>
  );
}
