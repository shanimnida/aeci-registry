from pathlib import Path

import environ
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    # Must precede django.contrib.admin: it overrides admin templates and a
    # couple of admin/js/* files by app-loader precedence, and it replaces
    # admin.site with its own AdminSite subclass from an AppConfig.ready()
    # hook (see aeci/urls.py for the header/title/app-ordering set on top of
    # that). unfold.contrib.simple_history must sit between unfold and
    # simple_history for the same reason, scoped to the history templates.
    "unfold",
    "unfold.contrib.simple_history",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "simple_history",
    "core",
    "people",
    "committees",
    "records",
]

# AEGIS admin theme (django-unfold). Purely cosmetic: site branding, a real
# sidebar, colour, typography. None of this touches permissions — every
# sidebar item's visibility is gated by the same request.user.has_perm(...)
# checks the underlying ModelAdmin already enforces, not a parallel ruleset.
UNFOLD = {
    "SITE_TITLE": "AEGIS",
    "SITE_HEADER": "AEGIS",
    "SITE_SUBHEADER": "Avdei Elohim Growth Information System",
    "SITE_SYMBOL": "shield_person",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "BORDER_RADIUS": "8px",
    "COLORS": {
        # Restrained corporate blue used only for interactive/active state —
        # the neutral "base" scale (Unfold's default) carries everything
        # else, so colour still reads as meaning rather than decoration.
        "primary": {
            "50": "#eff6ff",
            "100": "#dbeafe",
            "200": "#bfdbfe",
            "300": "#93c5fd",
            "400": "#60a5fa",
            "500": "#3b82f6",
            "600": "#2563eb",
            "700": "#1d4ed8",
            "800": "#1e40af",
            "900": "#1e3a8a",
            "950": "#172554",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": _("Registry"),
                "separator": True,
                "items": [
                    {
                        "title": _("People"),
                        "icon": "person",
                        "link": reverse_lazy("admin:people_person_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "people.view_person"
                        ),
                    },
                    {
                        "title": _("Households"),
                        "icon": "home",
                        "link": reverse_lazy("admin:people_household_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "people.view_household"
                        ),
                    },
                ],
            },
            {
                "title": _("Committees"),
                "separator": True,
                "items": [
                    {
                        "title": _("Committees"),
                        "icon": "groups",
                        "link": reverse_lazy("admin:committees_committee_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "committees.view_committee"
                        ),
                    },
                    {
                        "title": _("Committee memberships"),
                        "icon": "badge",
                        "link": reverse_lazy(
                            "admin:committees_committeemembership_changelist"
                        ),
                        "permission": lambda request: request.user.has_perm(
                            "committees.view_committeemembership"
                        ),
                    },
                    {
                        "title": _("Positions"),
                        "icon": "military_tech",
                        "link": reverse_lazy("admin:committees_position_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "committees.view_position"
                        ),
                    },
                    {
                        "title": _("Appointments"),
                        "icon": "event_available",
                        "link": reverse_lazy("admin:committees_appointment_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "committees.view_appointment"
                        ),
                    },
                ],
            },
            {
                "title": _("Records"),
                "separator": True,
                "items": [
                    {
                        "title": _("Form scans"),
                        "icon": "description",
                        "link": reverse_lazy("admin:records_formscan_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "records.view_formscan"
                        ),
                    },
                    {
                        "title": _("Access logs"),
                        "icon": "history",
                        "link": reverse_lazy("admin:records_accesslog_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "records.view_accesslog"
                        ),
                    },
                    {
                        "title": _("Purge records"),
                        "icon": "delete_history",
                        "link": reverse_lazy("admin:records_purgerecord_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "records.view_purgerecord"
                        ),
                    },
                ],
            },
            {
                "title": _("Administration"),
                "separator": True,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "manage_accounts",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "auth.view_user"
                        ),
                    },
                    {
                        "title": _("Groups"),
                        "icon": "admin_panel_settings",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "auth.view_group"
                        ),
                    },
                ],
            },
        ],
    },
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "aeci.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "aeci.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-ph"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Contact data is purged this many days after a person becomes
# TRANSFERRED or DECEASED. Spec section 5.1: two years.
CONTACT_RETENTION_DAYS = 730

# Version string stamped on the current paper profiling form footer.
CONSENT_FORM_VERSION = "v2 (August 2026)"

# pg_dump is not guaranteed to be on PATH — a stock Windows install of
# PostgreSQL does not add its bin directory to PATH, so the bare command
# name resolves on some hosts and not others. Override with the full path
# to the binary via the environment when needed; the bare name is a
# sensible default for hosts (Linux servers, most package managers) where
# it already is on PATH. Never hardcode a host-specific path here.
PG_DUMP_PATH = env("PG_DUMP_PATH", default="pg_dump")

# Static files always go through whitenoise. Media storage is what the flag
# switches — the two are unrelated and must not be coupled.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"

# Scans MUST live in object storage in production. A free-tier host resets its
# filesystem on every redeploy and on idle spin-down, which silently destroys
# uploads. Off by default so local development needs no credentials.
if env.bool("USE_S3_STORAGE", default=False):
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),
            "endpoint_url": env("AWS_S3_ENDPOINT_URL"),
            "access_key": env("AWS_ACCESS_KEY_ID"),
            "secret_key": env("AWS_SECRET_ACCESS_KEY"),
            "default_acl": "private",
            "querystring_auth": True,
        },
    }

# Backups follow the media storage: on a host whose disk resets, a local dump
# is not a backup. Defaults to wherever scans go.
BACKUP_TO_STORAGE = env.bool(
    "BACKUP_TO_STORAGE", default=env.bool("USE_S3_STORAGE", default=False)
)
BACKUP_RETENTION_DAYS = env.int("BACKUP_RETENTION_DAYS", default=30)

# Without this, Django's built-in default (an email to ADMINS, which this
# project never configures — see django.utils.log.DEFAULT_LOGGING) sends
# every unhandled 500 nowhere. A volunteer whose site breaks then has
# nothing to look at. Writing to stdout instead is what the hosting
# platform actually captures and lets you page through.
#
# Deliberately not a file: on a free-tier host the filesystem is wiped on
# every redeploy and on idle spin-down (see the USE_S3_STORAGE comment
# above for the same fact biting media storage), so a log file would
# vanish before anyone read it.
#
# What this does NOT do, on purpose: the formatter below renders only
# levelname/time/logger name/message. Django attaches the live
# HttpRequest object to error LogRecords via extra={"request": request}
# (see django.utils.log.log_response) specifically so a *request-aware*
# handler — django.utils.log.AdminEmailHandler is the built-in example —
# can pull GET/POST/META/cookies out of it for a detailed report. A plain
# %(message)s-style formatter never references that attribute, so it is
# simply inert on the record and nothing from the request body reaches
# this stream. The path Django does log (e.g. "Internal Server Error:
# /admin/people/person/42/change/") is request.path only, never the query
# string, so filter/search values typed into the changelist URL don't
# appear here either. A plain traceback prints call frames, not local
# variable values, so member data would only leak into a log line if
# application code put it into an exception message directly — none does
# today. "django.request" is kept separate from "django" and does not
# propagate, so the same 500 is not printed twice.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "{asctime} {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "simple",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

# Production security settings. Gated on DEBUG rather than a dedicated flag
# because these must never be forgotten on a real deploy, and there is no
# legitimate production configuration with DEBUG=True.
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    X_FRAME_OPTIONS = "DENY"
