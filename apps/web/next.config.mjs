/**
 * Next.js configuration.
 *
 * The app runs behind the Plesk nginx reverse proxy on 127.0.0.1:3010. nginx
 * terminates TLS, so Next must never assume it owns the public origin.
 *
 * @type {import('next').NextConfig}
 */
const nextConfig = {
  reactStrictMode: true,

  // The Docker/systemd deployment serves a self-contained build, so the runtime
  // does not need the full node_modules tree on the server.
  output: 'standalone',

  // Never leak framework internals in response headers.
  poweredByHeader: false,

  // Trailing slashes would create duplicate URLs for the same page and split
  // SEO signal between them.
  trailingSlash: false,

  images: {
    // AVIF first, WebP as fallback: smaller payloads matter on the mobile
    // connections this audience uses.
    formats: ['image/avif', 'image/webp'],
  },

  // Security headers.
  //
  // HSTS is deliberately absent: it is set once at the proxy, after the HTTPS
  // setup has been validated. Emitting it from two places makes it impossible to
  // reason about which value browsers actually received.
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          {
            key: 'Permissions-Policy',
            value: 'geolocation=(), microphone=(), camera=()',
          },
        ],
      },
      {
        // API routes are per-request and must never be cached by an
        // intermediary — they can carry customer data.
        source: '/api/:path*',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        // La page de suivi porte un secret dans sa query string.
        //
        // `strict-origin-when-cross-origin` transmet l'URL COMPLÈTE pour une
        // navigation de même origine. Un visiteur passant de
        // /tracking?ref=…&t=<token> à /contact envoyait donc le token dans
        // l'en-tête Referer, que nginx journalise sur la ligne /contact.
        // Mesuré le 13/08/2026 : le token apparaissait bien dans le journal,
        // malgré `access_log off` sur /tracking — la fuite se produit sur la
        // page de DESTINATION, pas sur la page d'origine.
        //
        // `no-referrer` supprime l'en-tête entièrement. La page de suivi n'a
        // aucun besoin d'attribution, et les liens de suivi déjà distribués
        // continuent de fonctionner : rien ne change côté URL.
        //
        // Cette entrée vient APRÈS la règle générale : Next applique la
        // dernière valeur pour une clé donnée, donc elle l'emporte sur
        // /tracking sans toucher au reste du site.
        source: '/tracking',
        headers: [
          { key: 'Referrer-Policy', value: 'no-referrer' },
          { key: 'Cache-Control', value: 'no-store' },
        ],
      },
    ];
  },
};

export default nextConfig;
