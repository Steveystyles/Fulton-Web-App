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

Create the compose-side path overrides once so restarts and helper scripts always target the intended host paths:

```bash
mkdir -p ~/fulton-web-app-deploy
cat > ~/fulton-web-app-deploy/.env <<'EOF'
FULTONS_SRC_DIR=/opt/src/fulton-web-app
FULTONS_ENV_FILE=/srv/storage/appdata/fultons-quiz/app.env
FULTONS_HOST_DATA_DIR=/srv/storage/appdata/fultons-quiz
EOF
chmod 600 ~/fulton-web-app-deploy/.env
```

If your private env file and SQLite data live on different mounts, set `FULTONS_ENV_FILE` and `FULTONS_HOST_DATA_DIR` to those exact host paths instead of keeping both under `/srv/storage`.

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
FULTONS_NEWS_MONITOR_INTERVAL_SEC=600
FULTONS_WORD_DEFINITION_TIMEOUT_SEC=5
FULTONS_EXPECT_DATA_DIR=/app/data
FULTONS_REQUIRE_EXISTING_DB=1
FULTONS_MIN_DB_USERS=1
AI_PROVIDER=gemini
AI_GENERATOR_MODEL=gemini-3.5-flash
AI_CRITIC_MODEL=gemini-3.1-flash-lite
GEMINI_API_KEY=<private-gemini-api-key>
AI_FALLBACK_PROVIDER=openrouter
AI_FALLBACK_GENERATOR_MODEL=google/gemini-2.5-flash
AI_FALLBACK_CRITIC_MODEL=google/gemini-2.5-flash
AI_FALLBACK_API_KEY=<private-openrouter-api-key>
AI_FALLBACK2_PROVIDER=openrouter
AI_FALLBACK2_GENERATOR_MODEL=openrouter/free
AI_FALLBACK2_CRITIC_MODEL=openrouter/free
AI_TIMEOUT_SEC=90
AI_REQUEST_DELAY_SEC=12
AI_TRANSIENT_RETRIES=3
MAX_ATTEMPTS_PER_SLOT=15
QUESTION_HISTORY_DAYS=90
INTERNAL_QUIZ_TOKEN=<generate-a-long-random-value>
FULTONS_FACT_ROTATION_TTL_SEC=86400
FULTONS_FACTS_GEMINI_API_KEY=<optional-separate-key-or-leave-blank-to-reuse-GEMINI_API_KEY>
FULTONS_FACTS_AI_GENERATOR_MODEL=gemini-3.5-flash
FULTONS_FACTS_AI_CRITIC_MODEL=gemini-3.1-flash-lite
FULTONS_FACTS_AI_TIMEOUT_SEC=8
FULTONS_FACTS_AI_REQUEST_DELAY_SEC=0.5
FULTONS_FACTS_AI_TRANSIENT_RETRIES=0
FULTONS_FACTS_AI_GENERATOR_BUDGET_SEC=12
FULTONS_FACTS_AI_CRITIC_BUDGET_SEC=6
FULTONS_FACT_PREWARM_ENABLED=1
FULTONS_FACT_PREWARM_LEAD_SEC=7200
FULTONS_FACT_PREWARM_POLL_SEC=60
FULTONS_FACT_PREWARM_MAX_ATTEMPTS=2
FULTONS_FACT_PREWARM_TIMEOUT_SEC=12
FULTONS_FACT_PREWARM_TRANSIENT_RETRIES=1
FULTONS_FACT_PREWARM_GENERATOR_BUDGET_SEC=24
FULTONS_FACT_PREWARM_CRITIC_BUDGET_SEC=12
FULTONS_FACT_PREWARM_WEB_SEARCH_TIMEOUT_SEC=10
FULTONS_FACTS_FALLBACK_PROVIDER=openrouter
FULTONS_FACTS_FALLBACK_GENERATOR_MODEL=google/gemini-2.5-flash
FULTONS_FACTS_FALLBACK_CRITIC_MODEL=google/gemini-2.5-flash
FULTONS_FACTS_FALLBACK2_PROVIDER=openrouter
FULTONS_FACTS_FALLBACK2_GENERATOR_MODEL=openrouter/free
FULTONS_FACTS_FALLBACK2_CRITIC_MODEL=openrouter/free
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
cd ~/fulton-web-app-deploy
docker compose -f compose.yaml build --pull
docker compose -f compose.yaml up -d
docker compose -f compose.yaml ps
```

## 5. Update Deployment

Preferred home-server update:

```bash
bash deploy/homeserver-update.sh <commit-sha>
```

The update script writes the resolved source, env-file, and data paths into `~/fulton-web-app-deploy/.env`, builds `local/fulton-web-app:latest` directly from that resolved source tree, and refuses the rollout if the running container revision label does not match the requested commit.

Manual update:

```bash
cd /opt/src/fulton-web-app
git pull --ff-only
bash deploy/homeserver-update.sh "$(git rev-parse HEAD)"
```

## 6. Health And Logs

```bash
cd ~/fulton-web-app-deploy
docker compose -f compose.yaml logs --tail=100 quiz-app
docker exec fultons-quiz python -c "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health')), indent=2))"
```

The container healthcheck calls `/api/health` internally.

The app also runs storage checks at startup. In production, keep these enabled after the first real database exists:

```env
FULTONS_EXPECT_DATA_DIR=/app/data
FULTONS_REQUIRE_EXISTING_DB=1
FULTONS_MIN_DB_USERS=1
```

These checks catch the common failure modes: `/app/data` not mounted, SQLite not writable, corrupt DB, missing DB, and an accidentally empty user database. Set `FULTONS_MIN_DB_USERS=0` only for a brand-new first run before an admin exists.

The home-server restart and update scripts also run a host-side SQLite `PRAGMA quick_check` before recreating containers. If this fails, preserve the bad DB file and restore a known-good backup rather than letting the app create a new empty database.

If `/api/health` reports a storage error, do not delete the mounted data directory. Check the compose mount first:

```bash
docker inspect fultons-quiz --format '{{range .Mounts}}{{println .Source "->" .Destination .RW}}{{end}}'
ls -la /srv/storage/appdata/fultons-quiz
docker exec fultons-quiz python -c "import sqlite3; c=sqlite3.connect('/app/data/fultons.db'); print(c.execute('PRAGMA quick_check').fetchone()[0]); print(c.execute('SELECT COUNT(*) FROM users').fetchone()[0])"
```

The interesting-facts cards now use Gemini selection plus critique on top of public web evidence. Do not let this path inherit the quiz generator's long retry settings. On the free Gemini tier, keep the fact-specific timeout and retry settings short and set explicit generator/critic budgets so the page can fall back cleanly instead of stalling. If `FULTONS_FACTS_FALLBACK_*` or `FULTONS_FACTS_FALLBACK2_*` is left blank, the facts path reuses the main `AI_FALLBACK_*` and `AI_FALLBACK2_*` OpenRouter-compatible settings for provider and model selection, but its own timeout, retry, and budget values should still be set explicitly. Successful reviewed facts are reused for 24 hours per place, and failed review attempts are cached in SQLite so later selections can avoid the same generic or low-quality ideas.

## 7. Daily Quiz Generation

The rebuilt quiz backend uses a cloud AI provider for offline daily generation. The live quiz navigation remains hidden until generated questions have been reviewed and the player-facing component is reintroduced.

Configure Gemini in the private app env file:

```env
AI_PROVIDER=gemini
AI_GENERATOR_MODEL=gemini-3.5-flash
AI_CRITIC_MODEL=gemini-3.1-flash-lite
GEMINI_API_KEY=<private-gemini-api-key>
AI_FALLBACK_PROVIDER=openrouter
AI_FALLBACK_GENERATOR_MODEL=google/gemini-2.5-flash
AI_FALLBACK_CRITIC_MODEL=google/gemini-2.5-flash
AI_FALLBACK_API_KEY=<private-openrouter-api-key>
AI_FALLBACK2_PROVIDER=openrouter
AI_FALLBACK2_GENERATOR_MODEL=openrouter/free
AI_FALLBACK2_CRITIC_MODEL=openrouter/free
AI_TIMEOUT_SEC=90
AI_REQUEST_DELAY_SEC=12
AI_TRANSIENT_RETRIES=3
MAX_ATTEMPTS_PER_SLOT=15
QUESTION_HISTORY_DAYS=90
INTERNAL_QUIZ_TOKEN=<generate-with-openssl-rand-base64-32>
```

From a Windows workstation, the setup helper prompts for the Gemini key securely and stores it in the private server env file without printing it:

```powershell
.\deploy\set-gemini-key.ps1
```

The system generates one question at a time for six slots: easy, medium, and hard general knowledge plus easy, medium, and hard football. Each candidate passes local validation, recent-question repetition checks, and a separate AI critic before it is stored. A quiz is published only after all six slots are approved. Failed attempts and critic feedback are retained in SQLite for review.

Generation and critique use separate Gemini models so their free-tier request quotas are independent. Keep `gemini-3.5-flash` for writing questions and the stable `gemini-3.1-flash-lite` model for the narrower critic task. When Gemini hits quota or times out, the server now supports a two-stage OpenRouter-compatible chain through `AI_FALLBACK_*` and `AI_FALLBACK2_*`, for example `google/gemini-2.5-flash` first and `openrouter/free` second.

Generate a quiz through the protected internal endpoint:

```bash
curl -X POST http://127.0.0.1:3000/internal/generate-daily-quiz \
  -H "Authorization: Bearer ${INTERNAL_QUIZ_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-06-02","force":false}'
