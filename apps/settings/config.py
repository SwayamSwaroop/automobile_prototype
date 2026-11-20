"""Core settings shared with parent portal, with school-specific service defaults."""

from functools import lru_cache
import os
from pathlib import Path
from typing import Optional

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


def _select_env_file() -> str:
    raw_env = os.getenv("ENVIRONMENT", "development").lower()

    env_file_map = {
        "development": ".env_dev",
        "dev": ".env_dev",
        "staging": ".env_stag",
        "stag": ".env_stag",
        "production": ".env_prod",
        "prod": ".env_prod",
    }

    filename = env_file_map.get(raw_env, ".env_dev")
    return str(ROOT_DIR / filename)


class Settings(BaseSettings):
    # Core
    environment: str = "development"
    debug: bool = False
    app_title: str = "School MenteeZ Core"
    app_version: str = "0.1.0"
    app_root_path: str = "/api"

    # PostgreSQL raw values, optional. DATABASE_URL remains the connection source.
    postgres_user: Optional[str] = None
    postgres_password: Optional[SecretStr] = None
    postgres_db: Optional[str] = None

    # Database
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/school_menteez_db"
    )
    db_schema: str = "app_core"

    # Media
    media_root: str = "media"
    public_media_prefix: str = "/media"
    media_storage_backend: str = "local"

    # S3 media storage
    s3_bucket_name: Optional[str] = None
    s3_region: str = "ap-south-1"
    s3_key_prefix: str = "media"
    s3_public_base_url: Optional[str] = None

    # AWS common. Local credentials are optional; deployments can use IAM roles.
    aws_region: str = "ap-south-1"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[SecretStr] = None
    aws_session_token: Optional[SecretStr] = None

    # CORS
    cors_allow_origins: str = "*"

    # Application logging. These names match the shared parent-portal logging setup.
    app_name: str = "school-menteez-api"
    log_level: str = "INFO"
    log_format: str = "console"
    log_queue_size: int = 10_000
    log_slow_request_threshold_ms: int = 2_000
    log_shutdown_flush_timeout_seconds: float = 3.0
    log_request_body: bool = False
    log_response_body: bool = False

    model_config = SettingsConfigDict(
        env_file=_select_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def postgres_password_value(self) -> Optional[str]:
        if not self.postgres_password:
            return None
        return self.postgres_password.get_secret_value()

    @property
    def aws_secret_access_key_value(self) -> Optional[str]:
        if not self.aws_secret_access_key:
            return None
        return self.aws_secret_access_key.get_secret_value().strip()

    @property
    def aws_session_token_value(self) -> Optional[str]:
        if not self.aws_session_token:
            return None
        return self.aws_session_token.get_secret_value().strip()

    @property
    def is_s3_storage(self) -> bool:
        return self.media_storage_backend.strip().lower() == "s3"

    @property
    def s3_base_url(self) -> Optional[str]:
        if self.s3_public_base_url:
            return self.s3_public_base_url.rstrip("/")

        if not self.s3_bucket_name:
            return None

        return (
            f"https://{self.s3_bucket_name}.s3."
            f"{self.s3_region}.amazonaws.com"
        )

    @property
    def media_root_path(self) -> Path:
        media_root = Path(self.media_root)

        if media_root.is_absolute():
            return media_root

        return ROOT_DIR / media_root

    @property
    def cors_origins(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]

        return [
            origin.strip()
            for origin in self.cors_allow_origins.split(",")
            if origin.strip()
        ]

    @property
    def async_db_url(self) -> str:
        url = self.database_url.strip()

        if url.startswith("postgresql+asyncpg://"):
            return url

        if url.startswith("postgresql+psycopg2://"):
            return url.replace(
                "postgresql+psycopg2://",
                "postgresql+asyncpg://",
                1,
            )

        if url.startswith("postgresql://"):
            return url.replace(
                "postgresql://",
                "postgresql+asyncpg://",
                1,
            )

        return url

    @property
    def sync_db_url(self) -> str:
        return self.async_db_url.replace(
            "postgresql+asyncpg://",
            "postgresql+psycopg2://",
            1,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
