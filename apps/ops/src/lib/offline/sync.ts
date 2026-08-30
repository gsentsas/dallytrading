/**
 * Le moteur de synchronisation.
 *
 * ## La seule règle qui compte
 *
 * `synced` s'écrit après une réponse positive du serveur. Pas avant. Ni le
 * départ d'un `fetch`, ni `navigator.onLine`, ni la disparition momentanée de
 * l'opération hors de la file ne valent confirmation. Un opérateur qui lit
 * « synchronisé » doit pouvoir fermer son téléphone.
 *
 * ## Le cas qui commande la conception : le silence ambigu
 *
 * Le POST part, Odoo écrit, la réponse se perd. Le navigateur ne voit qu'un
 * délai dépassé et ne peut pas savoir si l'objet existe. La seule conduite
 * sûre est de **conserver l'opération, avec le même identifiant de demande**,
 * et de rejouer : le serveur reconnaîtra son propre travail et rendra l'objet
 * existant. Abandonner créerait un trou ; recommencer avec un identifiant neuf
 * créerait un doublon — et sur une remise de caisse, un doublon est de
 * l'argent inventé.
 *
 * ## Ce que le moteur ne fait jamais
 *
 * Il ne réécrit pas un identifiant de demande, ne devine pas un numéro de
 * dossier, ne réaffecte pas un départ fermé, et n'envoie pas l'opération d'un
 * opérateur avec la session d'un autre.
 */

import { avecBail } from '@/lib/offline/lease';
import {
  corpsDeLaMutation, DESCRIPTEURS,
} from '@/lib/offline/operations';
import {
  enfantsDe, marquerAuthRequise, marquerBloque, marquerEnCours, marquerErreur,
  marquerSynchronise, prochaineAEnvoyer, reporter, resoudreCible,
} from '@/lib/offline/queue';
import type { MutationLocale } from '@/lib/offline/types';

/** Au-delà, on cesse d'attendre la réponse — sans rien conclure de l'objet. */
export const DELAI_ENVOI_MS = 20_000;

/**
 * Ce qu'une tentative a produit.
 *
 * `ambigu` est un verdict à part entière : le réseau a coupé, et **on ne sait
 * pas** si le serveur a écrit. Le confondre avec un échec ferait perdre des
 * opérations réussies ; le confondre avec un succès en inventerait.
 */
export type Verdict =
  | { readonly issue: 'succes'; readonly reference: string | null }
  | { readonly issue: 'ambigu'; readonly code: string; readonly message: string }
  | { readonly issue: 'transitoire'; readonly code: string; readonly message: string }
  | { readonly issue: 'authentification' }
  | { readonly issue: 'metier'; readonly code: string; readonly message: string };

interface ChargeReponse {
  readonly success?: boolean;
  readonly data?: unknown;
  readonly error?: string;
  readonly code?: string;
}

/**
 * Traduit une réponse HTTP en verdict.
 *
 * Le classement suit ce que l'opérateur doit faire, pas ce que le protocole
 * raconte : réessayer tout seul, se reconnecter, ou corriger quelque chose.
 */
export function classer(
  statut: number,
  charge: ChargeReponse | null,
  reference: string | null,
): Verdict {
  if (statut === 200 && charge?.success) return { issue: 'succes', reference };
  if (statut === 401 || statut === 403) return { issue: 'authentification' };
  if (statut === 429 || statut >= 500) {
    return {
      issue: 'transitoire',
      code: charge?.code ?? String(statut),
      message: charge?.error ?? 'Service momentanément indisponible.',
    };
  }
  // 400, 409, 415, 422 : le serveur a compris et refuse. Rejouer à l'identique
  // ne changerait rien, et boucler tiendrait la file occupée pour rien.
  return {
    issue: 'metier',
    code: charge?.code ?? String(statut),
    message: charge?.error ?? 'Cette opération a été refusée.',
  };
}

/** Envoie une opération, une fois, et rend le verdict. */
export async function tenter(mutation: MutationLocale): Promise<Verdict> {
  const descripteur = DESCRIPTEURS[mutation.operation_type];
  if (descripteur.exigeCible && !mutation.target_reference) {
    return {
      issue: 'metier', code: 'missing_target',
      message: 'L’opération dont celle-ci dépend n’est pas encore synchronisée.',
    };
  }

  const minuteur = new AbortController();
  const echeance = setTimeout(() => minuteur.abort(), DELAI_ENVOI_MS);
  try {
    const reponse = await fetch(descripteur.chemin(mutation), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corpsDeLaMutation(mutation)),
      signal: minuteur.signal,
    });
    const charge = (await reponse.json().catch(() => null)) as ChargeReponse | null;
    return classer(
      reponse.status, charge,
      charge?.success ? descripteur.reference(charge.data) : null,
    );
  } catch (erreur) {
    // Réseau coupé ou délai dépassé : le serveur a peut-être écrit. On ne
    // tranche pas, on conserve, et on rejouera avec le même identifiant.
    const interrompu = erreur instanceof Error && erreur.name === 'AbortError';
    return {
      issue: 'ambigu',
      code: interrompu ? 'timeout' : 'network',
      message: interrompu
        ? 'Le serveur n’a pas répondu à temps.'
        : 'Réseau indisponible.',
    };
  } finally {
    clearTimeout(echeance);
  }
}

