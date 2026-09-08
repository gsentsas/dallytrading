import Link from 'next/link';

import { EcranSync } from '@/features/offline/EcranSync';
import { EtatProjectionTableur } from '@/features/offline/EtatProjectionTableur';

export default function PageSynchronisation() {
  return (
    <main className="ops-operation-page ops-sync-page">
      <Link className="retour ops-back-link" href="/">← Accueil</Link>
      <header className="ops-operation-heading">
        <span className="ops-operation-heading-icon tone-green" aria-hidden="true">↻</span>
        <div>
          <p className="ops-eyebrow">HORS LIGNE</p>
          <h1>SYNCHRONISATION</h1>
          <p>Suivre ce que l’appareil doit encore au CRM et la projection vers le tableur.</p>
        </div>
      </header>

      <section className="ops-sync-section">
        <div className="ops-section-heading"><h2>APPAREIL → CRM</h2><p>FILE LOCALE</p></div>
        <p className="attenue">
          Les opérations enregistrées sur cet appareil et non encore confirmées par le CRM.
        </p>
        <EcranSync />
      </section>

      <section className="ops-sync-section ops-sync-sheet">
        {/*
          * Pas de titre ici : `EtatProjectionTableur` porte le sien, avec sa
          * description. Le répéter au-dessus donnait deux fois « CRM →
          * TABLEUR » l'un sous l'autre dès que la projection était lisible —
          * et deux titres pour une seule section brouillent la navigation par
          * titres autant que la lecture.
          */}
        <EtatProjectionTableur />
      </section>
    </main>
  );
}
