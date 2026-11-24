# syntax=docker/dockerfile:1
# One backend image for web, worker and the one-shot migrate job (PLAN.md §3).
# Build context: repository root.

# --- Frontend build (production SPA, served by Django/WhiteNoise from the same origin) ------
FROM node:24.22.0-trixie-slim@sha256:a6155384446670e9719bdc4fd0ebe4d4b29fb32a8d6aa523da3547a6cfbcf22c AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Python base -----------------------------------------------------------------------------
FROM python:3.13.16-slim-trixie@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    GDAL_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgdal.so.36 \
    GEOS_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgeos_c.so.1
# GeoDjango runtime libraries only (GDAL pulls in GEOS and PROJ); no compilers. The pinned base
# image lags Debian's security updates (41a's F-6: openssl, krb5, zlib, …), so the build takes
# them: rebuilding without the layer cache (a new digest, or `--no-cache`) picks up new ones.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
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
COPY --from=frontend /src/dist /app/spa_root/app
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput >/dev/null
EXPOSE 8000
# The access log prints the path without the query string (%(U)s, not the request line), so a
# tracker token sent as ?token= can't land in it even if the app's scrubbing were bypassed.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--worker-class", "gthread", "--access-logfile", "-", "--access-logformat", "%(h)s %(t)s \"%(m)s %(U)s %(H)s\" %(s)s %(b)s %(M)sms \"%(a)s\""]
