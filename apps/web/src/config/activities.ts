/**
 * The eleven DallyTrading activities.
 *
 * One source of truth for the navigation, the activity pages, the homepage grid,
 * the sitemap and the JSON-LD. Adding an activity here adds it everywhere.
 *
 * ## Relationship with the Odoo catalogue
 *
 * This is **editorial content** — headlines, prose, SEO copy — not business
 * configuration. The business configuration (which fields a quote form must ask
 * for) lives in Odoo and is fetched over `GET /api/v1/services`. The two are
 * connected by `serviceCode`, which deep-links an activity page to a pre-selected
 * service on `/devis`.
 *
 * That separation is deliberate: marketing copy changes weekly and belongs in
 * version control with the design; form requirements change rarely and belong
 * where the operators work. An activity whose `serviceCode` no longer exists in
 * Odoo simply loses its pre-selection — the form still works, and Odoo rejects an
 * unknown code, so a divergence fails loudly rather than silently.
 *
 * ## No invented facts
 *
 * There are no figures here: no volumes, no client counts, no years in business,
 * no certifications. Everything is a description of what is offered. Inventing a
 * credential on a company's own website is not a copywriting shortcut, it is a
 * false statement its salespeople then have to defend.
 */

export interface Activity {
  /** URL segment under /activites. Stable: it is an indexed URL. */
  readonly slug: string;
  /** Short label, for navigation and cards. */
  readonly label: string;
  /** Page H1 and card title. */
  readonly title: string;
  /** One sentence, used on cards and as the meta description base. */
  readonly summary: string;
  /** Opening paragraph of the activity page. */
  readonly intro: string;
  /** What the service concretely covers. */
  readonly includes: ReadonlyArray<string>;
  /** Who it is for. */
  readonly audience: ReadonlyArray<string>;
  /** Questions a prospect actually asks, answered honestly. */
  readonly faq: ReadonlyArray<{ question: string; answer: string }>;
  /** Matching `dally.service.type.code` in Odoo, for the /devis deep link. */
  readonly serviceCode: string;
  /**
   * A dedicated request page, when the activity has one.
   *
   * Sourcing has `/sourcing`, with its own form and FAQ. Without this, that page and
   * this activity page would both target "sourcing Sénégal" and compete for it —
   * keyword cannibalisation, with the two splitting the ranking signal. Pointing the
   * activity's CTA at the dedicated page makes the roles explicit: the activity page
   * explains, the dedicated page converts.
   */
  readonly requestHref?: string;
  /** Search terms this page legitimately targets (§49). */
  readonly keywords: ReadonlyArray<string>;
  /** Emphasised on the homepage. */
  readonly featured: boolean;
}

