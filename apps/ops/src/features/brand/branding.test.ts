import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

function source(path: string): string {
  return readFileSync(
    fileURLToPath(new URL(`../../../${path}`, import.meta.url)),
    'utf8',
  );
}

function exists(path: string): boolean {
  return existsSync(fileURLToPath(new URL(`../../../${path}`, import.meta.url)));
}

describe('branding DallyTrading dans Dally Ops', () => {
  it('affiche le branding DallyTrading sur toutes les pages via le layout racine', () => {
    const layout = source('src/app/layout.tsx');
    expect(layout).toContain('DallyTradingBrand');
    expect(layout).toContain('ops-brand-header');
  });

  it('utilise le pictogramme officiel dans l’interface et le manifeste PWA', () => {
    const brand = source('src/features/brand/DallyTradingBrand.tsx');
    const manifest = source('src/app/manifest.ts');
    expect(brand).toContain('/icones/dallytrading-ops-192.png');
    expect(manifest).toContain("src: '/icones/dallytrading-ops-192.png'");
    expect(manifest).toContain("src: '/icones/dallytrading-ops-512.jpg'");
    expect(manifest).toContain("src: '/icones/dallytrading-ops-maskable-512.jpg'");
  });

  it('embarque les trois fichiers d’icône officiels attendus', () => {
    expect(exists('public/icones/dallytrading-ops-192.png')).toBe(true);
    expect(exists('public/icones/dallytrading-ops-512.jpg')).toBe(true);
    expect(exists('public/icones/dallytrading-ops-maskable-512.jpg')).toBe(true);
  });

  it('ne référence plus les anciennes icônes ni les monogrammes provisoires', () => {
    const manifest = source('src/app/manifest.ts');
    const brand = source('src/features/brand/DallyTradingBrand.tsx');
    for (const legacy of [
      '/icones/ops-192.png',
      '/icones/ops-512.png',
      '/icones/ops-maskable-512.png',
      '/icones/dallytrading-ops.svg',
      '/icones/dallytrading-ops-maskable.svg',
    ]) {
      expect(manifest).not.toContain(legacy);
      expect(brand).not.toContain(legacy);
    }
  });

  it('conserve la couleur de thème DallyTrading', () => {
    const manifest = source('src/app/manifest.ts');
    const layout = source('src/app/layout.tsx');
    expect(manifest).toContain("theme_color: '#16365B'");
    expect(layout).toContain("themeColor: '#16365B'");
  });
});
