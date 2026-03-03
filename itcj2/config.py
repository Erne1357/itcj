import os
import json
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+psycopg2://postgres:password@postgres:5432/itcj"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Security
    SECRET_KEY: str = "dev"
    JWT_SECRET_KEY: str = "my_jwt_secret"
    JWT_EXPIRES_HOURS: int = 12
    JWT_REFRESH_THRESHOLD_SECONDS: int = 2 * 3600  # 2 horas

    # Cookies
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    # Environment
    FLASK_ENV: str = "production"
    APP_TZ: str = "America/Ciudad_Juarez"

    # CORS
    CORS_ORIGINS: str = ""

    # Domain
    DOMAIN: str = "http://localhost:8080"

    # Uploads
    INSTANCE_PATH: str = os.path.abspath("instance")
    HELPDESK_UPLOAD_PATH: str = os.path.join(os.path.abspath("instance"), "apps", "helpdesk")
    HELPDESK_MAX_FILE_SIZE: int = 3 * 1024 * 1024
    HELPDESK_ALLOWED_EXTENSIONS: str = "jpg,jpeg,png,gif,webp"
    HELPDESK_MAX_DOCUMENT_SIZE: int = 25 * 1024 * 1024
    HELPDESK_ALLOWED_DOC_EXTENSIONS: str = "xlsx,xls,csv,pdf,doc,docx"

    VISTETEC_UPLOAD_PATH: str = os.path.join(os.path.abspath("instance"), "apps", "vistetec", "garments")
    VISTETEC_MAX_IMAGE_SIZE: int = 3 * 1024 * 1024
    VISTETEC_ALLOWED_EXTENSIONS: str = "jpg,jpeg,png,webp"

    # Static versioning
    STATIC_VERSION: str = "1.0.111111"

    model_config = {"env_file": ".env", "extra": "ignore"}

    def get_cors_origins(self) -> list[str]:
        if self.FLASK_ENV == "development":
            return [
                "http://localhost:8080",
                "http://127.0.0.1:8080",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "http://localhost:8001",
                "http://127.0.0.1:8001",
            ]
        if self.CORS_ORIGINS:
            return [o.strip() for o in self.CORS_ORIGINS.split(",")]
        return [
            "https://enlinea.cdjuarez.tecnm.mx",
            "https://siiapec.cdjuarez.tecnm.mx",
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_static_manifest() -> dict:
    """Carga el manifiesto de hashes de archivos estáticos (compartido con Flask)."""
    manifest_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static-manifest.json",
    )
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}
