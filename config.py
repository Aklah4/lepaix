import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


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
    # Sent via Resend's HTTPS API - Railway blocks outbound SMTP, so raw
    # smtp.gmail.com is unreachable in production. Nothing here is a credential.
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
    # The "from" address. MUST be on a domain verified in Resend (SPF/DKIM);
    # a bare @gmail.com sender will be rejected. e.g. "Lepaix <orders@lepaix.com>".
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "")
    # Where the "new order placed" notification goes (any address is fine).
    VENDOR_EMAIL = os.environ.get("VENDOR_EMAIL", "")
    # Seconds before a hung HTTPS call to Resend gives up.
    MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT") or 20)

    # Business timezone for daily revenue/order reporting. Nigeria is WAT
    # (UTC+1, no daylight saving), so a fixed offset is exact and needs no
    # tz database. The "day" the dashboard resets on is measured against this.
    REPORT_TZ_OFFSET_HOURS = int(os.environ.get("REPORT_TZ_OFFSET_HOURS") or 1)


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class TestingConfig(Config):
    TESTING = True
    SESSION_COOKIE_SECURE = False
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
