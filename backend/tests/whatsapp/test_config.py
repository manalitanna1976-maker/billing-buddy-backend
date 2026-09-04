import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings

_REQUIRED = dict(
    database_url="postgresql+psycopg://u:p@localhost/db",
    jwt_secret="x",
    secret_encryption_key="qdEOcT2pkbVQ63tsXIEv6m5l0WILEJ_gMBWTm-_NHyE=",
    anthropic_api_key="k",
    whatsapp_app_secret="s",
    whatsapp_verify_token="t",
)


def test_parser_model_default():
    get_settings.cache_clear()
    assert get_settings().whatsapp_parser_model == "claude-sonnet-5"


def test_missing_whatsapp_app_secret_raises(monkeypatch):
    # conftest sets WHATSAPP_APP_SECRET in os.environ; drop it so the field is
    # genuinely absent for this construction.
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    monkeypatch.delenv("whatsapp_app_secret", raising=False)
    fields = {k: v for k, v in _REQUIRED.items() if k != "whatsapp_app_secret"}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **fields)


def test_all_required_fields_construct():
    s = Settings(_env_file=None, **_REQUIRED)
    assert s.whatsapp_api_version == "v21.0"
    assert s.deadletter_webhook_url is None
