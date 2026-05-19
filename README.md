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
npm run build
npm start
```

The Python server serves the built `dist` app and the API.

## Homeserver Deployment

The production container is built with `Dockerfile` and served through the
Traefik-facing compose file at `deploy/compose.yaml`. Runtime data is mounted at
`/srv/storage/appdata/fultons-quiz`.

## Test Accounts

- `admin` / `admin`
- `user1` / `user1`
- `user2` / `user2`

## Storage

- User accounts, sessions, daily Wordle games, guesses, and results are stored in `data/fultons.db`.
- The local used-word tracker is stored beside `wordle_game.py` as `used_words.txt`.
