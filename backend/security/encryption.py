"""
Salt generation for the client-side key derivation flow (PROJECT_CONTEXT.md
§4).

This module never touches a payslip value. Payslip encryption is AES-256-GCM,
done entirely in the browser via Web Crypto API, keyed from a PBKDF2
derivation the server can't reproduce — the salt below is the only piece of
that process the server holds.

(A server-side Fernet-encryption helper used to live here too, for a
"server-owned secret that needs encryption at rest" case — e.g. a cached
third-party token — that never actually arose. Removed as dead code during
a codebase review: nothing in the app called it, and speculative
infrastructure for a need that hasn't materialized is better re-added if
and when it actually does, not carried indefinitely on the chance it might.)
"""

import os

SALT_BYTES = 16


def generate_salt() -> bytes:
    """One salt per user, issued once at registration (POST /auth/register).
    The client derives its AES-256-GCM key from this salt + the user's
    password via PBKDF2 (100,000 iterations, SHA-256) on every login. The
    server stores only the salt — never the derived key, never a plaintext
    payslip value.
    """
    return os.urandom(SALT_BYTES)
