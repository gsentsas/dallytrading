/**
 * Le panier scellé : ce qu'il contient, ce qu'il ne contiendra jamais.
 *
 * ## Aucun prix, jamais
 *
 * Le panier ne transporte que des références et des quantités. Pas de prix, pas
 * de sous-total, pas de devise.
 *
 * Le scellement les rendrait pourtant infalsifiables — et c'est précisément le
 * piège. Un prix scellé serait authentique, donc on serait tenté de s'en servir ;
 * et il serait authentiquement **périmé** dès la première révision tarifaire. Le
 * client verrait un montant, Odoo en calculerait un autre, et la différence
 * apparaîtrait à l'étape la plus coûteuse du parcours.
 *
 * Comme il n'y a pas de prix dans le cookie, il n'y a rien à réconcilier : le
 * montant est calculé par Odoo à chaque affichage. C'est le même raisonnement
 * que pour le cookie du portail, qui ne porte pas de `partner_id`.
 *
 * ## Chiffré, pas seulement signé
 *
 * Le panier d'un visiteur anonyme est une information commerciale : ce qu'il
 * regarde, en quelle quantité. Un cookie signé serait lisible en clair dans les
 * outils du navigateur, dans un cache disque, dans une capture d'écran de
 * rapport de bug. AES-256-GCM le chiffre **et** l'authentifie.
 *
 * ## L'identifiant de panier
 *
 * Un UUID engendré à la première mise au panier, conservé ensuite. Il ne sert à
 * rien dans ce cycle — il servira de clé d'idempotence au moment de la commande,
 * pour qu'un double clic ne produise pas deux commandes. Il est créé maintenant
 * parce qu'il doit être stable sur toute la durée de vie du panier : le fabriquer
 * au moment du paiement le rendrait différent à chaque tentative, ce qui est
 * exactement le contraire d'une clé d'idempotence.
 */

import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
  createHash,
  randomUUID,
} from 'node:crypto';

/** Nom dédié, distinct du cookie de session du portail. */
export const CART_COOKIE = 'dt_shop_cart';

/**
 * Durée de vie du panier.
 *
 * Trente jours : assez long pour qu'un visiteur revienne finir ses achats, assez
 * court pour qu'un panier oublié ne réapparaisse pas des mois plus tard avec des
 * produits dépubliés depuis. La dépublication est de toute façon revérifiée à
 * chaque résolution.
 */
export const CART_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

/**
 * Bornes du panier.
 *
 * Elles existent des deux côtés — ici et dans le contrôleur Odoo — parce
 * qu'elles protègent deux choses différentes. Ici : la taille du cookie, qu'un
 * navigateur tronque silencieusement au-delà d'environ 4 ko. Là-bas : le coût
 * d'une requête. Le jour où l'un des deux contrôles est contourné, l'autre tient
 * encore.
 */
export const MAX_CART_LINES = 20;
export const MAX_LINE_QUANTITY = 999;

/** Longueur maximale d'une référence, alignée sur le slug côté Odoo. */
const MAX_REFERENCE_LENGTH = 128;

/**
 * Alphabet admis pour une référence.
 *
 * Identique au slug côté Odoo. Le contrôle est ici et pas seulement là-bas parce
 * que la référence est réécrite dans le cookie : accepter n'importe quel texte
 * ferait du panier un stockage arbitraire de 4 ko chiffré par nos soins.
 */
const REFERENCE_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

const ALGORITHM = 'aes-256-gcm';
const IV_BYTES = 12;
const TAG_BYTES = 16;
const VERSION = 'v1';

/** Une ligne de panier. Deux champs, et pas un de plus. */
export interface CartLine {
  readonly reference: string;
  readonly quantity: number;
}

/** Le contenu du cookie. */
export interface Cart {
  /** Clé d'idempotence de la future commande. Stable sur la vie du panier. */
  readonly cartId: string;
  readonly lines: readonly CartLine[];
}

export class CartError extends Error {}

/** Un panier vide, avec un identifiant neuf. */
export function newCart(): Cart {
  return { cartId: randomUUID(), lines: [] };
}

/**
 * Dérive une clé de 32 octets depuis le secret de configuration.
 *
 * SHA-256 et non un KDF lent : le secret est un aléa de haute entropie fourni
 * par la configuration, pas un mot de passe humain. Un PBKDF2 coûterait à chaque
 * requête sans rien renforcer.
 */
function keyFrom(secret: string): Buffer {
  return createHash('sha256').update(secret, 'utf8').digest();
}

/** Scelle un panier. Le résultat est opaque et infalsifiable. */
export function sealCart(cart: Cart, secret: string): string {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv(ALGORITHM, keyFrom(secret), iv);
  const payload = Buffer.from(JSON.stringify(cart), 'utf8');
  const encrypted = Buffer.concat([cipher.update(payload), cipher.final()]);
  const tag = cipher.getAuthTag();
  return [
    VERSION,
    iv.toString('base64url'),
    encrypted.toString('base64url'),
    tag.toString('base64url'),
  ].join('.');
}

/**
 * Ouvre un panier scellé, ou échoue.
 *
 * Toute anomalie donne la même erreur : version inconnue, structure invalide,
 * tag qui ne correspond pas, JSON illisible, champ absent, ligne hors bornes.
 * Distinguer les cas n'apprendrait rien d'utile au serveur et donnerait un
 * signal à qui teste des variantes.
 *
 * Les bornes sont revérifiées **à l'ouverture** et pas seulement à l'écriture.
 * Un cookie authentiquement scellé peut être ancien : issu d'une version qui
 * admettait d'autres limites, ou d'un déploiement où le plafond était plus haut.
 * Faire confiance à un paquet parce qu'il est authentique, c'est confondre
 * « nous l'avons écrit » et « il est encore valide ».
 */
