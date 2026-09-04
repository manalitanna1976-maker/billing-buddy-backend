import pytest
from cryptography.fernet import InvalidToken

from app.security_crypto import decrypt_secret, encrypt_secret


def test_round_trips():
    assert decrypt_secret(encrypt_secret("EAAG-meta-token-123")) == "EAAG-meta-token-123"


def test_ciphertext_is_not_plaintext_and_is_nondeterministic():
    a = encrypt_secret("same")
    b = encrypt_secret("same")
    assert "same" not in a
    assert a != b  # Fernet embeds a random IV


def test_tampered_token_raises():
    tok = encrypt_secret("secret")
    with pytest.raises(InvalidToken):
        decrypt_secret(tok[:-2] + ("AA" if tok[-2:] != "AA" else "BB"))


def test_malformed_encryption_key_rejected_at_settings_construction():
    from pydantic import ValidationError
    from app.config import Settings
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://x:x@localhost/x",
            jwt_secret="y",
            secret_encryption_key="not-a-valid-fernet-key",
        )
