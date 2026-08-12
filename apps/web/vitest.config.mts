import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

/**
 * Vitest configuration.
 *
 * Node environment: what is tested here is server-side logic — validation, the
 * gateway, rate limiting. Component tests would need jsdom and come with the UI
 * work in phase 5.
 */
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    // Fail on an unhandled rejection instead of passing with a warning.
    dangerouslyIgnoreUnhandledErrors: false,
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
});
