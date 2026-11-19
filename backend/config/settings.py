"""Django settings. Everything environment-specific comes from environment variables
(see .env.example at the repo root); there are no per-environment settings modules."""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from environs import Env

env = Env()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = env.str("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", False)

# --- Internet exposure (D-73, D-85; docs/tracking/exposure.md) ------------------------------
# Host names the internet reaches this app by (the Cloudflare Tunnel's hostname). They are
# always allowed hosts and trusted HTTPS origins, and always guarded (travel/core/exposure.py):
# with TRAVEL_PUBLIC_SCOPE=tracker (until go-live) they reach only the tracker endpoints, "all"
# opens the whole app (go-live, after Authentik with 2FA), and a DEBUG server answers nothing.
TRAVEL_PUBLIC_HOSTS = [
    host for raw in env.list("TRAVEL_PUBLIC_HOSTS", []) if (host := raw.strip().lower().rstrip("."))
]
TRAVEL_PUBLIC_SCOPE = env.str("TRAVEL_PUBLIC_SCOPE", "tracker")
# The public name the app lives at; the other public names answer a permanent redirect to the
# same path on it, except the tracker endpoints (D-96). Default: the first public host.
TRAVEL_CANONICAL_HOST = env.str("TRAVEL_CANONICAL_HOST", "").strip().lower().rstrip(".") or next(
    iter(TRAVEL_PUBLIC_HOSTS), ""
)
# The internet-facing `ingest` service: the tracker endpoints only, whatever the Host header.
TRAVEL_INGEST_ONLY = env.bool("TRAVEL_INGEST_ONLY", False)
# The production stack (compose.prod.yaml, D-96): refuses to start without the production
# settings of auth.md §7.7 (checked at the end of this file).
TRAVEL_PRODUCTION = env.bool("TRAVEL_PRODUCTION", False)

ALLOWED_HOSTS = [
    *env.list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"]),
    *TRAVEL_PUBLIC_HOSTS,
]
CSRF_TRUSTED_ORIGINS = [
    *env.list("DJANGO_CSRF_TRUSTED_ORIGINS", []),
    *(f"https://{host}" for host in TRAVEL_PUBLIC_HOSTS),
]

# GeoDjango finds these with ctypes; pin them so a base-image change fails loudly.
GDAL_LIBRARY_PATH = env.str("GDAL_LIBRARY_PATH", None)
GEOS_LIBRARY_PATH = env.str("GEOS_LIBRARY_PATH", None)

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.postgres",
    "procrastinate.contrib.django",
    "travel.core",
    "travel.accounts",
    "travel.geo",
    "travel.trips",
    "travel.vehicles",
    "travel.history",
    "travel.flights",
    "travel.media",
    "travel.public",
    "travel.tracking",
    "travel.routing",
]

MIDDLEWARE = [
    # First: takes a tracker's `?token=` out of the URL before anything can log or echo it.
    "travel.tracking.middleware.IngestTokenScrubMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Before WhiteNoise: public host names reach only the tracker endpoints until go-live.
    "travel.core.exposure.ExposureGuardMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    # Sets request.user and the row-level-security context in one transaction per request
    # (replaces django.contrib.auth.middleware.AuthenticationMiddleware).
    "travel.core.middleware.RlsContextMiddleware",
    "travel.core.loginwall.LoginWallMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ],
        },
    },
]


def _db(user_var: str, password_var: str, default_user: str) -> dict:
    return {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": env.str("DB_HOST", "db"),
        "PORT": env.int("DB_PORT", 5432),
        "NAME": env.str("DB_NAME", "travel"),
        "USER": env.str(user_var, default_user),
        "PASSWORD": env.str(password_var, ""),
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
    }


# `default` is the runtime role (travel_app, subject to row-level security). Migrations run in a
# separate one-shot container whose DB_USER is travel_owner. `public` is the read-only role the
# public renderer uses; it can only read the public snapshot tables (PLAN.md §6.5).
DATABASES = {
    "default": _db("DB_USER", "DB_PASSWORD", "travel_app"),
    # The rate limiter's own autocommit connection, same role (D-77): counts are final at once,
    # whatever happens to the request's transaction, and bucket row locks last one statement.
    "ratelimit": {
        **_db("DB_USER", "DB_PASSWORD", "travel_app"),
        "TEST": {"MIRROR": "default"},
    },
    "public": {
        **_db("DB_PUBLIC_USER", "DB_PUBLIC_PASSWORD", "travel_public"),
        "TEST": {"MIRROR": "default"},
    },
}
DATABASE_ROUTERS: list[str] = []
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
LOGIN_URL = "/auth/login"

