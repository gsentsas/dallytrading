import coreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

/**
 * ESLint flat config.
 *
 * eslint-config-next 16 ships native flat configs, so they are spread directly.
 * The `FlatCompat` bridge is not used: it is for eslintrc-format configs, and
 * feeding it an already-flat config crashes the validator.
 */
const config = [
  {
    ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts', 'coverage/**'],
  },

  ...coreWebVitals,
  ...nextTypescript,

  {
    rules: {
      // Underscore-prefixed arguments are intentional: an interface method keeps
      // its full signature even when an implementation ignores an argument (see
      // the gateway adapters).
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      // `any` erases exactly the guarantees this layer exists to provide.
      '@typescript-eslint/no-explicit-any': 'error',
      // Logging goes through lib/logger so redaction and structure are not
      // optional. A stray console.log can print a secret.
      'no-console': 'error',
      eqeqeq: ['error', 'always', { null: 'ignore' }],
    },
  },

  {
    // The logger is the one place allowed to write to the console.
    files: ['src/lib/logger.ts'],
    rules: { 'no-console': 'off' },
  },
];

export default config;
