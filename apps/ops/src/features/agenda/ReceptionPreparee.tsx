'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { FormulaireColis } from '@/features/reception/FormulaireColis';
import {
  preparedReceptionSchema, RECEPTION_AGENDA_KEY, type PreparedReception,
} from '@/features/agenda/reception-context';
import type { Consolidation } from '@/lib/ops/consolidations';
import type { FamilleTarifaire } from '@/lib/ops/intakes';

export function ReceptionPreparee({ consolidations, families }: {
  consolidations: Consolidation[];
  families: FamilleTarifaire[];
}) {
  const router = useRouter();
  const [context, setContext] = useState<PreparedReception | null>(null);
  const [selected, setSelected] = useState('');
  useEffect(() => {
    const task = window.setTimeout(() => {
      const raw = sessionStorage.getItem(RECEPTION_AGENDA_KEY);
      let parsed: unknown = null;
      try { parsed = raw ? JSON.parse(raw) : null; } catch { parsed = null; }
      const valid = preparedReceptionSchema.safeParse(parsed);
      if (!valid.success) { router.replace('/agenda'); return; }
      setContext(valid.data);
      setSelected(valid.data.consolidation_reference ?? '');
    }, 0);
    return () => window.clearTimeout(task);
  }, [router]);
  if (!context) return <p className="attenue">Préparation…</p>;
  const open = consolidations.some((item) => item.reference === selected);
  const reference = open ? selected : '';
  return <><h1>DOSSIER EN COURS</h1><section className="carte"><p className="attenue">Client</p><strong data-testid="client-selectionne">{context.customer_name}</strong><p className="attenue">Départ</p>{reference ? <p className="reference" data-testid="consolidation-selectionnee">{reference}</p> : <label>Choisir le départ<select aria-label="Choisir le départ" value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Sélectionner</option>{consolidations.map((item) => <option key={item.reference} value={item.reference}>{item.reference}</option>)}</select></label>}</section>{reference ? <FormulaireColis consolidation={reference} customer={context.customer_reference} familles={families} /> : null}</>;
}
