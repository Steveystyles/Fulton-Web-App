# Production Deployment

This app is designed to run as a Docker container behind Traefik on an Ubuntu server. The home-server deploy script is `deploy/homeserver-update.sh`; it backs up app data, rebuilds the container, starts it, and checks `/api/health`.

## 1. Clone The Repository

```bash
sudo mkdir -p /opt/src
sudo chown -R "$USER:$USER" /opt/src
git clone https://github.com/Steveystyles/Fulton-Web-App.git /opt/src/fulton-web-app
cd /opt/src/fulton-web-app
```

## 2. Create Runtime Storage

```bash
sudo mkdir -p /srv/storage/appdata/fultons-quiz
sudo chown -R "$USER:$USER" /srv/storage/appdata/fultons-quiz
cp .env.example /srv/storage/appdata/fultons-quiz/app.env
chmod 600 /srv/storage/appdata/fultons-quiz/app.env
nano /srv/storage/appdata/fultons-quiz/app.env
```

Recommended production settings:

```env
FULTONS_COOKIE_SECURE=1
FULTONS_SEED_DEMO_USERS=0
FULTONS_ALLOWED_ORIGINS=https://fultons-quiz.co.uk,https://www.fultons-quiz.co.uk
FULTONS_MIN_PASSWORD_LENGTH=12
FULTONS_LOGIN_MAX_ATTEMPTS=5
FULTONS_LOGIN_WINDOW_SECONDS=300
FULTONS_LOGIN_BACKOFF_SECONDS=60
FULTONS_NEWS_MONITOR_KEY=<generate-a-long-random-value>
```

Generate the news monitor key with:

```bash
openssl rand -base64 32
```

## 3. First Admin Account

Demo accounts are disabled by default. For an existing database, keep your existing admin user.

For a brand-new empty database, bootstrap one admin by setting both variables below for the first start only:

```env
FULTONS_BOOTSTRAP_ADMIN_USERNAME=<admin-username>
FULTONS_BOOTSTRAP_ADMIN_PASSWORD=<long-random-password>
```

After the app starts and the admin account exists, remove those two bootstrap variables from `app.env` and restart. Do not expose the public site with bootstrap credentials left in the environment.

For throwaway local development only, `FULTONS_SEED_DEMO_USERS=1` creates demo users with non-production sample passwords.

## 4. Build And Start

```bash
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml build --pull
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml up -d
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml ps
```

## 5. Update Deployment

Preferred home-server update:

```bash
bash deploy/homeserver-update.sh <commit-sha>
```

Manual update:

```bash
cd /opt/src/fulton-web-app
git pull --ff-only
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml build --pull
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml up -d
```

## 6. Health And Logs

```bash
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml logs --tail=100 quiz-app
```

The container healthcheck calls `/api/health` internally.

## Security Notes

The production image runs as a non-root user. Compose enables a read-only root filesystem, drops Linux capabilities, sets `no-new-privileges`, and keeps only `/app/data` writable for SQLite and runtime data. Session cookies include `Secure` when `FULTONS_COOKIE_SECURE=1`, which assumes users access the app through HTTPS.
