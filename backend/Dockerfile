# syntax=docker/dockerfile:1
# One backend image for web, worker and the one-shot migrate job (PLAN.md §3).
# Build context: repository root.

# --- Frontend build (production SPA, served by Django/WhiteNoise from the same origin) ------
FROM node:24-trixie-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Python base -----------------------------------------------------------------------------
FROM python:3.13-slim-trixie AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    GDAL_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgdal.so.36 \
    GEOS_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgeos_c.so.1
# GeoDjango runtime libraries only (GDAL pulls in GEOS and PROJ); no compilers.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgdal36 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

# --- Development / test image: adds test tools; source is bind-mounted in compose.dev.yaml --
FROM base AS dev
COPY backend/requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY backend/ ./

# --- Runtime image ---------------------------------------------------------------------------
FROM base AS runtime
COPY backend/ ./
COPY --from=frontend /src/dist /app/frontend_dist
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput >/dev/null
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--worker-class", "gthread", "--access-logfile", "-"]
