import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  LIBELLES_NATURE,
  NATURES,
  cheminPhoto,
  dateLisible,
  interpreterEnvoi,
  issueHorsLignePhoto,
  issueReseauPhoto,
  libelleNature,
  creerSuiviDeGeste,
  naturePardefaut,
} from '@/features/reception/photos-vocabulaire';

const SOURCE = readFileSync(
  fileURLToPath(new URL('./PhotosDossier.tsx', import.meta.url)), 'utf8');

describe('F26 · la nature de la photo', () => {
  it('couvre exactement les cinq natures du serveur', () => {
    expect([...NATURES]).toEqual([
      'reception', 'package', 'damage', 'preparation', 'other']);
    expect(Object.keys(LIBELLES_NATURE).sort()).toEqual([...NATURES].sort());
  });

  it('ne montre jamais le code technique à l’opérateur', () => {
    for (const nature of NATURES) {
      expect(libelleNature(nature)).not.toContain(nature);
      expect(libelleNature(nature).length).toBeGreaterThan(4);
    }
  });

  it('présélectionne le geste le plus probable, sans jamais l’imposer', () => {
    expect(naturePardefaut('goods_received')).toBe('reception');
    expect(naturePardefaut('preparing')).toBe('preparation');
    expect(naturePardefaut('ready')).toBe('preparation');
    // Un état inattendu ne doit pas inventer une nature : « Autre » existe
    // pour cela.
    expect(naturePardefaut('departed')).toBe('other');
    // Et l'écran laisse toujours choisir : la liste entière est proposée.
    expect(SOURCE).toContain('NATURES.map');
  });

  it('une nature inconnue au retour ne casse pas l’affichage', () => {
    expect(libelleNature('selfie')).toBe('Autre');
  });
});

describe('F27–F29 · l’identifiant du geste', () => {
  /** Un compteur, pour lire les identifiants sans deviner. */
  function suivi() {
    let rang = 0;
    return creerSuiviDeGeste(() => `geste-${(rang += 1)}`);
  }

  it('F27 · une reprise réseau, sans nouvelle sélection, garde le même geste', () => {
    const geste = suivi();
    expect(geste.identifiant()).toBe('geste-1');
    expect(geste.identifiant()).toBe('geste-1');
    expect(geste.identifiant()).toBe('geste-1');
  });

  it('F28 · deux fichiers de même nom et même taille sont deux gestes', () => {
    // La régression exacte. L'ancienne identité comparait nom, taille et
    // nature : deux clichés pris à la suite par le même appareil peuvent
    // partager les trois, et le second aurait alors rejoué le premier.
    const premier = new File([new Uint8Array([1, 2, 3, 4])], 'IMG_0042.jpg',
                             { type: 'image/jpeg' });
    const second = new File([new Uint8Array([9, 9, 9, 9])], 'IMG_0042.jpg',
                            { type: 'image/jpeg' });
    expect(second.name).toBe(premier.name);
    expect(second.size).toBe(premier.size);

    const geste = suivi();
    // Première sélection, puis envoi.
    geste.terminer();
    const pourLePremier = geste.identifiant();
    // Seconde sélection : le geste précédent est clos, quoi qu'annonce le
    // fichier.
    geste.terminer();
    const pourLeSecond = geste.identifiant();

    expect(pourLeSecond).not.toBe(pourLePremier);
  });

  it('F29 · un changement de nature termine aussi le geste', () => {
    const geste = suivi();
    const avant = geste.identifiant();
    geste.terminer();
    expect(geste.identifiant()).not.toBe(avant);
  });

  it('le premier envoi tire son identifiant au moment de partir', () => {
    const geste = suivi();
    expect(geste.enCours()).toBeNull();
    geste.identifiant();
    expect(geste.enCours()).toBe('geste-1');
    geste.terminer();
    expect(geste.enCours()).toBeNull();
  });

  it('le composant clôt le geste à la sélection, à la nature et à l’annulation', () => {
    // Trois points de clôture, et un seul point de tirage : c'est ce qui rend
    // la reprise réseau idempotente sans jamais confondre deux clichés.
    const choisir = SOURCE.slice(SOURCE.indexOf('function choisir('),
                                 SOURCE.indexOf('function changerNature('));
    expect(choisir).toContain('geste.current.terminer()');
    const nature = SOURCE.slice(SOURCE.indexOf('function changerNature('),
                                SOURCE.indexOf('function annuler('));
    expect(nature).toContain('geste.current.terminer()');
    const annuler = SOURCE.slice(SOURCE.indexOf('function annuler('),
                                 SOURCE.indexOf('async function envoyer('));
    expect(annuler).toContain('geste.current.terminer()');
    // Et l'envoi ne fabrique jamais d'identifiant lui-même.
    const envoyer = SOURCE.slice(SOURCE.indexOf('async function envoyer('),
                                 SOURCE.indexOf('async function retirer('));
    expect(envoyer).toContain('geste.current.identifiant()');
    expect(envoyer).not.toContain('crypto.randomUUID()');
  });
});

describe('l’adresse de lecture', () => {
  it('passe toujours par la route authentifiée, jamais par le stockage', () => {
    const chemin = cheminPhoto('AIR-DSS-CDG-2026-902-A001', 'abc-123');
    expect(chemin).toBe('/api/intakes/AIR-DSS-CDG-2026-902-A001/photos/abc-123');
    expect(chemin).not.toContain('/web/content');
    expect(chemin).not.toContain('attachment');
  });

  it('échappe ce qui vient du serveur', () => {
    expect(cheminPhoto('A/B', 'x y')).toBe('/api/intakes/A%2FB/photos/x%20y');
  });
});

describe('ce que l’opérateur lit', () => {
  it('reprend le message du serveur, qui seul sait pourquoi il refuse', () => {
    expect(interpreterEnvoi(false, {
      success: false, error: 'Ce dossier a atteint son nombre de photos.',
    })).toEqual({
      issue: 'refus', message: 'Ce dossier a atteint son nombre de photos.',
    });
  });

  it('garantit un message même quand le serveur n’en donne aucun', () => {
    const issue = interpreterEnvoi(false, null);
    expect(issue.issue).toBe('refus');
    expect(issue).toHaveProperty('message');
  });

  it('distingue le refus métier de la coupure réseau', () => {
    expect(issueReseauPhoto().message).toContain('réessayer');
    expect(issueHorsLignePhoto().message).toContain('Connexion requise');
  });

  it('ne promet ni envoi client, ni notification', () => {
    const textes = [
      ...Object.values(LIBELLES_NATURE),
      issueReseauPhoto().message,
      issueHorsLignePhoto().message,
      interpreterEnvoi(false, null).issue === 'refus'
        ? (interpreterEnvoi(false, null) as { message: string }).message : '',
      SOURCE,
    ].join(' ').toLowerCase();
    for (const interdit of ['sms', 'e-mail', 'email', 'notification',
                            'le client verra', 'visible par le client']) {
      expect(textes, interdit).not.toContain(interdit);
    }
  });
});

describe('la date d’une preuve', () => {
  it('se lit sans fuseau ni secondes', () => {
    expect(dateLisible('2026-08-31T09:05:00Z')).toMatch(
      /^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/);
  });

  it('ne rend rien plutôt qu’une date fausse', () => {
    expect(dateLisible('pas-une-date')).toBe('');
  });
});
