"""Django settings for the SearchSmartly PoI importer.

Every value that differs between a laptop and a server is read from the
environment with a development-friendly default, so the same code runs in both
without edits. See the Configuration table in README.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

#: True while ``manage.py test`` is running. Used to relax two settings that
#: would otherwise demand real production configuration from a test run.
RUNNING_TESTS = "test" in sys.argv or os.environ.get("DJANGO_TESTING") == "1"


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable.

    Accepts the spellings people actually type. Anything unrecognised falls
    back to ``default`` rather than silently reading as False, which is how
    ``DEBUG=flase`` ends up shipping to production.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _env_list(name: str, default: list[str]) -> list[str]:
    """Read a comma-separated environment variable into a list."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


# --- Core -------------------------------------------------------------------

DEBUG = _env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if RUNNING_TESTS:
        # Tests never persist sessions or signatures across runs, so a throwaway
        # key is correct here and keeps the suite runnable with no environment.
        from django.core.management.utils import get_random_secret_key

        SECRET_KEY = get_random_secret_key()
    elif not DEBUG:
        raise RuntimeError(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off. "
            "Generate one with: python -c "
            "'from django.core.management.utils import get_random_secret_key as k; print(k())'"
        )
    else:
        # Development only, and only ever reached with DEBUG on.
        SECRET_KEY = "django-insecure-development-only-do-not-use-in-production"

# Defaults to loopback rather than '*': an over-broad ALLOWED_HOSTS is how
# Host-header poisoning gets in.
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]"])
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "poi.apps.PoiConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "SearchSmartly.urls"
WSGI_APPLICATION = "SearchSmartly.wsgi.application"
ASGI_APPLICATION = "SearchSmartly.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": os.environ.get("DJANGO_DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.environ.get("DJANGO_DB_NAME", str(BASE_DIR / "db.sqlite3")),
        "USER": os.environ.get("DJANGO_DB_USER", ""),
        "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
        "HOST": os.environ.get("DJANGO_DB_HOST", ""),
        "PORT": os.environ.get("DJANGO_DB_PORT", ""),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth -------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n / static ----------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Celery -----------------------------------------------------------------

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "amqp://localhost:5672//")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "")
# Off by default: the previous version forced this on unconditionally, which
# meant every ``.delay()`` ran inline and the "asynchronous processing" the
# README advertised never actually happened. Tests run eager so they need no
# broker and make no network connection.
CELERY_TASK_ALWAYS_EAGER = _env_bool("CELERY_TASK_ALWAYS_EAGER", RUNNING_TESTS)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

# --- Security (applied when not in DEBUG) -----------------------------------

if not DEBUG and not RUNNING_TESTS:
    SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # Off by default: submitting a domain to the browser preload list is
    # effectively irreversible, so it is an explicit operator decision.
    SECURE_HSTS_PRELOAD = _env_bool("DJANGO_HSTS_PRELOAD", False)
    X_FRAME_OPTIONS = "DENY"

# --- Logging ----------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {
        "handlers": ["console"],
        # Import progress is useful on the command line and noise in a test
        # run, where assertions already say what happened.
        "level": os.environ.get("DJANGO_LOG_LEVEL", "CRITICAL" if RUNNING_TESTS else "INFO"),
    },
}
