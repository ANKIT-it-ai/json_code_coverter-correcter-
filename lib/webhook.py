# lib/webhook.py — HMAC-SHA256 signing and delivery

import hashlib
import hmac
import ipaddress
import json
import os
from urllib.parse import urlparse

import httpx


def sign_payload(payload: str) -> str:
    """Sign a payload string with HMAC-SHA256. Returns the hex digest."""
    secret = os.environ.get("WEBHOOK_SECRET") or "default-secret"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def is_safe_url(url_string: str) -> bool:
    """
    Validate that a URL is a safe http(s) URL.
    Blocks localhost, 127.x, 10.x, 192.168.x, 172.16-31.x, 0.0.0.0, ::1
    """
    try:
        parsed = urlparse(url_string)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False

        hostname = parsed.hostname.lower()

        # Block localhost and .local hostnames
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or hostname.endswith(".local"):
            return False

        # Block private / loopback / reserved IP addresses
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or ip.is_unspecified:
                return False
        except ValueError:
            # Not an IP literal (it's a domain name), which is fine
            pass

        return True
    except Exception:
        return False


async def deliver_webhook(webhook_url: str, event_payload: dict) -> dict:
    """
    Deliver a webhook event to the given URL.
    Returns {"delivered": bool, "status": int | None, "error"?: str}.
    """
    body = json.dumps(event_payload, separators=(",", ":"))
    signature = sign_payload(body)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(
                webhook_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": signature,
                },
            )
        ok = 200 <= res.status_code < 300
        return {"delivered": ok, "status": res.status_code}
    except httpx.TimeoutException:
        return {"delivered": False, "status": None, "error": "Timeout (5s)"}
    except Exception as err:
        return {"delivered": False, "status": None, "error": str(err)}

