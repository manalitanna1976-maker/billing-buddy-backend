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


def test_one_bad_key_in_the_list_is_rejected():
    from pydantic import ValidationError
    from cryptography.fernet import Fernet
    from app.config import Settings
    good = Fernet.generate_key().decode()
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://x:x@localhost/x",
            jwt_secret="y",
            secret_encryption_key=f"{good},garbage",
        )


def test_key_rotation_old_ciphertext_still_decrypts(monkeypatch):
    from cryptography.fernet import Fernet
    from app import security_crypto as sc

    k_old = Fernet.generate_key().decode()
    k_new = Fernet.generate_key().decode()

    def use_keys(value):
        monkeypatch.setattr(sc, "get_settings", lambda: type("S", (), {"secret_encryption_key": value}))
        sc._fernet.cache_clear()

    try:
        use_keys(k_old)
        legacy = sc.encrypt_secret("legacy-token")

        # rotate: new key first, old key retained
        use_keys(f"{k_new},{k_old}")
        assert sc.decrypt_secret(legacy) == "legacy-token"  # old ciphertext still readable
        fresh = sc.encrypt_secret("fresh-token")  # written under the new key

        # drop the old key: new ciphertext readable, would-be legacy is not
        use_keys(k_new)
        assert sc.decrypt_secret(fresh) == "fresh-token"
        with pytest.raises(InvalidToken):
            sc.decrypt_secret(legacy)
    finally:
        sc._fernet.cache_clear()
