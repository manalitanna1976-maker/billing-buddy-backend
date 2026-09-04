from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet

from app.config import get_settings


@lru_cache
def _fernet() -> MultiFernet:
    # SECRET_ENCRYPTION_KEY is a comma-separated list of Fernet keys, newest
    # first. MultiFernet encrypts with the first key and, on decrypt, tries
    # each key in turn -- so a key is rotated by prepending the new one and
    # keeping the old until every stored ciphertext has been re-encrypted
    # (e.g. `MultiFernet.rotate`), with no flag-day data migration.
    keys = [k.strip() for k in get_settings().secret_encryption_key.split(",") if k.strip()]
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
