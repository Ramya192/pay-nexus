"""
Salt generation for the client-side key derivation flow (PROJECT_CONTEXT.md
§4), plus a thin Fernet wrapper for anything the *server itself* needs to
encrypt at rest.

This module never touches a payslip value. Payslip encryption is AES-256-GCM,
done entirely in the browser via Web Crypto API, keyed from a PBKDF2
derivation the server can't reproduce — the salt below is the only piece of
that process the server holds. Fernet here is a separate, unrelated need:
anything server-owned that should be encrypted at rest (e.g. a cached
third-party token), which so far nothing in the codebase actually uses.
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet

from config import config

SALT_BYTES = 16


def generate_salt() -> bytes:
    """One salt per user, issued once at registration (POST /auth/register).
    The client derives its AES-256-GCM key from this salt + the user's
    password via PBKDF2 (100,000 iterations, SHA-256) on every login. The
    server stores only the salt — never the derived key, never a plaintext
    payslip value.
    """
    return os.urandom(SALT_BYTES)


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not config.JWT_SECRET_KEY:
            raise RuntimeError(
                "JWT_SECRET_KEY is not set — it also seeds this module's server-side Fernet key."
            )
        # Fernet needs a 32-byte urlsafe-base64 key; derive one deterministically
        # from the existing secret rather than requiring a second env var to manage.
        derived = base64.urlsafe_b64encode(hashlib.sha256(config.JWT_SECRET_KEY.encode()).digest())
        _fernet = Fernet(derived)
    return _fernet


def encrypt_server_side(plaintext: bytes) -> bytes:
    """For server-owned secrets that need encryption at rest — not the
    payslip flow, which arrives pre-encrypted from the browser and stays
    that way (see db/models.py PayslipSnapshot/SessionSummary)."""
    return _get_fernet().encrypt(plaintext)


def decrypt_server_side(ciphertext: bytes) -> bytes:
    return _get_fernet().decrypt(ciphertext)
