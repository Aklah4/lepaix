import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    DEBUG = False
    TESTING = False
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/lepaix")
    MONGO_DBNAME = os.environ.get("MONGO_DBNAME", "lepaix")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
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