export function unsealCart(sealed: string, secret: string): Cart {
  const parts = sealed.split('.');
  if (parts.length !== 4 || parts[0] !== VERSION) {
    throw new CartError('invalid cart cookie');
  }
  const [, ivPart, dataPart, tagPart] = parts;
  try {
    const iv = Buffer.from(ivPart as string, 'base64url');
    const data = Buffer.from(dataPart as string, 'base64url');
    const tag = Buffer.from(tagPart as string, 'base64url');
    if (iv.length !== IV_BYTES || tag.length !== TAG_BYTES) {
      throw new CartError('invalid cart cookie');
    }
    const decipher = createDecipheriv(ALGORITHM, keyFrom(secret), iv);
    decipher.setAuthTag(tag);
    const opened = Buffer.concat([decipher.update(data), decipher.final()]);
    return parseCart(JSON.parse(opened.toString('utf8')));
  } catch (error) {
    if (error instanceof CartError) throw error;
    throw new CartError('invalid cart cookie');
  }
}

/** Valide la forme d'un panier ouvert. Rien n'est réparé en silence. */
function parseCart(raw: unknown): Cart {
  if (typeof raw !== 'object' || raw === null) {
    throw new CartError('invalid cart cookie');
  }
  const candidate = raw as Partial<Cart>;
  if (typeof candidate.cartId !== 'string' || !isUuid(candidate.cartId)) {
    throw new CartError('invalid cart cookie');
  }
  if (!Array.isArray(candidate.lines) || candidate.lines.length > MAX_CART_LINES) {
    throw new CartError('invalid cart cookie');
  }

  const lines: CartLine[] = [];
  const seen = new Set<string>();
  for (const line of candidate.lines) {
    const parsed = parseLine(line);
    // Un doublon de référence n'est pas récupérable sans décider quelle
    // quantité l'emporte, et ce n'est pas au lecteur d'un cookie de trancher.
    if (seen.has(parsed.reference)) {
      throw new CartError('invalid cart cookie');
    }
    seen.add(parsed.reference);
    lines.push(parsed);
  }
  return { cartId: candidate.cartId, lines };
}

function parseLine(raw: unknown): CartLine {
  if (typeof raw !== 'object' || raw === null) {
    throw new CartError('invalid cart cookie');
  }
  const candidate = raw as Record<string, unknown>;
  // Égalité d'ensembles et non simple présence : une clé supplémentaire signifie
  // que quelque chose a écrit dans le panier une donnée qui n'y a pas sa place —
  // un prix, par exemple. On refuse au lieu de l'ignorer.
  const keys = Object.keys(candidate).sort();
  if (keys.length !== 2 || keys[0] !== 'quantity' || keys[1] !== 'reference') {
    throw new CartError('invalid cart cookie');
  }
  const { reference, quantity } = candidate;
  if (!isValidReference(reference)) {
    throw new CartError('invalid cart cookie');
  }
  if (!isValidQuantity(quantity)) {
    throw new CartError('invalid cart cookie');
  }
  return { reference, quantity };
}

export function isValidReference(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= MAX_REFERENCE_LENGTH &&
    REFERENCE_PATTERN.test(value)
  );
}

export function isValidQuantity(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= 1 &&
    value <= MAX_LINE_QUANTITY
  );
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
}

/**
 * Fixe la quantité d'une référence. Zéro retire la ligne.
 *
 * Une seule opération pour ajouter, modifier et retirer, parce que les trois se
 * réduisent à « cette référence doit finir à cette quantité ». Trois fonctions
 * distinctes auraient trois façons de dépasser les bornes.
 *
 * L'ordre des lignes existantes est conservé : un panier qui se réordonne à
 * chaque modification est désagréable à utiliser, et sur une page qui se
 * re-rend, la ligne qu'on vient de toucher sauterait ailleurs.
 */
export function setLine(cart: Cart, reference: string, quantity: number): Cart {
  if (!isValidReference(reference)) {
    throw new CartError('invalid reference');
  }
  if (quantity !== 0 && !isValidQuantity(quantity)) {
    throw new CartError('invalid quantity');
  }

  const lines = cart.lines.filter((line) => line.reference !== reference);
  if (quantity === 0) {
    return { cartId: cart.cartId, lines };
  }

  const existant = cart.lines.some((line) => line.reference === reference);
  if (!existant && lines.length >= MAX_CART_LINES) {
    throw new CartError('cart is full');
  }

  // Réinsérer à sa place quand la ligne existait déjà, l'ajouter à la fin sinon.
  const modifiee: CartLine = { reference, quantity };
  if (!existant) {
    return { cartId: cart.cartId, lines: [...lines, modifiee] };
  }
  return {
    cartId: cart.cartId,
    lines: cart.lines.map((line) =>
      line.reference === reference ? modifiee : line,
    ),
  };
}

/** Vide le panier en gardant son identifiant. */
export function clearLines(cart: Cart): Cart {
  return { cartId: cart.cartId, lines: [] };
}

/** Options du cookie. `secure` seulement hors développement local. */
export function cartCookieOptions(isProduction: boolean) {
  return {
    httpOnly: true,
    secure: isProduction,
    // Lax : un retour depuis une page externe — un lien partagé, un e-mail — doit
    // conserver le panier. Les mutations passent par des routes POST protégées
    // par le contrôle d'Origin.
    sameSite: 'lax' as const,
    path: '/',
    maxAge: CART_MAX_AGE_SECONDS,
    // Aucun `Domain=` : le cookie reste lié à l'hôte exact qui l'a posé. Un
    // `Domain=.dallytrading.com` l'enverrait à tous les sous-domaines, dont
    // `crm.dallytrading.com`, qui n'a aucune raison de le recevoir.
  };
}
