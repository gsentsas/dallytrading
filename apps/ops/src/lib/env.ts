/**
 * La configuration de Dally Ops, validée au démarrage.
 *
 * Importer ce fichier place l'appelant dans le bundle serveur. C'est
 * délibéré : si un composant client l'importait un jour, la compilation
 * échouerait au lieu d'embarquer un secret dans le navigateur.
 *
 * ## Ce qui n'est pas ici, et ne doit jamais y venir
 *
 * Aucune clé d'intégration : ni `DALLY_FREIGHT_SYNC_API_KEY`, ni
 * `DALLY_FREIGHT_BILLING_API_KEY`, ni `ODOO_API_KEY`. L'application terrain
 * n'a pas de secret à présenter à Odoo — elle transporte la session de son
 * utilisateur, et rien d'autre. Une clé lue ici deviendrait accessible à
 * toute la passerelle, et l'erreur d'architecture serait alors facile à
 * écrire ; son absence la rend impossible.
 */

import { z } from 'zod';

if (typeof window !== 'undefined') {
  throw new Error(
    "src/lib/env.ts est un module serveur : il ne doit jamais être importé " +
      "depuis un composant client.",
  );
}

const httpUrl = z
  .string()
  .trim()
  .min(1)
  .refine((value) => /^https?:\/\//.test(value), 'URL http(s) attendue');

const schema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),

  /** Adresse publique de l'application. Décide aussi du drapeau `secure`. */
  OPS_PUBLIC_URL: httpUrl,

  /**
   * Secret de scellement du cookie Ops.
   *
   * Distinct de celui du portail, et le rester : un compromis du portail
   * client ne doit pas permettre de fabriquer un cookie d'opérateur, ni
   * l'inverse. Trente-deux caractères au minimum — en deçà, la clé dérivée
   * n'apporterait qu'une illusion.
   */
  OPS_SESSION_SECRET: z
    .string()
    .min(32, 'OPS_SESSION_SECRET doit faire au moins 32 caractères'),

  ODOO_URL: httpUrl,
  ODOO_DATABASE: z.string().trim().min(1),
  ODOO_TIMEOUT_MS: z.coerce.number().int().positive().max(120_000).default(15_000),
});

export type OpsEnv = z.output<typeof schema>;

let cache: OpsEnv | null = null;

export function opsEnv(): OpsEnv {
  if (cache) return cache;
  const parsed = schema.safeParse(process.env);
  if (!parsed.success) {
    // Les valeurs ne sont jamais réaffichées : seuls les noms manquants le
    // sont. Un message d'erreur qui recopie un secret finit dans un journal.
    const champs = parsed.error.issues.map((issue) => issue.path.join('.')).join(', ');
    throw new Error(`Configuration Dally Ops invalide : ${champs}`);
  }
  cache = parsed.data;
  return cache;
}

/** Le cookie ne porte `Secure` que si l'application est servie en HTTPS. */
export function opsUsesHttps(): boolean {
  return opsEnv().OPS_PUBLIC_URL.startsWith('https://');
}

/** Pour les tests : repart d'une configuration non lue. */
export function resetOpsEnv(): void {
  cache = null;
}
