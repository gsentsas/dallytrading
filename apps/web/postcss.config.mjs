/**
 * Tailwind CSS v4 is configured from CSS (see src/app/globals.css), not from a
 * JavaScript config file. The PostCSS plugin is all that is needed here.
 *
 * @type {import('postcss-load-config').Config}
 */
const config = {
  plugins: {
    '@tailwindcss/postcss': {},
  },
};

export default config;
