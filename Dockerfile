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
ARG FULTONS_BUILD_SOURCE=unknown

RUN apk add --no-cache tzdata \
  && adduser -D -u 1000 appuser

LABEL org.opencontainers.image.revision="${FULTONS_BUILD_COMMIT}" \
      org.opencontainers.image.source="${FULTONS_BUILD_SOURCE}"

COPY --chown=appuser:appuser server.py production_server.py daily_quiz.py local_ops_settings.py ops_monitor.py wordle_game.py wordle_words.txt ./
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

CMD ["python", "-u", "production_server.py"]
