'use client';

import { useRef, useState, type FormEvent } from 'react';

import { enfilerPuisSynchroniser } from '@/lib/offline/client';
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
  | { nom: 'abouti'; resultat: ResultatIntake }
  /**
   * Enregistré ici, pas encore au CRM.
   *
   * Un état à part entière, et non une variante d'erreur : la saisie n'est pas
   * perdue, et l'opérateur peut passer au colis suivant.
   */
  | { nom: 'en_file' };

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

/** Ce qu'une soumission déléguée renvoie au formulaire. */
export interface IssueSoumission {
  readonly ok: boolean;
  readonly message?: string;
  readonly code?: string;
}

/**
 * Le formulaire d'article, en trois emplois.
 *
 * Sans `soumettre`, il crée le dossier — c'est le comportement de l'étape 7.
 * Avec, il délègue l'envoi : l'ajout d'un article et la correction d'un
 * article existant réutilisent ainsi les mêmes champs et les mêmes règles de
 * validation, au lieu d'en entretenir trois copies.
 */
export function FormulaireColis({
  consolidation,
  customer,
  familles,
  valeursInitiales,
  libelleBouton,
  onAnnuler,
  soumettre,
  login,
}: {
  consolidation: string;
  customer: string;
  familles: FamilleTarifaire[];
  /**
   * L'opérateur, pour la file hors connexion.
   *
   * Absent dans les emplois délégués — ajout et correction d'article — dont
   * l'appelant possède déjà sa propre voie d'envoi.
   */
  login?: string;
  valeursInitiales?: Partial<Saisie>;
  libelleBouton?: string;
  onAnnuler?: () => void;
  soumettre?: (
    ligne: Record<string, unknown>,
    requestUuid: string,
  ) => Promise<IssueSoumission>;
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
    ...valeursInitiales,
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

  /** La ligne telle que l'API l'attend, quelle que soit la route visée. */
  function ligneSaisie(): Record<string, unknown> {
    return {
      line_uuid: lineUuid.current,
      package_type: saisie.packageType,
      goods_category: saisie.goodsCategory.trim(),
      description: saisie.description.trim(),
      quantity: Number(saisie.quantity),
      announced_weight_kg: nombre(saisie.announcedWeight, true),
      exact_weight_kg: nombre(saisie.exactWeight),
      length_cm: nombre(saisie.length, true),
      width_cm: nombre(saisie.width, true),
      height_cm: nombre(saisie.height, true),
      billing_method: saisie.billingMethod,
      tariff_family_code: saisie.tariffFamilyCode,
      customs_value_xof: nombre(saisie.customsValue),
    };
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

    if (soumettre) {
      // Ajout ou correction : l'appelant sait à quelle route s'adresser, le
      // formulaire garde la saisie et les identifiants stables entre deux
      // tentatives.
      try {
        const issue = await soumettre(
          ligneSaisie(), requestUuid.current,
        );
        if (!issue.ok) {
          if (issue.code === 'idempotency_conflict') {
            requestUuid.current = null;
          }
          setEtat({
            nom: 'erreur',
            message: issue.message ?? 'Enregistrement impossible.',
          });
          return;
        }
      } catch {
        setEtat({
          nom: 'erreur',
          message: 'Service momentanément indisponible.',
        });
      }
      return;
    }

    // Le corps est construit une fois : l'envoi direct et la mise en file
    // doivent porter exactement la même chose, sans quoi un rejeu serait rejeté
    // comme « déjà traité avec d'autres informations ».
    const corpsReception = () => ({
      consolidation_reference: consolidation,
      customer_reference: customer,
      received_on: new Date().toISOString().slice(0, 10),
      line: {
        line_uuid: lineUuid.current,
        package_type: saisie.packageType,
        goods_category: saisie.goodsCategory.trim(),
        description: saisie.description.trim(),
        quantity: Number(saisie.quantity),
        announced_weight_kg: nombre(saisie.announcedWeight, true),
        exact_weight_kg: nombre(saisie.exactWeight),
        length_cm: nombre(saisie.length, true),
        width_cm: nombre(saisie.width, true),
        height_cm: nombre(saisie.height, true),
        billing_method: saisie.billingMethod,
        tariff_family_code: saisie.tariffFamilyCode,
        customs_value_xof: nombre(saisie.customsValue),
      },
    });

    try {
      const reponse = await fetch('/api/intakes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_uuid: requestUuid.current,
          ...corpsReception(),
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
      // Réseau absent ou silence du serveur : on ne perd pas la saisie et on
      // ne prétend pas qu'elle est arrivée. Elle entre en file **avec le même
      // identifiant de demande**, celui tiré avant le premier envoi — sans
      // quoi une reprise deviendrait une seconde réception.
      if (!login) {
        setEtat({
          nom: 'erreur',
          message: 'Service momentanément indisponible.',
        });
        return;
      }
      try {
        await enfilerPuisSynchroniser(login, {
          operation_type: 'intake_create',
          payload: corpsReception(),
          resume: `${saisie.quantity} × ${saisie.description.trim()}`,
          // Toujours présent ici : il a été tiré avant la première tentative.
          ...(requestUuid.current ? { request_uuid: requestUuid.current } : {}),
        });
        setEtat({ nom: 'en_file' });
      } catch {
        setEtat({
          nom: 'erreur',
          message: 'Service momentanément indisponible.',
        });
      }
    }
  }

  if (etat.nom === 'en_file') {
    return (
      <section className="carte" data-testid="reception-en-file">
        <span className="succes">✓ ENREGISTRÉ SUR CET APPAREIL</span>
        {/* Jamais « enregistré dans Odoo » : le CRM n'a rien confirmé, et le
            numéro de dossier n'existe pas encore. Il est attribué par le
            serveur, au moment de la synchronisation. */}
        <p style={{ margin: '0.4rem 0 0' }}>
          Synchronisation avec le CRM en attente.
        </p>
        <p className="attenue" style={{ margin: '0.2rem 0 0' }}>
          Le numéro de dossier sera attribué par le CRM.
        </p>
        <button
          type="button"
          style={{ marginTop: '1rem' }}
          onClick={() => router.push('/synchronisation')}
        >
          VOIR LES OPÉRATIONS EN ATTENTE
        </button>
        <button
          type="button"
          className="secondaire"
          style={{ marginTop: '0.6rem' }}
          onClick={() => router.push('/')}
        >
          TERMINER
        </button>
      </section>
    );
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
          onClick={() => router.push(
            `/reception/dossier/${encodeURIComponent(
              intake.reference,
            )}`,
          )}
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
            : (libelleBouton ?? 'ENREGISTRER LA RÉCEPTION')}
      </button>
        {onAnnuler ? (
          <button
            type="button"
            className="secondaire"
            style={{ marginTop: '0.6rem' }}
            onClick={onAnnuler}
          >
            ANNULER
          </button>
        ) : null}
    </form>
  );
}

