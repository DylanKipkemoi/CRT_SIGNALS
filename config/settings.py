"""Django settings for the CRT Signals platform.

All secrets and environment-specific values are read from environment
variables (optionally loaded from a local ``.env`` file).
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-change-me"
    else:
        hint = "" if ENV_FILE.exists() else (
            f" No .env file found at {ENV_FILE}: copy .env.example to .env (it enables DEBUG for local development)."
        )
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false." + hint)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "accounts",
    "markets",
    "signals",
    "access",
    "payments",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database: SQLite for development. Set DATABASE_ENGINE etc. for production.
DATABASE_ENGINE = env("DATABASE_ENGINE", "django.db.backends.sqlite3")
if DATABASE_ENGINE == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": DATABASE_ENGINE,
            "NAME": env("DATABASE_NAME", str(BASE_DIR / "db.sqlite3")),
            "OPTIONS": {"timeout": 20},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": DATABASE_ENGINE,
            "NAME": env("DATABASE_NAME"),
            "USER": env("DATABASE_USER"),
            "PASSWORD": env("DATABASE_PASSWORD"),
            "HOST": env("DATABASE_HOST", "localhost"),
            "PORT": env("DATABASE_PORT", ""),
            "CONN_MAX_AGE": env_int("DATABASE_CONN_MAX_AGE", 60),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "signals:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Cache: used for rate limiting, market-data caching and scanner locks.
# LocMem is per-process; use Redis (or the DB cache) in production.
REDIS_URL = env("REDIS_URL")
if REDIS_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
elif env("CACHE_BACKEND") == "database":
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "cache_table"}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "crt-signals"}}

# Email
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "CRT Signals <no-reply@localhost>")
CONTACT_EMAIL = env("CONTACT_EMAIL", "support@localhost")
SITE_NAME = env("SITE_NAME", "CRT Signals")
SITE_URL = env("SITE_URL", "http://127.0.0.1:8000")

# Security
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 60 * 60 * 24 * 7)
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 60 * 60 * 24 * 30)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
    if env_bool("USE_X_FORWARDED_PROTO", False):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Number of reverse proxies in front of Django (used to read the client IP safely).
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", 0)

# Rate limits: "<max requests>/<window seconds>"
RATE_LIMITS = {
    "login": env("RATE_LIMIT_LOGIN", "5/900"),
    "register": env("RATE_LIMIT_REGISTER", "10/3600"),
    "password_reset": env("RATE_LIMIT_PASSWORD_RESET", "5/3600"),
    "payment_initiate": env("RATE_LIMIT_PAYMENT", "5/600"),
    "api": env("RATE_LIMIT_API", "120/60"),
    "contact": env("RATE_LIMIT_CONTACT", "5/3600"),
    "callback": env("RATE_LIMIT_CALLBACK", "300/60"),
}

# --- Market data -----------------------------------------------------------
MARKET_DATA = {
    "HTTP_TIMEOUT": env_int("MARKET_DATA_HTTP_TIMEOUT", 10),
    "RETRIES": env_int("MARKET_DATA_RETRIES", 3),
    "CACHE_SECONDS": env_int("MARKET_DATA_CACHE_SECONDS", 30),
    "MIN_REQUEST_INTERVAL": float(env("MARKET_DATA_MIN_REQUEST_INTERVAL", "0.25")),
    # A feed is stale when its latest completed candle closed more than
    # (timeframe + grace) ago.
    "STALE_GRACE_SECONDS": env_int("MARKET_DATA_STALE_GRACE_SECONDS", 180),
    "QUOTE_MAX_AGE_SECONDS": env_int("MARKET_DATA_QUOTE_MAX_AGE_SECONDS", 120),
    "OANDA_API_TOKEN": env("OANDA_API_TOKEN", ""),
    "OANDA_ACCOUNT_ID": env("OANDA_ACCOUNT_ID", ""),
    "OANDA_ENVIRONMENT": env("OANDA_ENVIRONMENT", "practice"),
    "TWELVEDATA_API_KEY": env("TWELVEDATA_API_KEY", ""),
}

SCANNER = {
    "INTERVAL_SECONDS": env_int("SCANNER_INTERVAL_SECONDS", 300),
    "LOCK_SECONDS": env_int("SCANNER_LOCK_SECONDS", 600),
    "HEALTHY_MAX_AGE_SECONDS": env_int("SCANNER_HEALTHY_MAX_AGE_SECONDS", 900),
}

# --- M-Pesa Daraja ---------------------------------------------------------
DARAJA = {
    "ENVIRONMENT": env("DARAJA_ENVIRONMENT", "sandbox"),  # sandbox | production
    "CONSUMER_KEY": env("DARAJA_CONSUMER_KEY", ""),
    "CONSUMER_SECRET": env("DARAJA_CONSUMER_SECRET", ""),
    "SHORTCODE": env("DARAJA_SHORTCODE", ""),
    "PASSKEY": env("DARAJA_PASSKEY", ""),
    # CustomerPayBillOnline (paybill) or CustomerBuyGoodsOnline (till)
    "TRANSACTION_TYPE": env("DARAJA_TRANSACTION_TYPE", "CustomerPayBillOnline"),
    # For Buy Goods the till number differs from the HO/store shortcode.
    "PARTY_B": env("DARAJA_PARTY_B", ""),
    "CALLBACK_BASE_URL": env("DARAJA_CALLBACK_BASE_URL", ""),
    "CALLBACK_TOKEN": env("DARAJA_CALLBACK_TOKEN", ""),
    "ALLOWED_CALLBACK_IPS": env_list("DARAJA_ALLOWED_CALLBACK_IPS", ""),
    "VERIFY_WITH_QUERY": env_bool("DARAJA_VERIFY_WITH_QUERY", True),
    "ACCOUNT_REFERENCE": env("DARAJA_ACCOUNT_REFERENCE", "CRTSIGNALS"),
    "HTTP_TIMEOUT": env_int("DARAJA_HTTP_TIMEOUT", 30),
    "PENDING_TIMEOUT_SECONDS": env_int("DARAJA_PENDING_TIMEOUT_SECONDS", 180),
}

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"standard": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "app.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "standard",
            "encoding": "utf-8",
            "delay": True,
        },
    },
    "root": {"handlers": ["console", "file"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": ["console", "file"], "level": "WARNING", "propagate": False},
    },
}
