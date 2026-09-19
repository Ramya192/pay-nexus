"""
Shared `Limiter` instance for `slowapi` rate limiting.

Split into its own module (rather than defined in api/main.py) so
api/routes/auth.py can import and apply it via `@limiter.limit(...)`
without api/main.py and api/routes/auth.py importing each other.

Added 2026-09-13 after a security pass found /auth/login and
/auth/register had no rate limiting at all — a brute-force password
guess or a registration-spam script could hit either endpoint as fast
as the network allowed. Keyed by remote IP, which is the standard
default for this and good enough for a single-instance deployment;
a horizontally-scaled deployment behind a load balancer would need a
shared backend (Redis) instead of slowapi's in-memory default, not
a concern at this project's current scale.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
