FROM node:24-alpine AS frontend

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html postcss.config.js tailwind.config.ts tsconfig.json vite.config.ts ./
COPY src ./src
RUN npm run build

FROM python:3.14-alpine

WORKDIR /app

RUN apk add --no-cache tzdata

COPY server.py wordle_game.py ./
COPY --from=frontend /app/dist ./dist

ENV FULTONS_HOST=0.0.0.0
ENV FULTONS_PORT=3000
ENV FULTONS_TIMEZONE=Europe/London
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 3000
VOLUME ["/app/data"]

CMD ["python", "-u", "server.py"]
