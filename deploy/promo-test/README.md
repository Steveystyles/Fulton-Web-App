# Promo Test Deployment

This deployment exposes the map-game promo and a restricted guest map session
without showing the login page. It runs an isolated beta API and database and
does not replace or proxy into the production Fulton Quiz container. The proxy
permits only the session check and daily-map endpoints; all other API routes
are unavailable.

Set `FULTONS_PROMO_DIST_DIR` to an absolute directory containing the built Vite
`dist` output. Set `FULTONS_PROMO_GUEST_SESSION` to a valid session belonging
to a dedicated non-admin review user in the test database. Set the beta image
revision and isolated data directory, then start it from this directory:

```bash
FULTONS_PROMO_DIST_DIR=/home/ste/fultons-promo-test/releases/<commit> \
FULTONS_PROMO_GUEST_SESSION=<server-held-session-token> \
FULTONS_PROMO_BUILD_COMMIT=<commit> \
FULTONS_PROMO_DATA_DIR=/home/ste/fultons-promo-test/data \
  docker compose up -d
```

The session token is injected upstream by Nginx and is never returned to the
browser. Review attempts share the dedicated user's daily map result in the
test database.

The Traefik router accepts:

- `test.fultons-quiz.com`
- `test.fultons-quiz.co.uk`
- `FULTONS_PROMO_FALLBACK_HOST`, which defaults to
  `fultons-promo.81-102-195-20.sslip.io`

The first two names require public DNS records pointing to the home server.
The fallback hostname resolves automatically and is intended only for
short-lived external review.
