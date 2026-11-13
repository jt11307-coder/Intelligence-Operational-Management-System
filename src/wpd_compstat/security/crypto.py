"""File and field encryption. Keys are derived or random. Nothing here is a fixed key."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from wpd_compstat.constants import AAD_CHECK, AAD_DEK, AAD_FILE, FILE_MAGIC, KEY_CHECK_PLAINTEXT
from wpd_compstat.errors import CryptoError


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64d(text: str) -> bytes:
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except Exception as exc:
        raise CryptoError("A stored cryptographic value is unreadable.") from exc


def derive_key(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    if not password:
        raise CryptoError("A password is required.")
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)


def encrypt_bytes(key: bytes, data: bytes, aad: bytes) -> bytes:
    if len(key) != 32:
        raise CryptoError("Encryption key length is invalid.")
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, data, aad)
    return FILE_MAGIC + nonce + ciphertext


def decrypt_bytes(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(key) != 32 or not blob.startswith(FILE_MAGIC) or len(blob) < len(FILE_MAGIC) + 12 + 16:
        raise CryptoError("The encrypted data could not be opened.")
    offset = len(FILE_MAGIC)
    nonce = blob[offset : offset + 12]
    ciphertext = blob[offset + 12 :]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except Exception as exc:
        raise CryptoError("The encrypted data could not be opened.") from exc


def encrypt_field(dek: bytes, field_name: str, text: str) -> str:
    aad = b"field:" + field_name.encode("utf-8")
    return b64e(encrypt_bytes(dek, text.encode("utf-8"), aad))


def decrypt_field(dek: bytes, field_name: str, stored: str) -> str:
    aad = b"field:" + field_name.encode("utf-8")
    return decrypt_bytes(dek, b64d(stored), aad).decode("utf-8")


def new_dek() -> bytes:
    return os.urandom(32)


def wrap_dek(password: str, dek: bytes, n: int, r: int, p: int) -> dict:
    salt = os.urandom(16)
    kek = derive_key(password, salt, n, r, p)
    return {
        "salt": b64e(salt),
        "password_check": b64e(encrypt_bytes(kek, KEY_CHECK_PLAINTEXT, AAD_CHECK)),
        "wrapped_dek": b64e(encrypt_bytes(kek, dek, AAD_DEK)),
    }


def unwrap_dek(password: str, record: dict, n: int, r: int, p: int) -> bytes:
    kek = derive_key(password, b64d(record["salt"]), n, r, p)
    try:
        check = decrypt_bytes(kek, b64d(record["password_check"]), AAD_CHECK)
    except CryptoError as exc:
        raise CryptoError("Authentication failed.") from exc
    if check != KEY_CHECK_PLAINTEXT:
        raise CryptoError("Authentication failed.")
    try:
        dek = decrypt_bytes(kek, b64d(record["wrapped_dek"]), AAD_DEK)
    except CryptoError as exc:
        raise CryptoError("The data key could not be opened.") from exc
    if len(dek) != 32:
        raise CryptoError("The data key could not be opened.")
    return dek


def seal_file(path: Path, key: bytes, data: bytes) -> None:
    payload = encrypt_bytes(key, data, AAD_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def open_sealed_file(path: Path, key: bytes) -> bytes:
    if not path.exists():
        raise CryptoError("An encrypted file is missing.")
    return decrypt_bytes(key, path.read_bytes(), AAD_FILE)


def secure_unlink(path: Path) -> None:
    """Best-effort overwrite before unlink. SSD wear leveling can retain old copies."""
    if not path.exists() or not path.is_file():
        return
    size = path.stat().st_size
    if size:
        with path.open("r+b") as handle:
            handle.write(os.urandom(size))
            handle.flush()
            os.fsync(handle.fileno())
    path.unlink()


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
