/**
 * « À traiter », vu du comptoir.
 *
 * Ce que ces tests protègent : l'écran **restitue** et ne déduit rien. Il
 * n'invente ni gravité, ni message, ni lien. En particulier, il ne propose
 * d'ouvrir un dossier que si le serveur en a nommé un — une projection en
 * peine n'a pas de fiche à ouvrir, et y renvoyer l'opérateur l'enverrait
 * chercher un incident de transport dans un dossier.
 */
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ListeAnomalies } from '@/features/traitement/ListeAnomalies';
import type { Anomalie, ListeAnomalies as Liste } from '@/lib/ops/supervision';

const COLIS: Anomalie = {
  type: 'UNBILLED_PACKAGE',
  reference: 'AIR-DSS-CDG-2099-001-A901',
  title: 'Article non facturé',
  operator_message: '1 article de ce dossier n’est couvert par aucune facture.',
  severity: 'medium',
  action: 'open_intake',
  intake_reference: 'AIR-DSS-CDG-2099-001-A901',
};

const PROJECTION: Anomalie = {
  type: 'SHEET_PROJECTION_FAILED',
  reference: 'AIR-DSS-CDG-2099-001-A807',
  title: 'Synchronisation du tableur',
  operator_message: 'Le tableur n’a pas reçu ce dossier.',
  severity: 'high',
  action: null,
  intake_reference: null,
};

const rendu = (liste: Partial<Liste>) => renderToStaticMarkup(
  <ListeAnomalies
    liste={{ anomalies: [], total: 0, truncated: false, ...liste }}
  />,
);

describe('la liste des anomalies', () => {
  it('dit clairement quand il n’y a rien à traiter', () => {
    expect(rendu({})).toContain('Rien à traiter');
  });

  it('affiche le message rédigé par le serveur, pas un message inventé', () => {
    const html = rendu({ anomalies: [COLIS], total: 1 });
    expect(html).toContain('n’est couvert par aucune facture');
    expect(html).toContain('Article non facturé');
  });

  it('propose d’ouvrir le dossier quand le serveur en nomme un', () => {
    const html = rendu({ anomalies: [COLIS], total: 1 });
    expect(html).toContain('OUVRIR LE DOSSIER');
    expect(html).toContain('/reception/dossier/AIR-DSS-CDG-2099-001-A901');
  });

  it(
    'ne propose rien à ouvrir pour un incident de transport — il n’y a pas '
    + 'de fiche où le voir',
    () => {
      const html = rendu({ anomalies: [PROJECTION], total: 1 });
      expect(html).toContain('Synchronisation du tableur');
      expect(html).not.toContain('OUVRIR LE DOSSIER');
    },
  );

  it('traduit la gravité en mots, sans la recalculer', () => {
    expect(rendu({ anomalies: [PROJECTION], total: 1 })).toContain('À traiter');
    expect(rendu({ anomalies: [COLIS], total: 1 })).toContain('À surveiller');
  });

  it('annonce la troncature plutôt que de laisser croire à une liste complète', () => {
    const html = rendu({ anomalies: [COLIS], total: 120, truncated: true });
    expect(html).toContain('120 points à traiter');
    expect(html).toContain('Seuls les 1 premiers');
  });

  it('ne montre jamais un identifiant Odoo ni un message de transport', () => {
    const html = rendu({ anomalies: [COLIS, PROJECTION], total: 2 });
    for (const interdit of [
      'last_error', 'traceback', 'shipment_id', 'outbox_id', 'partner_id',
      'invoice_id', 'resource_id',
    ]) {
      expect(html).not.toContain(interdit);
    }
  });

  it('distingue les deux anomalies par leur type, pas par leur rang', () => {
    const html = rendu({ anomalies: [COLIS, PROJECTION], total: 2 });
    expect(html).toContain('data-type="UNBILLED_PACKAGE"');
    expect(html).toContain('data-type="SHEET_PROJECTION_FAILED"');
  });
});
