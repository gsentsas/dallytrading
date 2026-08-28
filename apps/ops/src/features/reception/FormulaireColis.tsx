'use client';

import { useRef, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';

import type {
  FamilleTarifaire,
  ResultatIntake,
} from '@/lib/ops/intakes';

interface Saisie {
  packageType: 'parcel' | 'pallet' | 'crate' | 'bag' | 'drum' | 'other';
  goodsCategory: string;
  description: string;
  quantity: string;
  announcedWeight: string;
  exactWeight: string;
  length: string;
  width: string;
  height: string;
  billingMethod: 'real' | 'volumetric' | 'quote';
  tariffFamilyCode: string;
  customsValue: string;
}

type Etat =
  | { nom: 'saisie' }
  | { nom: 'envoi' }
  | { nom: 'erreur'; message: string }
  | { nom: 'abouti'; resultat: ResultatIntake };

const TYPES = [
  ['parcel', 'Colis'],
  ['pallet', 'Palette'],
  ['crate', 'Caisse'],
  ['bag', 'Sac'],
  ['drum', 'Fût'],
  ['other', 'Autre'],
] as const;

function nombre(
  valeur: string,
  nullable = false,
): number | null {
  const nettoyee = valeur.trim();
  if (!nettoyee && nullable) return null;
  return Number(nettoyee);
}

function argent(
  valeur: number | null,
): string {
  if (valeur === null) return 'À définir';
  return new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency: 'EUR',
  }).format(valeur);
}

