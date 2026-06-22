# --- Stage 1: PWA bauen (Astro → static dist/) ---
FROM node:22-slim AS web-builder

WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# --- Stage 2: Python-Runtime (uv installiert die Deps) ---
FROM python:3.12-slim AS runtime

# Build-Tools für fastembed/ONNX-Laufzeit + dumb-init (PID 1 Signal-Forwarding)
# + curl für den Docker-Healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        dumb-init \
        lsof \
    && rm -rf /var/lib/apt/lists/*

# uv statt pip — schnell, deterministisch (wie im lokalen Setup).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Deps zuerst (besserer Layer-Cache als Code-everything-at-once).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Anwendungscode + gebautes Web.
COPY kb/ kb/
COPY kb.toml ./

# PWA-Dist aus Stage 1 (Gateway serviert sie aus web/dist/).
COPY --from=web-builder /app/web/dist web/dist/

# Daten-Volumes (var/ = cognee-DBs/Queues, raw/ = Rohschicht).
# kb.toml + .env.* werden zur Laufzeit gemountet (kein Rebuild bei Topologie-Change).
VOLUME ["/app/var", "/app/raw"]

EXPOSE 8800

# dumb-init als PID 1: korrektes Signal-Forwarding (SIGTERM → kb serve),
# reapt Zombies, kein Python-Signal-Gedöns als PID 1.
# healthcheck gegen /api/health (ohne Token, liefert {"gateway":"ok"}).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8800/api/health || exit 1

CMD ["dumb-init", "--", "uv", "run", "kb", "serve"]