/** Applique le verdict à la file, et propage aux enfants s'il le faut. */
export async function appliquer(
  mutation: MutationLocale,
  verdict: Verdict,
): Promise<void> {
  if (verdict.issue === 'succes') {
    await marquerSynchronise(mutation.local_id, verdict.reference);
    // Les enfants attendaient cette référence : le vrai `Axxx`, par exemple.
    if (verdict.reference) {
      for (const enfant of await enfantsDe(mutation.local_id)) {
        if (!enfant.target_reference) {
          await resoudreCible(enfant.local_id, verdict.reference);
        }
      }
    }
    return;
  }
  if (verdict.issue === 'authentification') {
    await marquerAuthRequise(mutation.local_id);
    return;
  }
  if (verdict.issue === 'ambigu' || verdict.issue === 'transitoire') {
    await reporter(mutation.local_id, verdict.code, verdict.message);
    return;
  }
  await marquerErreur(mutation.local_id, verdict.code, verdict.message);
  // Un enfant posté sur un parent refusé viserait un objet inexistant.
  for (const enfant of await enfantsDe(mutation.local_id)) {
    if (enfant.status === 'pending' || enfant.status === 'draft_local') {
      await marquerBloque(
        enfant.local_id,
        'L’opération dont celle-ci dépend a été refusée.');
    }
  }
}

export interface ResultatSynchronisation {
  readonly traitees: number;
  readonly synchronisees: number;
  readonly reportees: number;
  readonly en_erreur: number;
  /** Vrai quand la file s'est arrêtée faute de session valide. */
  readonly authentification_requise: boolean;
}

/**
 * Vide la file, autant que possible, pour un opérateur donné.
 *
 * Séquentiel : une opération à la fois, dans l'ordre de création. Le
 * parallélisme ferait partir un enfant avant son parent, et gagnerait quelques
 * secondes au prix de l'ordre métier.
 *
 * Un seul onglet travaille à la fois — voir `lease.ts`. L'appel rend un
 * résultat vide, sans erreur, quand un autre onglet tient le bail.
 */
export async function synchroniser(
  ownerKey: string,
  options: { readonly limite?: number; readonly ignorerDelai?: boolean } = {},
): Promise<ResultatSynchronisation> {
  const limite = options.limite ?? 50;
  // Un geste explicite de l'opérateur passe outre le délai de reprise.
  //
  // Sans cela, appuyer sur « Synchroniser maintenant » juste après une coupure
  // ne ferait rien pendant plusieurs secondes, sans rien expliquer : l'écran
  // resterait identique et l'opérateur conclurait que le bouton est cassé. Le
  // délai protège le serveur des reprises **automatiques** ; il n'a pas à
  // contredire une demande humaine.
  const instant = options.ignorerDelai ? Number.MAX_SAFE_INTEGER : Date.now();
  const vide: ResultatSynchronisation = {
    traitees: 0, synchronisees: 0, reportees: 0, en_erreur: 0,
    authentification_requise: false,
  };
  const resultat = await avecBail(async () => {
    let traitees = 0;
    let synchronisees = 0;
    let reportees = 0;
    let en_erreur = 0;
    let authentification_requise = false;
    // Une passe tente chaque opération **au plus une fois**. Sans cela, une
    // opération reposée en `pending` redeviendrait aussitôt éligible et la
    // boucle la martèlerait jusqu'à la limite — d'autant plus vite quand le
    // délai de reprise est ignoré.
    const dejaTentees = new Set<string>();

    while (traitees < limite) {
      const suivante = await prochaineAEnvoyer(ownerKey, instant, dejaTentees);
      if (!suivante) break;
      dejaTentees.add(suivante.local_id);

      const enCours = await marquerEnCours(suivante.local_id);
      if (!enCours) break;
      const verdict = await tenter(enCours);
      await appliquer(enCours, verdict);

      traitees += 1;
      if (verdict.issue === 'succes') synchronisees += 1;
      else if (verdict.issue === 'metier') en_erreur += 1;
      else if (verdict.issue === 'authentification') {
        // Inutile d'insister : toutes les suivantes échoueraient pareil.
        authentification_requise = true;
        break;
      } else {
        reportees += 1;
        // Réseau absent : la file entière attendra le prochain réveil.
        if (verdict.code === 'network') break;
      }
    }
    return {
      traitees, synchronisees, reportees, en_erreur, authentification_requise,
    };
  });
  return resultat ?? vide;
}
