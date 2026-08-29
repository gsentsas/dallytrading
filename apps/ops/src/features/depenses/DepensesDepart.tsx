'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import type { DepenseLue, ListeDepenses } from '@/lib/ops/expenses';
import { LIBELLES_MODE } from '@/lib/ops/expenses-vocabulaire';
import { enJour } from '@/features/reception/format';
import { LIBELLE_ETAT, montant } from '@/features/depenses/format';
import { EnvoiJustificatif, type IssueJustificatif } from '@/features/depenses/EnvoiJustificatif';
import { FormulaireDepense, type IssueDepense } from '@/features/depenses/FormulaireDepense';

type Vue =
  | { nom: 'liste' }
  | { nom: 'ajout' }
  | { nom: 'photo'; depense: DepenseLue };

/**
 * Les dépenses d'un départ.
 *
 * Après chaque écriture, l'écran relit la liste depuis le serveur au lieu de
 * la recalculer : les totaux appartiennent à Odoo, et deux arithmétiques
 * finissent toujours par diverger.
 *
 * Les totaux sont donnés **par devise**, jamais additionnés entre elles.
 * Convertir demanderait un taux ; un taux choisi dans le navigateur serait
 * faux la moitié du temps, et faux sur une pièce de caisse.
 */
export function DepensesDepart({
  liste,
  payeur,
}: {
  liste: ListeDepenses;
  payeur: string;
}) {
  const router = useRouter();
  const [vue, setVue] = useState<Vue>({ nom: 'liste' });

  async function enregistrer(demande: Record<string, unknown>): Promise<IssueDepense> {
    const reponse = await fetch('/api/expenses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(demande),
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

  async function envoyerPhoto(
    reference: string,
    fichier: File,
    requestUuid: string,
  ): Promise<IssueJustificatif> {
    const corps = new FormData();
    corps.append('request_uuid', requestUuid);
    corps.append('receipt', fichier);
    // Aucun en-tête `Content-Type` : c'est au navigateur de poser la frontière
    // multipart, et l'écrire à la main produirait un corps illisible.
    const reponse = await fetch(
      `/api/expenses/${encodeURIComponent(reference)}/receipt`,
      { method: 'POST', body: corps },
    );
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
        message: charge?.error ?? 'Envoi impossible.',
        ...(charge?.code ? { code: charge.code } : {}),
      };
    }
    return { ok: true };
  }

  if (vue.nom === 'ajout') {
    return (
      <FormulaireDepense
        depart={liste.consolidation_reference}
        payeur={payeur}
        onAnnuler={() => setVue({ nom: 'liste' })}
        soumettre={enregistrer}
      />
    );
  }

  if (vue.nom === 'photo') {
    const depense = vue.depense;
    return (
      <EnvoiJustificatif
        depense={depense}
        onAnnuler={() => setVue({ nom: 'liste' })}
        onTermine={() => {
          setVue({ nom: 'liste' });
          router.refresh();
        }}
        soumettre={(fichier, requestUuid) =>
          envoyerPhoto(depense.reference, fichier, requestUuid)}
      />
    );
  }

  return (
    <>
      {liste.summary.length > 0 ? (
        <section className="carte" data-testid="total-depenses">
          <p className="attenue" style={{ margin: 0 }}>Total dépensé</p>
          {liste.summary.map((ligne) => (
            <p className="reference" key={ligne.currency_code} style={{ margin: '0.2rem 0 0' }}>
              {montant(ligne.amount, ligne.currency_code)}
            </p>
          ))}
        </section>
      ) : null}

      {liste.expenses.length === 0 ? (
        <p className="attenue">Aucune dépense enregistrée sur ce départ.</p>
      ) : (
        liste.expenses.map((depense) => (
          <section className="carte" key={depense.reference}>
            <p className="reference" style={{ margin: 0 }}>
              {montant(depense.amount, depense.currency_code)}
            </p>
            <p style={{ margin: '0.2rem 0 0' }}>
              {depense.category} — {depense.description}
            </p>
            {depense.beneficiary ? (
              <p className="attenue" style={{ margin: 0 }}>
                Bénéficiaire : {depense.beneficiary}
              </p>
            ) : null}
            <p className="attenue" style={{ margin: 0 }}>
              {enJour(depense.expense_date)} · {LIBELLES_MODE[
                depense.payment_method as keyof typeof LIBELLES_MODE
              ] ?? depense.payment_method} · {depense.paid_by}
            </p>
            <p className="attenue" style={{ margin: 0 }}>
              {LIBELLE_ETAT[depense.state] ?? depense.state}
            </p>

            {depense.has_receipt ? (
              <p className="attenue" style={{ margin: '0.4rem 0 0' }}>
                Justificatif joint
              </p>
            ) : !depense.can_attach_receipt ? (
              <p className="attenue" style={{ margin: '0.4rem 0 0' }}>
                Sans justificatif — à compléter au back-office
              </p>
            ) : (
              <button
                type="button"
                className="secondaire"
                style={{ marginTop: '0.6rem' }}
                onClick={() => setVue({ nom: 'photo', depense })}
              >
                AJOUTER LA PHOTO
              </button>
            )}
          </section>
        ))
      )}

      <button type="button" onClick={() => setVue({ nom: 'ajout' })}>
        DÉCLARER UNE DÉPENSE
      </button>
    </>
  );
}
