import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

const { PhotosDossier } = await import('@/features/reception/PhotosDossier');

const SOURCE = readFileSync(
  fileURLToPath(new URL('./PhotosDossier.tsx', import.meta.url)), 'utf8');

const rendu = (peutGerer = true, etat = 'goods_received') =>
  renderToStaticMarkup(
    <PhotosDossier
      reference="AIR-DSS-CDG-2026-902-A001"
      etat={etat}
      peutGerer={peutGerer}
    />,
  );

describe('F01–F02 · la capacité, jamais le rôle', () => {
  it('F01 · sans `photo_manage`, le bloc n’existe pas du tout', () => {
    expect(rendu(false)).toBe('');
  });

  it('F01 · avec la capacité, le bloc s’annonce', () => {
    const html = rendu(true);
    expect(html).toContain('PHOTOS');
    expect(html).toContain('data-testid="photos-dossier"');
  });

  it('F02 · le composant ne raisonne sur aucun nom de rôle', () => {
    const sansCommentaires = SOURCE
      .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    expect(sansCommentaires).not.toContain("'supervisor'");
    expect(sansCommentaires).not.toContain("'logistician'");
    expect(sansCommentaires).not.toMatch(/\brole\s*===/);
  });
});

describe('F22–F23 · la prise de vue mobile', () => {
  it('F22 · propose l’appareil photo arrière', () => {
    // Le formulaire n'apparaît qu'une fois `can_add` reçu du serveur ; un
    // rendu statique n'exécute aucun effet et n'a donc pas encore de réponse.
    // C'est le parcours de bout en bout qui vérifie l'affichage réel ; ici on
    // épingle l'attribut, qui est ce qui ouvre l'appareil photo arrière.
    expect(SOURCE).toContain('capture="environment"');
    expect(SOURCE).toContain(
      "const TYPES = 'image/jpeg,image/png,image/webp,image/heic,image/heif'");
    expect(SOURCE).toContain('accept={TYPES}');
  });

  it('F23 · propose aussi la galerie, par une entrée sans `capture`', () => {
    // Sur iOS, `capture` interdit la galerie : un opérateur qui a photographié
    // le colis avant d'ouvrir le dossier ne pourrait plus rien envoyer.
    expect(SOURCE).toContain('data-testid="photo-galerie"');
    const galerie = SOURCE.slice(SOURCE.indexOf('id="photo-galerie"'));
    const finDuChamp = galerie.indexOf('/>');
    expect(galerie.slice(0, finDuChamp)).not.toContain('capture');
  });
});

describe('F24–F25 · l’aperçu local', () => {
  it('F24 · l’aperçu se construit depuis le fichier choisi', () => {
    expect(SOURCE).toContain('URL.createObjectURL(choisi)');
    expect(SOURCE).toContain('data-testid="apercu-photo"');
  });

  it('F25 · chaque adresse d’objet est révoquée', () => {
    expect(SOURCE).toContain('URL.revokeObjectURL');
    // Quatre sorties possibles, une seule fonction de libération : le
    // changement de fichier, l'annulation, la réussite et le démontage.
    expect(SOURCE).toContain('const libererApercu = useCallback');
    expect(SOURCE).toContain('useEffect(() => libererApercu');
    // `annuler()` libère, et c'est lui qu'appelle la réussite de l'envoi.
    const annuler = SOURCE.slice(SOURCE.indexOf('function annuler()'));
    expect(annuler.slice(0, annuler.indexOf('}'))).toContain('libererApercu()');
  });
});

describe('F30 · le serveur décide, l’écran obéit', () => {
  it('n’affiche le formulaire que sur `can_add`', () => {
    expect(SOURCE).toContain('donnees?.can_add ? (');
    // Aucune règle d'état recalculée ici : la liste des états autorisés
    // n'apparaît nulle part.
    for (const etat of ['goods_received', 'preparing', 'ready', 'departed']) {
      const sansCommentaires = SOURCE
        .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
      // `naturePardefaut` reçoit l'état mais ne l'interprète pas ici.
      expect(sansCommentaires.includes(`'${etat}'`), etat).toBe(false);
    }
  });

  it('ne propose le retrait que sur `can_delete`', () => {
    expect(SOURCE).toContain('photo.can_delete ? (');
    // Le nom de l'auteur ne sert jamais à décider : il n'est qu'affiché.
    expect(SOURCE).not.toContain('created_by ===');
  });
});

describe('F31–F32 · ce que ce bloc ne fait jamais', () => {
  it('F31 · n’inscrit rien dans la file hors connexion', () => {
    for (const interdit of ['offline', 'IndexedDB', 'inscrireMutation',
                            'file d’attente', 'queue']) {
      expect(SOURCE, interdit).not.toContain(interdit);
    }
  });

  it('F32 · ne mentionne ni tableur, ni projection, ni portail', () => {
    for (const interdit of ['sheet', 'outbox', 'portal', 'portail']) {
      expect(SOURCE.toLowerCase(), interdit).not.toContain(interdit);
    }
  });

  it('n’écrit aucune adresse de stockage ni identifiant technique', () => {
    for (const interdit of ['/web/content', 'attachment_id', 'res_model',
                            'res_id', 'store_fname', 'datas']) {
      expect(SOURCE, interdit).not.toContain(interdit);
    }
  });
});
