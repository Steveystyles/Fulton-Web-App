# Production deployment

This app is designed to run as a Docker container behind Traefik on an Ubuntu server.

## 1. Clone the repository

```bash
sudo mkdir -p /opt/src
sudo chown -R "$USER:$USER" /opt/src
git clone https://github.com/Steveystyles/Fulton-Web-App.git /opt/src/fulton-web-app
cd /opt/src/fulton-web-app
```

## 2. Create runtime storage

```bash
sudo mkdir -p /srv/storage/appdata/fultons-quiz
sudo chown -R "$USER:$USER" /srv/storage/appdata/fultons-quiz
cp .env.example /srv/storage/appdata/fultons-quiz/app.env
nano /srv/storage/appdata/fultons-quiz/app.env
```

Set at least:

```env
FULTONS_COOKIE_SECURE=1
FULTONS_SEED_DEMO_USERS=0
FULTONS_ALLOWED_ORIGINS=https://fultons-quiz.co.uk,https://www.fultons-quiz.co.uk
FULTONS_NEWS_MONITOR_KEY=<generate-a-long-random-value>
```

Generate the news monitor key with:

```bash
openssl rand -base64 32
```

## 3. Build and start

```bash
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml build --pull
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml up -d
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml ps
```

## 4. First admin account

For an existing database, keep your existing admin user.

For a brand-new production database, do not leave demo accounts enabled. The temporary first-run option is:

1. Set `FULTONS_SEED_DEMO_USERS=1` in `app.env`.
2. Start the app once.
3. Sign in as `admin` using the temporary demo credential documented in the project README.
4. Immediately change the admin password in the Account screen.
5. Create your real user accounts in Admin.
6. Set `FULTONS_SEED_DEMO_USERS=0` again.
7. Restart the container.

This is a temporary bootstrap flow only. Remove or disable demo credentials before exposing the app publicly.

## 5. Update deployment

```bash
cd /opt/src/fulton-web-app
git pull --ff-only
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml build --pull
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml up -d
```

## 6. Health check

```bash
docker compose --env-file /srv/storage/appdata/fultons-quiz/app.env -f deploy/compose.yaml logs --tail=100 quiz-app
```

The container healthcheck calls `/api/health` internally.