# Header with the real client address when every request arrives through a proxy (e.g.
# "CF-Connecting-IP" behind the Cloudflare Tunnel); empty = use the socket address.
RATELIMIT_CLIENT_IP_HEADER = env.str("RATELIMIT_CLIENT_IP_HEADER", "")

# --- Routing (docs/design/routing.md §13) ---------------------------------------------------
# The self-hosted Valhalla (separate compose project, shared `valhalla` network) and the polygon
# where it has data (travel/routing/coverage/<name>.geojson, or a path to a .geojson file).
VALHALLA_URL = env.str("VALHALLA_URL", "http://valhalla:8002")
VALHALLA_COVERAGE = env.str("VALHALLA_COVERAGE", "kansas")
# Build date of the OSM extract behind the tiles (YYYY-MM-DD; BUILD_INFO.json's
# extract_last_modified). Empty = the tile build time from Valhalla's /status.
VALHALLA_DATA_DATE = env.str("VALHALLA_DATA_DATE", "")
# Hosted fallback outside coverage (routing.md §13.1, Q-9): skipped cleanly while the key is empty.
ORS_API_KEY = env.str("ORS_API_KEY", "")
ORS_URL = env.str("ORS_URL", "https://api.openrouteservice.org")
# Emergency fallback: at most 1 request/s globally, identifying User-Agent, no personal data.
FOSSGIS_OSRM_URL = env.str("FOSSGIS_OSRM_URL", "https://routing.openstreetmap.de/routed-car")
ROUTING_FOSSGIS_ENABLED = env.bool("ROUTING_FOSSGIS_ENABLED", True)
ROUTING_USER_AGENT = env.str(
    "ROUTING_USER_AGENT", "travel-history/1 (+https://travel.adamcasada.com)"
)
ROUTING_TIMEOUT = env.float("ROUTING_TIMEOUT", 15.0)  # seconds per provider request
ROUTING_CACHE_SECONDS = env.int("ROUTING_CACHE_SECONDS", 600)  # identical requests (§13.1)

# --- Tracker ingestion (PLAN.md §9.1) -------------------------------------------------------
# Public origin trackers post to (e.g. https://travel.example.org, item 8); empty = the address
# the browser used when the token was created.
TRACKER_BASE_URL = env.str("TRACKER_BASE_URL", "")
TRACKER_MAX_BODY_BYTES = env.int("TRACKER_MAX_BODY_BYTES", 5 * 1024 * 1024)
TRACKER_MAX_POINTS = env.int("TRACKER_MAX_POINTS", 1000)  # per request (Overland batches)
TRACKER_RATE_PER_TOKEN = env.int("TRACKER_RATE_PER_TOKEN", 120)  # requests per minute
TRACKER_RATE_PER_IP = env.int("TRACKER_RATE_PER_IP", 600)  # requests per minute, all tokens
TRACKER_MAX_SPEED_MPS = env.float("TRACKER_MAX_SPEED_MPS", 400.0)  # plausibility flag limit
TRACKER_MAX_TOKENS_PER_USER = env.int("TRACKER_MAX_TOKENS_PER_USER", 20)  # active tokens

