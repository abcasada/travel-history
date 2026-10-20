"""Django settings. Everything environment-specific comes from environment variables
(see .env.example at the repo root); there are no per-environment settings modules."""

from pathlib import Path

from environs import Env

env = Env()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = env.str("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", [])

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
    "travel.media",
    "travel.public",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
# Cloudflare Tunnel terminates TLS; cloudflared forwards X-Forwarded-Proto.
if env.bool("DJANGO_BEHIND_TLS_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", 0)
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
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", "INFO")},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}
