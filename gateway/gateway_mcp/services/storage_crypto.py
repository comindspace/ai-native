import os
from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet


_FERNET: Fernet | None = None

def _token_cipher() -> Fernet:
    global _FERNET
    if _FERNET is not None:
        return _FERNET

    raw = os.getenv("GATEWAY_USER_TOKEN_ENCRYPTION_KEY", "")
    if raw:
        key = raw.encode("utf-8")
    else:
        secret = os.getenv("GATEWAY_JWT_SECRET", "")
        if not secret:
            raise RuntimeError("GATEWAY_USER_TOKEN_ENCRYPTION_KEY or GATEWAY_JWT_SECRET is required for user OAuth tokens")
        key = urlsafe_b64encode(sha256(secret.encode("utf-8")).digest())
    _FERNET = Fernet(key)
    return _FERNET


def _encrypt_secret(value: str) -> str:
    return _token_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_secret(value: str) -> str:
    return _token_cipher().decrypt(value.encode("utf-8")).decode("utf-8")
