"""Central configuration. All secrets come from environment variables.

Secure defaults: ENVIRONMENT defaults to "production", which means a strong
JWT secret and an explicit DATABASE_URL are REQUIRED or the app refuses to start
(fail closed).
"""
import os
from dataclasses import dataclass
from functools import lru_cache

NON_PROD = {"development", "test"}


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    jwt_secret: str
    jwt_ttl_minutes: int
    storage_dir: str
    max_upload_bytes: int
    max_rows: int
    cors_origins: tuple
    allow_real_data: bool
    login_max_attempts: int
    lockout_minutes: int

    @property
    def is_prod(self) -> bool:
        return self.environment not in NON_PROD


@lru_cache
def get_settings() -> Settings:
    env = os.environ.get("ENVIRONMENT", "production").lower()

    secret = os.environ.get("JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be set and at least 32 characters long")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        if env in NON_PROD:
            db_url = "sqlite:///./dev.db"
        else:
            raise RuntimeError("DATABASE_URL is required outside development/test")

    allow_real = os.environ.get("ALLOW_REAL_DATA", "false").lower() == "true"
    if allow_real and env in NON_PROD:
        raise RuntimeError("ALLOW_REAL_DATA must never be enabled in development/test")

    return Settings(
        environment=env,
        database_url=db_url,
        jwt_secret=secret,
        jwt_ttl_minutes=int(os.environ.get("JWT_TTL_MINUTES", "30")),
        storage_dir=os.environ.get("STORAGE_DIR", "./private_storage"),
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        max_rows=int(os.environ.get("MAX_ROWS", "100000")),
        cors_origins=tuple(
            o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        ),
        allow_real_data=allow_real,
        login_max_attempts=int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5")),
        lockout_minutes=int(os.environ.get("LOCKOUT_MINUTES", "15")),
    )
