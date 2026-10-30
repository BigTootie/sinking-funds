"""Optional end-to-end encryption for synced operation files."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b'SFENC1\n'
NONCE_BYTES = 12
SALT_BYTES = 16
KEY_BYTES = 32


class CryptoError(Exception):
    """Encrypted sync data could not be decrypted."""


class SyncCrypto:
    """AES-GCM encryption with a user-derived sync key."""

    def __init__(self, key: bytes, salt: str | None = None):
        if len(key) != KEY_BYTES:
            raise ValueError('sync key must be 32 bytes')
        self._key = key
        self.salt = salt

    @classmethod
    def from_passphrase(cls, passphrase: str, salt: str | None = None):
        if not passphrase:
            raise ValueError('sync passphrase is required')
        salt_bytes = base64.b64decode(salt) if salt else new_salt()
        key = hashlib.scrypt(
            passphrase.encode('utf-8'),
            salt=salt_bytes,
            n=2**14,
            r=8,
            p=1,
            dklen=KEY_BYTES,
        )
        return cls(key, base64.b64encode(salt_bytes).decode('ascii'))

    @classmethod
    def from_encoded_key(cls, encoded_key: str, salt: str | None = None):
        return cls(base64.b64decode(encoded_key), salt)

    def encoded_key(self) -> str:
        return base64.b64encode(self._key).decode('ascii')

    def encrypt(self, content: bytes) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(self._key).encrypt(nonce, content, MAGIC)
        return MAGIC + nonce + ciphertext

    def decrypt(self, content: bytes) -> bytes:
        if not content.startswith(MAGIC):
            raise CryptoError('encrypted sync file has an unknown format')
        nonce = content[len(MAGIC) : len(MAGIC) + NONCE_BYTES]
        ciphertext = content[len(MAGIC) + NONCE_BYTES :]
        try:
            return AESGCM(self._key).decrypt(nonce, ciphertext, MAGIC)
        except Exception as exc:
            raise CryptoError('could not decrypt sync data with this key') from exc


def new_salt() -> bytes:
    return secrets.token_bytes(SALT_BYTES)


def new_recovery_key() -> str:
    return secrets.token_urlsafe(32)
