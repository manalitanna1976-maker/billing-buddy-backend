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
    # Comma-separated list of Fernet keys, newest first. One key is the common
    # case; a second (old) key is kept during rotation so ciphertext written
    # under it still decrypts until it has all been re-encrypted. See
    # app/security_crypto.py.
    secret_encryption_key: str

    # --- WhatsApp invoice-drafting feature ---
    anthropic_api_key: str
    whatsapp_app_secret: str          # Meta app secret, for X-Hub-Signature-256
    whatsapp_verify_token: str        # the GET-handshake token
    whatsapp_api_version: str = "v21.0"
    whatsapp_graph_base_url: str = "https://graph.facebook.com"
    whatsapp_parser_model: str = "claude-sonnet-5"
    whatsapp_message_max_bytes: int = 2048
    whatsapp_rate_per_sender: int = 20            # per 15 min
    whatsapp_rate_per_business: int = 100         # per 15 min
    whatsapp_job_max_attempts: int = 5
    whatsapp_job_stale_claim_seconds: int = 300
    whatsapp_conversation_ttl_minutes: int = 30
    deadletter_webhook_url: str | None = None

    @field_validator("secret_encryption_key")
    @classmethod
    def _validate_fernet_keys(cls, v: str) -> str:
        from cryptography.fernet import Fernet

        keys = [k.strip() for k in v.split(",") if k.strip()]
        if not keys:
            raise ValueError("SECRET_ENCRYPTION_KEY must hold at least one Fernet key")
        for k in keys:
            Fernet(k.encode())  # raises ValueError on a malformed key -> app won't start
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
