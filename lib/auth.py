# lib/auth.py — Validate x-api-key header

import os
from fastapi import Request


def get_api_key(request: Request) -> str | None:
    """Returns the API key from the request, or None."""
    return request.headers.get("x-api-key") or None


def is_valid_key(key: str | None) -> bool:
    """Check if a key is in the valid list."""
    if not key:
        return False
    valid = [k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()]
    return key in valid

