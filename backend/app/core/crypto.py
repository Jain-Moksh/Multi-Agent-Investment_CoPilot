"""
Symmetric encryption for secrets we must store and later read back
(e.g. a user's Zerodha access token).

Fernet = AES-128-CBC + HMAC-SHA256: tampered ciphertext is rejected, not
silently decrypted. The key is derived from JWT_SECRET_KEY with HKDF using a
purpose-specific label, so it is a different key from the one that signs
JWTs (no extra env variable needed). Rotating JWT_SECRET_KEY makes existing
ciphertexts unreadable; for Kite tokens that only means "reconnect Zerodha",
since they expire daily anyway.
"""

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

__all__ = ["encrypt_secret", "decrypt_secret", "InvalidToken"]


@lru_cache
def _fernet() -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"investment-copilot/broker-token-encryption/v1",
    ).derive(settings.JWT_SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Raises cryptography.fernet.InvalidToken if the data was tampered with or the key changed."""
    return _fernet().decrypt(ciphertext.encode()).decode()