export function FormulaireColis({
  consolidation,
  customer,
  familles,
}: {
  consolidation: string;
  customer: string;
  familles: FamilleTarifaire[];
}) {
  const router = useRouter();
  const [saisie, setSaisie] = useState<Saisie>({
    packageType: 'parcel',
    goodsCategory: '',
    description: '',
    quantity: '1',
    announcedWeight: '',
    exactWeight: '',
    length: '',
    width: '',
    height: '',
    billingMethod: 'real',
    tariffFamilyCode: familles[0]?.code ?? '',
    customsValue: '',
  });
  const [etat, setEtat] = useState<Etat>({ nom: 'saisie' });
  const requestUuid = useRef<string | null>(null);
  const lineUuid = useRef<string | null>(null);

  function modifier<K extends keyof Saisie>(
    champ: K,
    valeur: Saisie[K],
  ) {
    setSaisie((precedente) => ({
      ...precedente,
      [champ]: valeur,
    }));
    requestUuid.current = null;
    lineUuid.current = null;
  }

  function valider(): string | null {
    if (!saisie.goodsCategory.trim()) {
      return 'La catégorie est obligatoire.';
    }
    if (!saisie.description.trim()) {
      return 'La désignation est obligatoire.';
    }
    const quantite = Number(saisie.quantity);
    if (!Number.isInteger(quantite) || quantite <= 0) {
      return 'La quantité doit être un entier supérieur à zéro.';
    }
    if (
      saisie.announcedWeight.trim()
      && Number(saisie.announcedWeight) < 0
    ) {
      return 'Le poids annoncé ne peut pas être négatif.';
    }
    if (
      !saisie.exactWeight.trim()
      || Number(saisie.exactWeight) <= 0
    ) {
      return 'Le poids exact total doit être supérieur à zéro.';
    }
    const dimensions = [
      saisie.length, saisie.width, saisie.height,
    ];
    const presentes = dimensions.filter(
      (valeur) => valeur.trim(),
    ).length;
    if (
      (presentes !== 0 && presentes !== 3)
      || (
        presentes === 3
        && dimensions.some((valeur) => Number(valeur) <= 0)
      )
    ) {
      return 'Renseignez les trois dimensions positives, ou aucune.';
    }
    if (
      saisie.billingMethod === 'volumetric'
      && presentes !== 3
    ) {
      return 'Les dimensions sont obligatoires en volumétrique.';
    }
    if (!saisie.tariffFamilyCode) {
      return 'La famille tarifaire est obligatoire.';
    }
    if (
      !saisie.customsValue.trim()
      || Number(saisie.customsValue) <= 0
    ) {
      return 'La valeur déclarée doit être supérieure à zéro.';
    }
    return null;
  }

  async function enregistrer(
    evenement: FormEvent<HTMLFormElement>,
  ) {
    evenement.preventDefault();
    const probleme = valider();
    if (probleme) {
      setEtat({ nom: 'erreur', message: probleme });
      return;
    }
    requestUuid.current ??= crypto.randomUUID();
    lineUuid.current ??= crypto.randomUUID();
    setEtat({ nom: 'envoi' });

    try {
      const reponse = await fetch('/api/intakes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_uuid: requestUuid.current,
          consolidation_reference: consolidation,
          customer_reference: customer,
          received_on: new Date().toISOString().slice(0, 10),
          line: {
            line_uuid: lineUuid.current,
            package_type: saisie.packageType,
            goods_category: saisie.goodsCategory.trim(),
            description: saisie.description.trim(),
            quantity: Number(saisie.quantity),
            announced_weight_kg: nombre(
              saisie.announcedWeight, true,
            ),
            exact_weight_kg: nombre(saisie.exactWeight),
            length_cm: nombre(saisie.length, true),
            width_cm: nombre(saisie.width, true),
            height_cm: nombre(saisie.height, true),
            billing_method: saisie.billingMethod,
            tariff_family_code: saisie.tariffFamilyCode,
            customs_value_xof: nombre(saisie.customsValue),
          },
        }),
      });
      if (reponse.status === 401) {
        router.replace('/connexion');
        return;
      }
      const charge = (await reponse.json().catch(
        () => null,
      )) as {
        success?: boolean;
        data?: ResultatIntake;
        error?: string;
        code?: string;
      } | null;
      if (
        !reponse.ok
        || !charge?.success
        || !charge.data
      ) {
        if (charge?.code === 'idempotency_conflict') {
          requestUuid.current = null;
          lineUuid.current = null;
        }
        setEtat({
          nom: 'erreur',
          message: (
            charge?.error
            ?? 'Enregistrement impossible.'
          ),
        });
        return;
      }
      setEtat({ nom: 'abouti', resultat: charge.data });
    } catch {
      setEtat({
        nom: 'erreur',
        message: 'Service momentanément indisponible.',
      });
    }
  }

  if (etat.nom === 'abouti') {
    const intake = etat.resultat.intake;
    const ligne = intake.line;
    return (
      <section
        className="carte"
        data-testid="intake-enregistre"
      >
        <span className="succes">
          ✓ DOSSIER {intake.local_reference} ENREGISTRÉ
        </span>
        <p className="reference">{intake.reference}</p>
        <p>
          {ligne.quantity} × {ligne.description}
          {' — '}
          {ligne.exact_weight_kg} kg
        </p>
        {ligne.pricing_status === 'manual_required' ? (
          <>
            <p className="alerte">
              ⚠ TARIF À VALIDER
            </p>
            <p>Transport : À définir</p>
          </>
        ) : null}
        {ligne.pricing_status === 'quote' ? (
          <p>Tarification : Sur devis</p>
        ) : null}
        {ligne.pricing_status === 'automatic' ? (
          <p>
            Transport : {argent(ligne.transport_amount_eur)}
          </p>
        ) : null}
        <button
          type="button"
          className="secondaire"
          style={{ marginTop: '0.75rem' }}
        >
          + Ajouter un autre article
        </button>
        <button
          type="button"
          className="secondaire"
          style={{ marginTop: '0.75rem' }}
        >
          Terminer le dossier
        </button>
      </section>
    );
  }

  return (
    <form onSubmit={enregistrer} noValidate>
      {etat.nom === 'erreur' ? (
        <p className="erreur" role="alert">
          {etat.message}
        </p>
      ) : null}

      <label htmlFor="package-type">
        Type de colis
        <select
          id="package-type"
          value={saisie.packageType}
          onChange={(event) => modifier(
            'packageType',
            event.target.value as Saisie['packageType'],
          )}
        >
          {TYPES.map(([code, nom]) => (
            <option key={code} value={code}>{nom}</option>
          ))}
        </select>
      </label>

      <label htmlFor="goods-category">
        Catégorie
        <input
          id="goods-category"
          value={saisie.goodsCategory}
          onChange={(event) => modifier(
            'goodsCategory', event.target.value,
          )}
        />
      </label>

      <label htmlFor="description">
        Désignation
        <input
          id="description"
          value={saisie.description}
          onChange={(event) => modifier(
            'description', event.target.value,
          )}
        />
      </label>

      <label htmlFor="quantity">
        Quantité
        <input
          id="quantity"
          type="number"
          inputMode="numeric"
          min="1"
          step="1"
          value={saisie.quantity}
          onChange={(event) => modifier(
            'quantity', event.target.value,
          )}
        />
      </label>

      <label htmlFor="announced-weight">
        Poids annoncé (kg)
        <input
          id="announced-weight"
          type="number"
          inputMode="decimal"
          min="0"
          step="0.001"
          value={saisie.announcedWeight}
          onChange={(event) => modifier(
            'announcedWeight', event.target.value,
          )}
        />
      </label>

      <label htmlFor="exact-weight">
        Poids exact total (kg)
        <input
          id="exact-weight"
          type="number"
          inputMode="decimal"
          min="0.001"
          step="0.001"
          value={saisie.exactWeight}
          onChange={(event) => modifier(
            'exactWeight', event.target.value,
          )}
        />
      </label>

      <fieldset className="dimensions">
        <legend>Dimensions (cm)</legend>
        <div className="grille-trois">
          {([
            ['length', 'Longueur'],
            ['width', 'Largeur'],
            ['height', 'Hauteur'],
          ] as const).map(([champ, libelle]) => (
            <label key={champ} htmlFor={champ}>
              {libelle}
              <input
                id={champ}
                type="number"
                inputMode="decimal"
                min="0.1"
                step="0.1"
                value={saisie[champ]}
                onChange={(event) => modifier(
                  champ, event.target.value,
                )}
              />
            </label>
          ))}
        </div>
      </fieldset>

      <label htmlFor="billing-method">
        Méthode facturation
        <select
          id="billing-method"
          value={saisie.billingMethod}
          onChange={(event) => modifier(
            'billingMethod',
            event.target.value as Saisie['billingMethod'],
          )}
        >
          <option value="real">Poids réel</option>
          <option value="volumetric">Poids volumétrique</option>
          <option value="quote">Sur devis</option>
        </select>
      </label>

      <label htmlFor="tariff-family">
        Famille tarifaire
        <select
          id="tariff-family"
          value={saisie.tariffFamilyCode}
          onChange={(event) => modifier(
            'tariffFamilyCode', event.target.value,
          )}
        >
          {familles.map((famille) => (
            <option
              key={famille.code}
              value={famille.code}
            >
              {famille.name}
            </option>
          ))}
        </select>
      </label>

      <label htmlFor="customs-value">
        Valeur déclarée du contenu — pas le prix du transport
        <input
          id="customs-value"
          type="number"
          inputMode="numeric"
          min="1"
          step="1"
          value={saisie.customsValue}
          onChange={(event) => modifier(
            'customsValue', event.target.value,
          )}
        />
      </label>

      <button
        type="submit"
        disabled={
          etat.nom === 'envoi' || familles.length === 0
        }
      >
        {etat.nom === 'envoi'
          ? 'Enregistrement…'
          : 'ENREGISTRER LA RÉCEPTION'}
      </button>
    </form>
  );
}

