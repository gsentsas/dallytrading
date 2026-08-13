# Brand assets

## What belongs here

| File | Purpose | Status |
|---|---|---|
| `dallytrading-emblem.png` | Circular emblem: vessel, aircraft, truck, leaf swoosh | ⬜ **à fournir** |
| `dallytrading-logo.png` | Full logo, emblem + wordmark, for e-mails and documents | ⬜ **à fournir** |
| `og-default.png` | Social preview image, 1200 × 630 px | ⬜ **à fournir** |

## Why the emblem is not in the code

The wordmark (DALLY navy + TRADING green + signature line) is rendered in code
from the design tokens, so it can never drift from the rest of the site.

The **emblem is not recreated in code, deliberately**. An approximation of a
company's own logo is worse than no logo: it looks nearly right, which is exactly
how a wrong version ends up on a business card or a printed invoice. It must be the
official file.

## Enabling the emblem

Until the file is supplied, the site renders the wordmark alone — never a broken
image. Once `dallytrading-emblem.png` is in this directory, set:

```env
NEXT_PUBLIC_BRAND_EMBLEM=true
```

and the header, footer and hero pick it up automatically.

## Format guidance

- **Emblem** — square, transparent background. SVG is preferable; if PNG, supply
  at least 512 × 512 px so it stays sharp on high-density screens.
- **Social preview** — exactly 1200 × 630 px. Any other ratio is cropped
  unpredictably by LinkedIn, Facebook and WhatsApp.
- Keep the navy `#16365B` and the greens `#4C9A2A` / `#6DBE45` exactly as in the
  official artwork: they are the source of the whole palette in
  `src/app/globals.css`.
