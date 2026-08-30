/**
 * Les commandes du reçu.
 *
 * Le comportement — partage, repli, impression — se vérifie dans le parcours
 * de bout en bout, avec un vrai navigateur. Ici on fige ce qui doit être
 * offert, et ce qui ne doit jamais l'être : une adresse du PDF laissée dans la
 * page serait devinable et sortirait le document de la session.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

const { RecuActions } = await import('@/features/reception/RecuActions');

const AXXX = 'AIR-DSS-CDG-TEST-001-A001';
const html = renderToStaticMarkup(<RecuActions reference={AXXX} />);

const source = readFileSync(
  join(fileURLToPath(new URL('.', import.meta.url)), 'RecuActions.tsx'), 'utf8');

describe('les commandes offertes au comptoir', () => {
  it('offre le téléchargement, le partage et l’impression', () => {
    expect(html).toContain('TÉLÉCHARGER PDF');
    expect(html).toContain('PARTAGER');
    expect(html).toContain('IMPRIMER');
  });

  it('n’écrit aucune adresse du PDF dans la page', () => {
    // Un lien vers le PDF serait copiable, partageable et devinable ; les
    // octets passent par une requête portée par la session.
    expect(html).not.toContain('receipt/pdf');
    expect(html).not.toContain('href');
  });

  it('retombe sur le téléchargement dès que le partage n’est pas possible', () => {
    // Trois conditions, trois replis — et l'annulation par l'utilisateur en
    // est un quatrième.
    expect(source).toContain("typeof navigator.share !== 'function'");
    expect(source).toContain("typeof partageur.canShare !== 'function'");
    expect(source).toContain('!partageur.canShare({ files: [fichier] })');
    expect(source.match(/enregistrer\(contenu\)/g)?.length).toBe(2);
  });

  it('révoque toujours l’objet URL créé', () => {
    // Sans cela le reçu resterait en mémoire de l'onglet pour toute la
    // session, sur un téléphone que plusieurs personnes utilisent.
    expect(source).toContain('finally');
    expect(source).toContain('URL.revokeObjectURL(adresse)');
  });
});
