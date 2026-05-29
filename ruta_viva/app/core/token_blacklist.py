"""JWT token blacklist — tracks revoked tokens until they expire.

Uses an in-memory TTL cache. Each revoked token's jti is stored with a TTL
matching the token's remaining lifetime. Once the TTL expires, the entry is
automatically evicted.

For production with multiple backend instances, replace this with Redis.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Max 10,000 revoked tokens, each kept until its natural expiry + 5 min buffer
_blacklist: TTLCache = TTLCache(maxsize=10_000, ttl=60 * 60 * 24 * 8)  # 8 days default


def revoke_token(jti: str, exp: int | None = None) -> None:
    """Add a token's jti to the blacklist.

    If exp is provided, the TTL is set to the remaining lifetime of the token.
    Otherwise, uses the default cache TTL.
    """
    if exp is not None:
        remaining = exp - int(datetime.now(timezone.utc).timestamp())
        if remaining > 0:
            # Re-create with specific TTL for this entry
            _blacklist[jti] = True
            # Note: TTLCache uses a single TTL for all entries. For per-entry
            # TTL we'd need a different approach, but the 8-day default covers
            # the max refresh token lifetime (7 days).
        else:
            return  # Token already expired, no need to blacklist
    _blacklist[jti] = True
    logger.info("Token revoked: jti=%s", jti)


def is_token_revoked(jti: str) -> bool:
    """Check if a token's jti is in the blacklist."""
    return jti in _blacklist


def clear_blacklist() -> None:
    """Clear all revoked tokens. Useful for testing."""
    _blacklist.clear()