export const ACTIVITIES: ReadonlyArray<Activity> = [
  {
    slug: 'import-export',
    label: 'Import & Export',
    title: 'Import & Export',
    summary:
      'Nous prenons en charge vos opérations d’importation et d’exportation, de la recherche du fournisseur à la livraison finale.',
    intro:
      'Importer ou exporter suppose de coordonner un fournisseur, un transporteur, une douane et un destinataire, souvent dans des fuseaux et des langues différents. DallyTrading joue ce rôle de coordination pour les particuliers, les commerçants et les entreprises au Sénégal, et reste votre interlocuteur unique du début à la fin.',
    includes: [
      'Recherche et vérification de fournisseurs à l’international',
      'Négociation commerciale et conditions d’achat',
      'Organisation du transport, maritime, aérien ou routier',
      'Préparation des documents d’expédition et d’importation',
      'Accompagnement des formalités douanières',
      'Livraison jusqu’à votre entrepôt ou votre point de vente',
    ],
    audience: [
      'Commerçants qui importent régulièrement des marchandises',
      'Entreprises qui exportent des produits sénégalais',
      'Particuliers ayant un achat ponctuel à faire venir',
    ],
    faq: [
      {
        question: 'Pouvez-vous gérer une importation depuis n’importe quel pays ?',
        answer:
          'Nous travaillons principalement sur les axes Europe, Asie et Moyen-Orient vers le Sénégal, ainsi que sur les exportations depuis le Sénégal. Indiquez votre pays d’origine dans votre demande : nous vous confirmons rapidement si nous couvrons l’axe.',
      },
      {
        question: 'Quels documents dois-je fournir ?',
        answer:
          'Cela dépend de la marchandise et du régime douanier. Nous vous transmettons la liste exacte après avoir étudié votre dossier, plutôt que de vous demander des pièces inutiles à l’avance.',
      },
    ],
    serviceCode: 'import_export',
    keywords: [
      'import export Sénégal',
      'import export Dakar',
      'importer au Sénégal',
      'exporter du Sénégal',
      'commerce international Sénégal',
    ],
    featured: true,
  },
  {
    slug: 'logistique-transport',
    label: 'Logistique & Transport',
    title: 'Logistique & Transport',
    summary:
      'Transport, entreposage et distribution de vos marchandises, au Sénégal comme à l’international.',
    intro:
      'La logistique ne se limite pas au trajet principal. Entre le départ et la livraison, il faut stocker, regrouper, redistribuer et parfois reprendre un dossier en cours de route. DallyTrading organise cette chaîne et vous informe à chaque étape.',
    includes: [
      'Transport routier national et sous-régional',
      'Pré-acheminement et post-acheminement portuaire',
      'Entreposage et gestion de stock',
      'Groupage et dégroupage de marchandises',
      'Distribution vers plusieurs points de livraison',
      'Suivi documenté de chaque expédition',
    ],
    audience: [
      'Entreprises ayant des flux réguliers à organiser',
      'Importateurs qui doivent redistribuer après dédouanement',
      'Sociétés cherchant un prestataire logistique unique',
    ],
    faq: [
      {
        question: 'Assurez-vous le transport à l’intérieur du Sénégal ?',
        answer:
          'Oui, le transport routier national fait partie de nos activités, y compris en complément d’un fret maritime ou aérien que nous avons organisé.',
      },
      {
        question: 'Puis-je suivre ma marchandise ?',
        answer:
          'Chaque expédition reçoit une référence de suivi et un lien personnel. Vous consultez son statut et son trajet à tout moment depuis notre page de suivi.',
      },
    ],
    serviceCode: 'logistics',
    keywords: [
      'logistique Sénégal',
      'transport Dakar',
      'transporteur Sénégal',
      'entreposage Dakar',
    ],
    featured: true,
  },
  {
    slug: 'fret-maritime',
    label: 'Fret Maritime',
    title: 'Fret Maritime',
    summary:
      'Conteneur complet, groupage ou fret conventionnel, sur les principales lignes vers le Sénégal.',
    intro:
      'Le maritime reste la solution la plus économique pour les volumes importants et les marchandises non urgentes. DallyTrading réserve l’espace, organise l’empotage et suit le navire jusqu’à l’arrivée au port de Dakar.',
    includes: [
      'Conteneur complet 20 pieds, 40 pieds et high cube',
      'Groupage maritime pour les volumes réduits',
      'Fret conventionnel pour les marchandises hors gabarit',
      'Empotage, calage et sécurisation de la marchandise',
      'Documentation maritime et connaissement',
      'Suivi du navire et information à l’arrivée',
    ],
    audience: [
      'Importateurs de volumes conséquents',
      'Commerçants approvisionnant leur stock',
      'Entreprises exportant des produits en conteneur',
    ],
    faq: [
      {
        question: 'Combien de temps prend un transport maritime ?',
        answer:
          'Le délai dépend du port de départ, de la ligne maritime et des escales. Nous vous communiquons une estimation d’arrivée pour votre trajet précis dans notre devis, et nous la mettons à jour si elle évolue.',
      },
      {
        question: 'Comment le fret maritime est-il facturé ?',
        answer:
          'En conteneur complet, au conteneur. En groupage, au poids ou au volume selon lequel des deux est le plus élevé — un mètre cube compte généralement comme une tonne. Nous détaillons ce calcul dans le devis.',
      },
    ],
    serviceCode: 'freight_sea',
    keywords: [
      'fret maritime Sénégal',
      'fret maritime Dakar',
      'conteneur Sénégal',
      'transport maritime France Sénégal',
    ],
    featured: true,
  },
  {
    slug: 'fret-aerien',
    label: 'Fret Aérien',
    title: 'Fret Aérien',
    summary:
      'Solution rapide pour les expéditions urgentes, sensibles ou de forte valeur.',
    intro:
      'Quand le délai commande, l’aérien est la réponse. Il coûte davantage que le maritime, mais il se compte en jours plutôt qu’en semaines. DallyTrading organise l’enlèvement, la réservation et la remise à l’arrivée.',
    includes: [
      'Expéditions urgentes et délais courts',
      'Marchandises de forte valeur ou fragiles',
      'Pièces détachées et rechanges industriels',
      'Échantillons commerciaux et documents',
      'Lettre de transport aérien et documentation',
      'Enlèvement à l’origine et remise à destination',
    ],
    audience: [
      'Entreprises immobilisées par une pièce manquante',
      'Importateurs de produits à forte valeur ajoutée',
      'Sociétés envoyant des échantillons à un client',
    ],
    faq: [
      {
        question: 'Pourquoi mon devis aérien dépasse-t-il le poids réel ?',
        answer:
          'L’aérien facture le poids taxable : le plus élevé entre le poids réel et le volume converti, à raison d’un mètre cube pour environ 167 kg. Une marchandise légère mais volumineuse occupe de l’espace, et c’est cet espace qui est vendu. Nous indiquons systématiquement le calcul.',
      },
      {
        question: 'Quelles marchandises ne peuvent pas voyager par avion ?',
        answer:
          'Les matières dangereuses sont soumises à une réglementation stricte et parfois interdites. Décrivez votre marchandise dans votre demande : nous vérifions sa faisabilité avant de vous engager.',
      },
    ],
    serviceCode: 'freight_air',
    keywords: [
      'fret aérien Sénégal',
      'fret aérien Dakar',
      'transport aérien urgent Sénégal',
      'envoi express Dakar',
    ],
    featured: true,
  },
  {
    slug: 'transport-vehicules',
    label: 'Transport de Véhicules',
    title: 'Transport de Véhicules',
    summary:
      'Acheminement de voitures, utilitaires, engins et machines vers le Sénégal.',
    intro:
      'Faire venir un véhicule demande davantage qu’une place sur un navire : il faut le bon mode d’embarquement, les documents du véhicule, et une anticipation des formalités à l’arrivée. DallyTrading prend en charge l’ensemble.',
    includes: [
      'Voitures particulières et véhicules utilitaires',
      'Camions, engins de chantier et matériel agricole',
      'Choix du mode d’embarquement adapté au véhicule',
      'Vérification des documents du véhicule',
      'Organisation du transport jusqu’au port de départ',
      'Accompagnement des formalités à l’arrivée',
    ],
    audience: [
      'Particuliers important un véhicule',
      'Concessionnaires et revendeurs automobiles',
      'Entreprises important du matériel roulant',
    ],
    faq: [
      {
        question: 'Quels documents faut-il pour importer un véhicule ?',
        answer:
          'La carte grise ou le titre de propriété, la facture d’achat et vos pièces d’identité constituent la base. Les exigences varient selon l’âge et le type du véhicule : nous vous confirmons la liste applicable à votre cas.',
      },
      {
        question: 'Puis-je charger des affaires dans le véhicule ?',
        answer:
          'Cela dépend du mode d’embarquement et de la réglementation en vigueur. Posez-nous la question avant de charger : une déclaration incomplète peut bloquer le véhicule à l’arrivée.',
      },
    ],
    serviceCode: 'freight_vehicle',
    keywords: [
      'transport véhicule Sénégal',
      'importer voiture Sénégal',
      'transport voiture France Sénégal',
      'import véhicule Dakar',
    ],
    featured: true,
  },
  {
    slug: 'groupage',
    label: 'Groupage',
    title: 'Groupage',
    summary:
      'Partagez un conteneur avec d’autres expéditeurs et ne payez que le volume que vous occupez.',
    intro:
      'Un conteneur complet n’a pas de sens pour quelques cartons ou une palette. Le groupage consolide votre marchandise avec celle d’autres clients : vous accédez au tarif maritime sans avoir à remplir un conteneur entier.',
    includes: [
      'Consolidation de petits volumes',
      'Facturation au volume ou au poids occupé',
      'Réception et stockage avant départ',
      'Dégroupage à l’arrivée',
      'Suivi individuel de votre part de chargement',
      'Départs réguliers sur les axes principaux',
    ],
    audience: [
      'Petits commerçants et jeunes entreprises',
      'Particuliers ayant plusieurs colis ou une palette',
      'Importateurs testant un nouveau produit',
    ],
    faq: [
      {
        question: 'À partir de quel volume le groupage est-il intéressant ?',
        answer:
          'Le groupage est pertinent dès quelques cartons et jusqu’à plusieurs mètres cubes. Au-delà, un conteneur complet devient souvent plus économique. Nous comparons les deux options dans votre devis quand la question se pose.',
      },
      {
        question: 'Le groupage est-il plus lent ?',
        answer:
          'Oui, généralement : il faut attendre la constitution du chargement, puis dégrouper à l’arrivée. Si votre délai est contraint, dites-le : nous vous orienterons vers une solution adaptée plutôt que de vous laisser attendre.',
      },
    ],
    serviceCode: 'freight_groupage',
    keywords: [
      'groupage Sénégal',
      'groupage maritime Dakar',
      'groupage France Sénégal',
      'envoi palette Sénégal',
    ],
    featured: true,
  },
  {
    slug: 'commerce-trading',
    label: 'Commerce & Trading',
    title: 'Commerce & Trading',
    summary:
      'Négoce, courtage et représentation commerciale : nous rapprochons acheteurs et vendeurs.',
    intro:
      'Certaines opérations ne sont pas un transport mais une transaction : trouver un acheteur pour un lot, un vendeur pour un besoin, et sécuriser l’exécution entre les deux. DallyTrading intervient comme négociant ou comme intermédiaire, selon ce qui sert le mieux l’opération.',
    includes: [
      'Achat et revente de marchandises',
      'Mise en relation acheteurs et vendeurs',
      'Négociation des conditions commerciales',
      'Représentation commerciale au Sénégal',
      'Coordination logistique de l’opération',
      'Suivi de l’exécution jusqu’à la livraison',
    ],
    audience: [
      'Entreprises cherchant un débouché pour un lot',
      'Acheteurs à la recherche d’un produit précis',
      'Sociétés étrangères voulant être représentées au Sénégal',
    ],
    faq: [
      {
        question: 'Intervenez-vous comme acheteur ou comme intermédiaire ?',
        answer:
          'Les deux, selon l’opération. Nous précisons notre rôle dès la proposition, ainsi que notre rémunération : marge sur négoce ou commission d’intermédiation.',
      },
      {
        question: 'Traitez-vous toutes les catégories de produits ?',
        answer:
          'Nous privilégions les produits que nous connaissons et dont nous maîtrisons la chaîne. Soumettez-nous votre opportunité : nous vous dirons franchement si elle relève de notre périmètre.',
      },
    ],
    serviceCode: 'trade',
    // Sends the conversion intent to /trading rather than to the generic quote form.
    // The activity page explains the business; /trading is where a deal is proposed.
    // Without this split the two pages compete for the same query and Google picks
    // one — usually not the one that converts.
    requestHref: '/trading',
    keywords: [
      'trading Sénégal',
      'négoce international Sénégal',
      'commerce international Dakar',
      'représentation commerciale Sénégal',
    ],
    featured: true,
  },
  {
    slug: 'sourcing-international',
    label: 'Sourcing International',
    title: 'Sourcing International',
    summary:
      'Nous recherchons vos fournisseurs et vos produits, vérifions leur sérieux et négocions pour vous.',
    intro:
      'Trouver un fournisseur en ligne est facile ; trouver un fournisseur fiable ne l’est pas. Le sourcing consiste à identifier des candidats crédibles, comparer leurs offres, vérifier ce qu’ils annoncent et négocier des conditions tenables.',
    includes: [
      'Recherche de fournisseurs selon votre cahier des charges',
      'Recherche de produits et d’équivalences',
      'Comparaison des offres et des conditions',
      'Vérification préalable des fournisseurs',
      'Négociation des prix et des délais',
      'Organisation du transport une fois l’accord conclu',
    ],
    audience: [
      'Commerçants voulant sécuriser un approvisionnement',
      'Entreprises lançant un nouveau produit',
      'Acheteurs échaudés par un fournisseur défaillant',
    ],
    faq: [
      {
        question: 'De quelles informations avez-vous besoin pour démarrer ?',
        answer:
          'Une description du produit, une quantité approximative et un ordre de grandeur de budget suffisent pour commencer. Le budget compte autant que le produit : il détermine la gamme de fournisseurs à cibler.',
      },
      {
        question: 'Garantissez-vous la qualité du fournisseur ?',
        answer:
          'Nous procédons à des vérifications et nous vous restituons ce que nous constatons, y compris ce qui nous paraît douteux. Nous ne prétendons pas éliminer tout risque : nous le documentons pour que vous décidiez en connaissance de cause.',
      },
    ],
    serviceCode: 'sourcing',
    requestHref: '/sourcing',
    keywords: [
      'recherche fournisseur Sénégal',
      'trouver fournisseur Chine Sénégal',
      'recherche fabricant international',
    ],
    featured: true,
  },
  {
    slug: 'e-commerce',
    label: 'E-commerce',
    title: 'E-commerce',
    summary:
      'Vente en ligne et traitement des commandes, adossés à notre logistique.',
    intro:
      'Vendre en ligne suppose une logistique qui suit. DallyTrading rapproche les deux : le catalogue et la commande d’un côté, l’approvisionnement, le stock et la livraison de l’autre.',
    includes: [
      'Vente en ligne de produits sélectionnés',
      'Traitement et préparation des commandes',
      'Approvisionnement adossé à notre sourcing',
      'Livraison au Sénégal',
      'Suivi de commande pour le client final',
      'Accompagnement des commerçants vendant en ligne',
    ],
    audience: [
      'Particuliers achetant en ligne au Sénégal',
      'Commerçants souhaitant vendre en ligne',
      'Entreprises externalisant leur logistique e-commerce',
    ],
    faq: [
      {
        question: 'La boutique en ligne est-elle ouverte ?',
        answer:
          'Notre boutique est en cours de déploiement. En attendant, adressez-nous votre besoin par le formulaire ou sur WhatsApp : nous traitons votre commande directement.',
      },
    ],
    serviceCode: 'ecommerce',
    keywords: [
      'e-commerce Sénégal',
      'achat en ligne Sénégal',
      'vendre en ligne Dakar',
    ],
    featured: false,
  },
  {
    slug: 'agrobusiness',
    label: 'Agrobusiness',
    title: 'Agrobusiness',
    summary:
      'Produits agricoles : sourcing, conditionnement, export et distribution.',
    intro:
      'Les filières agricoles ont leurs contraintes propres : saisonnalité, conditionnement, délais courts et exigences sanitaires. DallyTrading intervient sur la chaîne, du producteur au marché, au Sénégal comme à l’export.',
    includes: [
      'Sourcing de produits agricoles',
      'Mise en relation avec des producteurs',
      'Conditionnement et préparation à l’expédition',
      'Export de produits sénégalais',
      'Distribution sur le marché local',
      'Organisation du transport adapté à la marchandise',
    ],
    audience: [
      'Producteurs cherchant des débouchés',
      'Acheteurs de produits agricoles',
      'Exportateurs de la filière',
    ],
    faq: [
      {
        question: 'Traitez-vous les produits périssables ?',
        answer:
          'Cela dépend du produit, du volume et de la destination : le froid et les délais imposent des contraintes fortes. Décrivez-nous votre produit et nous vous dirons ce qui est réalisable, sans promettre au-delà.',
      },
    ],
    serviceCode: 'agrobusiness',
    keywords: [
      'agrobusiness Sénégal',
      'export produits agricoles Sénégal',
      'commerce agricole Dakar',
    ],
    featured: false,
  },
  {
    slug: 'solutions-entreprises',
    label: 'Solutions Entreprises',
    title: 'Solutions Entreprises',
    summary:
      'Recherche de partenaires, représentation et accompagnement des entreprises au Sénégal.',
    intro:
      'S’implanter ou opérer au Sénégal sans y être présent demande un relais local. DallyTrading joue ce rôle : trouver les bons interlocuteurs, représenter votre société, et gérer l’opérationnel sur place.',
    includes: [
      'Recherche de partenaires et de prestataires locaux',
      'Représentation commerciale au Sénégal',
      'Accompagnement des entreprises étrangères',
      'Mise en relation avec des acteurs du secteur',
      'Coordination des opérations sur place',
      'Conseil sur les circuits commerciaux et logistiques',
    ],
    audience: [
      'Sociétés étrangères visant le marché sénégalais',
      'Entreprises ayant besoin d’un relais local',
      'Groupes cherchant un partenaire de confiance',
    ],
    faq: [
      {
        question: 'Quel type d’accompagnement proposez-vous exactement ?',
        answer:
          'Cela va de la simple mise en relation à la représentation suivie. Le périmètre se définit avec vous : décrivez votre besoin et nous vous proposerons un cadre précis plutôt qu’une offre générique.',
      },
    ],
    serviceCode: 'business_solutions',
    keywords: [
      'représentation commerciale Sénégal',
      'partenaire commercial Dakar',
      'accompagnement entreprise Sénégal',
    ],
    featured: false,
  },
];

/** Resolve an activity by slug. */
export function findActivity(slug: string): Activity | undefined {
  return ACTIVITIES.find((activity) => activity.slug === slug);
}

/** Activities emphasised on the homepage. */
export function featuredActivities(): ReadonlyArray<Activity> {
  return ACTIVITIES.filter((activity) => activity.featured);
}

/** Every activity URL, for the sitemap and the navigation. */
export function activityHref(activity: Activity): string {
  return `/activites/${activity.slug}`;
}

/**
 * Deep link to the quote form with this activity's service pre-selected.
 *
 * The form validates the code against Odoo's catalogue, so a stale value here
 * loses the pre-selection rather than breaking the page.
 */
export function activityQuoteHref(activity: Activity): string {
  // A dedicated request page wins: it asks the right questions for that activity, and
  // pointing here avoids two pages competing for the same search intent.
  if (activity.requestHref) {
    return activity.requestHref;
  }
  return `/devis?service=${encodeURIComponent(activity.serviceCode)}`;
}