# --- OIDC (PLAN.md §7.1, §7.2) -------------------------------------------------------------
OIDC_ISSUER = env.str("OIDC_ISSUER", "")
OIDC_CLIENT_ID = env.str("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = env.str("OIDC_CLIENT_SECRET", "")
# Development only: internal base URL for server-to-server calls to the provider (see oidc.py).
OIDC_BACKCHANNEL_URL = env.str("OIDC_BACKCHANNEL_URL", "")
# Only members of this provider group may use the app ("" disables the check).
OIDC_REQUIRED_GROUP = env.str("OIDC_REQUIRED_GROUP", "travel-users")
# Bearer tokens: Authentik issues one issuer per provider (web + Android).
OIDC_ACCEPTED_ISSUERS = [i for i in [OIDC_ISSUER, *env.list("OIDC_EXTRA_ISSUERS", [])] if i]
OIDC_ACCEPTED_AUDIENCES = [a for a in [OIDC_CLIENT_ID, *env.list("OIDC_EXTRA_AUDIENCES", [])] if a]
# Approvals and destructive admin actions need a login at most this many seconds old.
REAUTH_MAX_AGE = env.int("REAUTH_MAX_AGE", 300)
# Per-address limits on the public pages (auth.md §7.7): sign-in starts and provider callbacks
# per 10 minutes each, landing-page views per minute.
AUTH_RATE_PER_IP = env.int("AUTH_RATE_PER_IP", 30)
LANDING_RATE_PER_IP = env.int("LANDING_RATE_PER_IP", 60)

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Built SPA (production image): files live in SPA_ROOT/app/ and are served at /app/ by WhiteNoise.
SPA_ROOT = Path(env.str("SPA_ROOT", str(BASE_DIR / "spa_root")))
if SPA_ROOT.exists():
    WHITENOISE_ROOT = SPA_ROOT
WHITENOISE_MIMETYPES = {".webmanifest": "application/manifest+json"}

# Bulk storage on the HDD: raw import files, photo derivatives, backup outbox.
BULK_DIR = Path(env.str("TRAVEL_BULK_DIR_IN_CONTAINER", "/bulk"))
# Uploads (PLAN.md D-33): 32 MiB chunks stay well under Cloudflare's 100 MB request limit.
TRAVEL_UPLOAD_CHUNK_BYTES = env.int("TRAVEL_UPLOAD_CHUNK_BYTES", 32 * 1024 * 1024)
TRAVEL_UPLOAD_MAX_BYTES = env.int("TRAVEL_UPLOAD_MAX_BYTES", 2 * 1024**3)
TRAVEL_USER_QUOTA_BYTES = env.int("TRAVEL_USER_QUOTA_BYTES", 20 * 1024**3)

# --- Security -------------------------------------------------------------------------------
SESSION_COOKIE_SECURE = env.bool("DJANGO_SECURE_COOKIES", True)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env.int("DJANGO_SESSION_AGE", 60 * 60 * 24 * 14)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# Cloudflare terminates TLS: it sets X-Forwarded-Proto to the visitor's scheme (overwriting any
# value the client sent) and cloudflared passes it on. Behind it the app is HTTPS-only: plain
# HTTP is redirected (the container's own health check excepted) and HSTS is on.
BEHIND_TLS_PROXY = env.bool("DJANGO_BEHIND_TLS_PROXY", False)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if BEHIND_TLS_PROXY else None
SECURE_SSL_REDIRECT = env.bool("DJANGO_SSL_REDIRECT", BEHIND_TLS_PROXY)
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", 365 * 24 * 3600 if BEHIND_TLS_PROXY else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
DATA_UPLOAD_MAX_MEMORY_SIZE = 40 * 1024 * 1024  # one upload chunk (32 MB) plus headroom

SECURE_CSP = {
    "default-src": ["'self'"],
    "script-src": ["'self'"],
    "style-src": ["'self'", "'unsafe-inline'"],  # MapLibre sets inline styles
    "img-src": ["'self'", "data:", "blob:", "https://tiles.openfreemap.org"],
    "connect-src": ["'self'", "https://tiles.openfreemap.org"],
    "font-src": ["'self'", "https://tiles.openfreemap.org"],
    "worker-src": ["'self'", "blob:"],
    "frame-ancestors": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
}
# Sign-out is a form POST that redirects to the provider's end-session page; Chrome applies
# form-action to that redirect, so the provider's origin must be allowed.
if OIDC_ISSUER:
    from urllib.parse import urlsplit

    _issuer = urlsplit(OIDC_ISSUER)
    SECURE_CSP["form-action"].append(f"{_issuer.scheme}://{_issuer.netloc}")

# --- Logging --------------------------------------------------------------------------------
# Every line goes through a redacting formatter (device tokens, token query parameters,
# Authorization values; travel/core/logredact.py). Django's own handlers are replaced: its
# `mail_admins` would send request details, and runserver's request log prints raw URLs.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {
            "()": "travel.core.logredact.RedactingFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
        "django.server": {
            "()": "travel.core.logredact.RedactingServerFormatter",
            "format": "[{server_time}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "django.server": {"class": "logging.StreamHandler", "formatter": "django.server"},
    },
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": [], "level": "INFO", "propagate": True},
        "django.server": {"handlers": ["django.server"], "level": "INFO", "propagate": False},
        "django.db.backends": {"level": "WARNING"},
    },
}

# --- Exposure checks -------------------------------------------------------------------------
if TRAVEL_PUBLIC_SCOPE not in ("tracker", "all"):
    raise ImproperlyConfigured("TRAVEL_PUBLIC_SCOPE must be 'tracker' or 'all'")
if TRAVEL_CANONICAL_HOST and TRAVEL_CANONICAL_HOST not in TRAVEL_PUBLIC_HOSTS:
    raise ImproperlyConfigured("TRAVEL_CANONICAL_HOST must be one of TRAVEL_PUBLIC_HOSTS")
if TRAVEL_PRODUCTION or TRAVEL_INGEST_ONLY:
    # Servers facing the internet refuse to start without production settings (fail closed).
    from travel.core.exposure import production_problems

    _problems = production_problems(globals())
    if _problems:
        _which = "TRAVEL_INGEST_ONLY" if TRAVEL_INGEST_ONLY else "TRAVEL_PRODUCTION"
        raise ImproperlyConfigured(f"{_which}: " + "; ".join(_problems))
