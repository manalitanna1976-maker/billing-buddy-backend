from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    upload_dir: str = "uploads"
    cors_origins: list[str] = ["http://localhost:5173"]
    secret_encryption_key: str

    @field_validator("secret_encryption_key")
    @classmethod
    def _validate_fernet_key(cls, v: str) -> str:
        from cryptography.fernet import Fernet

        Fernet(v.encode())  # raises ValueError on a malformed key -> app won't start
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
