# lib/rate_limit.py — Simple in-memory rate limiter
# 30 requests per minute per API key

import time

WINDOW_SECONDS = 60
MAX_REQUESTS = 30

# Dict: api_key -> {"count": int, "reset_time": float}
_store: dict[str, dict] = {}


def check_rate_limit(api_key: str) -> dict:
    """
    Check rate limit for a given key.
    Returns {"allowed": bool, "remaining": int}.
    """
    now = time.time()
    entry = _store.get(api_key)

    # Create or reset entry if window expired
    if not entry or now > entry["reset_time"]:
        entry = {"count": 0, "reset_time": now + WINDOW_SECONDS}
        _store[api_key] = entry

    entry["count"] += 1

    if entry["count"] > MAX_REQUESTS:
        return {"allowed": False, "remaining": 0}

    return {"allowed": True, "remaining": MAX_REQUESTS - entry["count"]}

