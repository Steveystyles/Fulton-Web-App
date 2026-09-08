FROM node:22-alpine AS frontend

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html postcss.config.js tailwind.config.ts tsconfig.json vite.config.ts ./
COPY public ./public
COPY src ./src
RUN npm run build

FROM python:3.12-alpine

WORKDIR /app

ARG FULTONS_BUILD_COMMIT=unknown

RUN apk upgrade --no-cache \
  && apk add --no-cache tzdata \
  && adduser -D -u 1000 appuser

LABEL org.opencontainers.image.revision="${FULTONS_BUILD_COMMIT}" \
      org.opencontainers.image.source="https://github.com/Steveystyles/Fulton-Web-App.git"

COPY --chown=appuser:appuser server.py daily_quiz.py quiz_evidence.py daily_map_game.py env_config.py safe_http.py wordle_game.py ./
COPY --chown=appuser:appuser games ./games
COPY --chown=appuser:appuser tools/__init__.py tools/build_map_learning_profile.py tools/build_map_selector_profile.py tools/build_quiz_learning_profile.py tools/evaluate_quiz_candidate_pipeline.py tools/export_map_place_review_batch.py tools/generate_ai_daily_map_round.py tools/generate_map_place_candidates_with_ai.py tools/install_map_training_seed.py tools/map_clue_failure_log.py tools/map_clue_quality_model.py tools/map_selector_model.py tools/refresh_map_learning_profile.py tools/refresh_quiz_learning_profile.py tools/rewrite_map_clues_with_ai.py tools/training_data_store.py ./tools/
COPY --chown=appuser:appuser tools/map_launch_round.py ./tools/
COPY --chown=appuser:appuser tools/install_map_reviewed_fallbacks.py ./tools/
COPY --chown=appuser:appuser tools/controlled_map_round.py tools/preview_ai_map_round.py ./tools/
COPY --chown=appuser:appuser tools/discover_map_places.py ./tools/
COPY --chown=appuser:appuser tools/automatic_map_pool.py ./tools/
COPY --chown=appuser:appuser deploy/map-evidence-catalog.json ./map-evidence-catalog.json
COPY --chown=appuser:appuser deploy/map-training-seed ./map-training-seed
COPY --chown=appuser:appuser deploy/map-reviewed-fallbacks.json ./map-reviewed-fallbacks.json
COPY --chown=appuser:appuser deploy/map-launch-round-2026-08-04.json ./map-launch-round/
COPY --chown=appuser:appuser --from=frontend /app/dist ./dist

ENV FULTONS_HOST=0.0.0.0
ENV FULTONS_PORT=3000
ENV FULTONS_TIMEZONE=Europe/London
ENV FULTONS_COOKIE_SECURE=1
ENV FULTONS_SEED_DEMO_USERS=0
ENV FULTONS_BUILD_COMMIT="${FULTONS_BUILD_COMMIT}"
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 3000
VOLUME ["/app/data"]

USER appuser

CMD ["python", "-u", "server.py"]
