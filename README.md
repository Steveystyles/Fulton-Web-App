# Fulton's Quiz

Mobile-first quiz app with a server-side daily Wordle draft.

## Run Locally

Start the Python API in one terminal:

```bash
npm run api
```

Start the Vite frontend in another terminal:

```bash
npm run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

## Production-Style Run

```bash
cp .env.example .env
npm run build
npm start
```

`npm start` runs the hardened production wrapper in `production_server.py`. It preserves the existing API while adding stronger password requirements, secure cookies, security headers, restricted CORS preflight handling, and basic login throttling.

## Homeserver Deployment

The production container is built with `Dockerfile` and served through the Traefik-facing compose file at `deploy/compose.yaml`. Runtime data is mounted at `/srv/storage/appdata/fultons-quiz`.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full server clone, environment, build, and update process.

## Security Notes

Production defaults are intentionally stricter than local development:

- Demo users are not seeded unless `FULTONS_SEED_DEMO_USERS=1` is set.
- Cookies are marked `Secure` by default when using the production wrapper.
- New and reset passwords must be at least 12 characters by default.
- Failed login attempts are throttled per username/client combination.
- The Docker Compose service runs with a read-only container filesystem, dropped Linux capabilities, and `no-new-privileges`.

## Storage

- User accounts, sessions, daily Wordle games, guesses, and results are stored in `data/fultons.db` locally or `/app/data/fultons.db` inside the container.
- Daily quiz JSON is stored in `data/quizzes` locally or `/app/data/quizzes` inside the container. The backend can generate quizzes with `FULTONS_QUIZ_OPENAI_API_KEY`; without that key it uses a curated rotating question bank rather than placeholder sample questions.
- The local used-word tracker is stored beside `wordle_game.py` as `used_words.txt`.

## Checks

```bash
npm run build
npm run test:server
```
