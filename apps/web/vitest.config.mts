import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

/**
 * Vitest configuration.
 *
 * Node environment : les tests React rendent le HTML initial avec
 * `react-dom/server` et testent des reducers purs, sans navigateur ni jsdom.
 */
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // Fail on an unhandled rejection instead of passing with a warning.
    dangerouslyIgnoreUnhandledErrors: false,
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
});
