"""F20: SSRF allow-list wrapper for outbound HTTP calls.

Design goal
-----------
All outbound HTTP hosts in this backend are hard-coded (Telegram, toncenter,
tonapi, Cloudflare Turnstile, Google, Resend, TON Center). There is no place
in the code today where a user-supplied URL flows into `session.get(url)`.

But that's a discipline that's easy to break as the code grows — one review
miss and we introduce full SSRF (scan localhost, hit AWS metadata service,
etc.). This module exists so that any NEW outbound call can be routed through
a single check, and PR reviewers can grep for `safe_fetch(` to spot user-URL
sinks quickly.

Usage
-----
    from security.safe_fetch import ensure_allowed_host, ALLOWED_OUTBOUND_HOSTS

    async with aiohttp.ClientSession() as s:
        ensure_allowed_host(url)         # raises SSRFError if disallowed
        r = await s.get(url)

Adding a new host: edit `ALLOWED_OUTBOUND_HOSTS` OR set the
`SSRF_EXTRA_ALLOWED_HOSTS` env (comma-separated) at deploy time.
"""
from __future__ import annotations

import ipaddress
import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SSRFError(Exception):
    """Raised when an outbound URL points at a disallowed host."""


ALLOWED_OUTBOUND_HOSTS: set = {
    # Telegram
    "api.telegram.org",
    "telegram.org",
    # TON RPC / indexers
    "toncenter.com",
    "testnet.toncenter.com",
    "tonapi.io",
    "testnet.tonapi.io",
    # Google (OAuth / Turnstile-style verification)
    "oauth2.googleapis.com",
    "accounts.google.com",
    "www.googleapis.com",
    # Cloudflare Turnstile (bot-protection)
    "challenges.cloudflare.com",
    # Resend (transactional email)
    "api.resend.com",
}


def _load_extra_hosts() -> set:
    raw = (os.environ.get("SSRF_EXTRA_ALLOWED_HOSTS") or "").strip()
    if not raw:
        return set()
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def ensure_allowed_host(url: str) -> None:
    """Raise SSRFError if the URL is not one of our allowed outbound targets.

    Rules:
      * scheme must be http or https
      * host must be a registered domain in the allowlist, OR
        - localhost is REJECTED (even if allowlisted, block link-local)
        - IP addresses are REJECTED (blocks 169.254.169.254 AWS metadata,
          10.x/172.16-31.x/192.168.x internal networks, ::1, etc.)
    """
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise SSRFError(f"scheme not allowed: {p.scheme!r}")
    host = (p.hostname or "").lower().strip()
    if not host:
        raise SSRFError("missing host")

    # Reject raw IP addresses regardless of allowlist — legitimate outbound
    # calls should always go by DNS name.
    try:
        ip = ipaddress.ip_address(host)
        raise SSRFError(f"IP address outbound not allowed: {ip}")
    except ValueError:
        pass  # not an IP, that's fine — it's a hostname

    # Reject localhost / link-local names explicitly.
    if host in ("localhost", "ip6-localhost", "ip6-loopback"):
        raise SSRFError("localhost not allowed")

    allowed = ALLOWED_OUTBOUND_HOSTS | _load_extra_hosts()
    # exact match OR any subdomain of an allowed host (e.g. *.toncenter.com)
    for entry in allowed:
        if host == entry or host.endswith("." + entry):
            return
    raise SSRFError(f"host not in allow-list: {host}")


def is_allowed_host(url: str) -> bool:
    """Non-raising variant of ensure_allowed_host — returns bool."""
    try:
        ensure_allowed_host(url)
        return True
    except SSRFError:
        return False
