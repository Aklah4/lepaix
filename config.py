import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _env_bool(name, default):
    """Read a truthy/falsy env var, falling back when it is unset or blank."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY")
    DEBUG = False
    TESTING = False
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/lepaix")
    MONGO_DBNAME = os.environ.get("MONGO_DBNAME", "lepaix")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = True

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB per request

    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

    # ── Outgoing mail (order confirmations) ──────────────────────────────────
    # Everything comes from the environment; nothing here is a real credential.
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or 587)
    # 465 is implicit SSL, 587 is STARTTLS. Either can be overridden explicitly.
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", MAIL_PORT == 465)
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", not MAIL_USE_SSL)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    # Most providers require the envelope sender to match the authenticated
    # account, so fall back to the username rather than sending as nobody.
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER") or MAIL_USERNAME
    # Where the "new order placed" notification goes.
    VENDOR_EMAIL = os.environ.get("VENDOR_EMAIL") or MAIL_USERNAME
    # Give up rather than hold a worker thread open on a dead SMTP host.
    MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT") or 20)

    # Business timezone for daily revenue/order reporting. Nigeria is WAT
    # (UTC+1, no daylight saving), so a fixed offset is exact and needs no
    # tz database. The "day" the dashboard resets on is measured against this.
    REPORT_TZ_OFFSET_HOURS = int(os.environ.get("REPORT_TZ_OFFSET_HOURS") or 1)
    # Flask-Mail otherwise mirrors app.debug here, which dumps the whole SMTP
    # conversation - including the base64 AUTH line holding the password - to
    # the console on every send. Never log credentials.
    MAIL_DEBUG = False


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class TestingConfig(Config):
    TESTING = True
    SESSION_COOKIE_SECURE = False
    MAIL_SUPPRESS_SEND = True
    MONGO_URI = os.environ.get("TEST_MONGO_URI", "mongodb://localhost:27017/lepaix_test")
    MONGO_DBNAME = os.environ.get("TEST_MONGO_DBNAME", "lepaix_test")


class ProductionConfig(Config):
    DEBUG = False


def get_config(name: str | None = None):
    """Return a config class by name or FLASK_ENV."""
    name = name or os.environ.get("FLASK_ENV", "development")
    return {
        "development": DevelopmentConfig,
        "testing": TestingConfig,
        "production": ProductionConfig,
    }.get(name, DevelopmentConfig)
