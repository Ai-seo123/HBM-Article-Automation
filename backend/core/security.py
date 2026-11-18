"""
Security module for Espial Article Publishing.

Implements:
1. PBKDF2-HMAC-SHA256 password hashing (OWASP recommended 600,000 iterations).
2. Fernet AES-128-CBC + HMAC-SHA256 token encryption using mandatory persistent TOKEN_ENCRYPTION_KEY.
3. Cryptographically secure session ID and CSRF token generation / validation.
"""

import hashlib
import hmac
import logging
import os
import secrets
from cryptography.fernet import Fernet
from core.config import settings

log = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 600_000
PBKDF2_ALGORITHM = "sha256"
SALT_BYTES = 32


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with 600,000 iterations and 32-byte salt."""
    if not password:
        raise ValueError("Password cannot be empty.")
    salt = os.urandom(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2:{PBKDF2_ALGORITHM}:{PBKDF2_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against stored PBKDF2 hash using constant-time comparison."""
    if not plain_password or not hashed_password:
        return False
    try:
        header, salt_hex, hash_hex = hashed_password.split("$")
        algo_name, iters_str = header.split(":")[1], header.split(":")[2]
        iterations = int(iters_str)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)

        derived = hashlib.pbkdf2_hmac(
            algo_name,
            plain_password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(derived, expected_hash)
    except Exception as exc:
        log.warning("Password verification failed with error: %s", exc)
        return False


def _get_fernet() -> Fernet:
    """
    Get configured Fernet instance using persistent TOKEN_ENCRYPTION_KEY.
    Strictly fails if TOKEN_ENCRYPTION_KEY is missing or invalid.
    Never generates ephemeral keys.
    """
    key = settings.TOKEN_ENCRYPTION_KEY.strip() if settings.TOKEN_ENCRYPTION_KEY else ""
    if not key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not configured in environment. "
            "Cannot perform secure token operations. Plaintext token storage is prohibited."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Invalid TOKEN_ENCRYPTION_KEY format in environment: {exc}. Must be 32 URL-safe base64-encoded bytes."
        )


def encrypt_token(plain_token: str) -> str:
    """Encrypt OAuth token to ciphertext string using Fernet."""
    if not plain_token:
        return ""
    fernet = _get_fernet()
    return fernet.encrypt(plain_token.encode("utf-8")).decode("utf-8")


def decrypt_token(cipher_token: str) -> str:
    """Decrypt OAuth ciphertext string back to plaintext token using Fernet."""
    if not cipher_token:
        return ""
    fernet = _get_fernet()
    return fernet.decrypt(cipher_token.encode("utf-8")).decode("utf-8")


def generate_session_id() -> str:
    """Generate cryptographically secure 256-bit URL-safe session token."""
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    """Generate cryptographically secure 256-bit URL-safe CSRF token."""
    return secrets.token_urlsafe(32)


def verify_csrf_token(cookie_token: str, header_token: str) -> bool:
    """Validate CSRF token using constant-time comparison."""
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token, header_token)