```

For a manual generation run from the application source directory:

```bash
python3 tools/generate_daily_quiz.py --date 2026-06-02
```

From a Windows workstation, use the SSH helper to generate tomorrow's quiz and print the review JSON without exposing the internal token:

```powershell
.\deploy\generate-daily-quiz.ps1
```

The Fulton server checks tomorrow's quiz at startup and then runs its internal scheduler at `00:05 Europe/London` each day. The scheduler generates the following day's quiz without requiring host cron packages. Configure it in the private env file:

```env
FULTONS_DAILY_QUIZ_SCHEDULER_ENABLED=1
FULTONS_DAILY_QUIZ_SCHEDULER_HOUR=0
FULTONS_DAILY_QUIZ_SCHEDULER_MINUTE=5
FULTONS_DAILY_QUIZ_TRANSIENT_RETRY_INTERVAL_SEC=3600
```

Provider rate-limit failures use `FULTONS_DAILY_QUIZ_TRANSIENT_RETRY_INTERVAL_SEC`
instead of the normal retry cadence so the app does not keep refreshing a rate
limit while waiting for the upstream provider to recover.

Do not expose the internal token in browser code or commit it to Git.

Run a one-time generation for a specific date without changing the schedule:

```bash
bash /home/ste/fulton-web-app/deploy/generate-daily-quiz.sh 2026-06-01
```

Authenticated admins can review generation state and failed attempts:

```http
GET /api/admin/daily-quiz-status?date=2026-06-02
GET /api/admin/question-attempts?date=2026-06-02
```

The public read endpoint only returns published content and omits prompts, critic scores, failed attempts, and internal notes:

```http
GET /api/daily-quiz?date=2026-06-02
```

To switch fully to an OpenAI-compatible provider such as Groq or OpenRouter later, set `AI_PROVIDER=groq`, `AI_PROVIDER=openrouter`, or `AI_PROVIDER=openai-compatible`, then provide `AI_BASE_URL` and `AI_API_KEY`. Gemini remains the default because its API supports structured JSON output directly, while `AI_FALLBACK_*` lets you keep Gemini primary and OpenRouter-compatible routing as a backup.

## 8. Unexpected Shutdown Checks
If the server powers off or must be unplugged before it will restart, inspect the host before running heavy workloads:

```bash
last -x | head -20
journalctl -k -b --no-pager | egrep -i 'thermal|overheat|critical|power|battery|acpi|mce|hardware error|oom|killed process|ext4|i/o error' | tail -120
cat /sys/class/power_supply/AC*/online 2>/dev/null || true
for b in /sys/class/power_supply/BAT*; do [ -d "$b" ] && echo "$b" && cat "$b/status" "$b/capacity" "$b/energy_now" "$b/energy_full" "$b/energy_full_design" 2>/dev/null; done
```

A `crash` entry in `last -x`, an unclean filesystem message such as `Volume was not properly unmounted`, and a very low laptop battery usually means hard power loss rather than an app failure. Charge the battery above 30% before CPU-heavy tests, and check the AC adapter if this repeats.

## Security Notes

The production image runs as a non-root user. Compose enables a read-only root filesystem, drops Linux capabilities, sets `no-new-privileges`, and keeps only `/app/data` writable for SQLite and runtime data. Session cookies include `Secure` when `FULTONS_COOKIE_SECURE=1`, which assumes users access the app through HTTPS.
