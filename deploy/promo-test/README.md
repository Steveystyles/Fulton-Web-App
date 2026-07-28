# Promo Test Deployment

This static deployment exposes the map-game promo without authentication and
does not replace the production Fulton Quiz container.

Set `FULTONS_PROMO_DIST_DIR` to an absolute directory containing the built
Vite `dist` output, then start it from this directory:

```bash
FULTONS_PROMO_DIST_DIR=/home/ste/fultons-promo-test/releases/<commit> \
  docker compose up -d
```

The Traefik router accepts:

- `test.fultons-quiz.com`
- `test.fultons-quiz.co.uk`
- `FULTONS_PROMO_FALLBACK_HOST`, which defaults to
  `fultons-promo.81-102-195-20.sslip.io`

The first two names require public DNS records pointing to the home server.
The fallback hostname resolves automatically and is intended only for
short-lived external review.
