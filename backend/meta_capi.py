"""
Meta Conversions API (CAPI) integration — server-side "Lead" tracking.

Sends a `Lead` event to the Meta dataset every time a NEW user is created in
the database (email registration, Google Auth, TON Connect).

Design (approved plan):
  • Hybrid action_source:
      - if fbp/fbc are present  -> action_source="website"          (pixel match)
      - otherwise               -> action_source="system_generated" (CRM match by
                                    IP + User-Agent + hashed email), with
                                    custom_data.event_source="crm".
  • PII (email / external_id) is SHA-256 hashed (normalized: trim + lowercase).
  • fbp / fbc are sent RAW (never hashed).
  • Fire-and-forget: any failure is swallowed and logged — it must NEVER break
    the registration flow.

Environment variables (backend/.env):
  FB_DATA_SET_ID, FB_ACCESS_TOKEN, META_CAPI_LEAD_SOURCE, META_TEST_EVENT_CODE
"""
import os
import time
import uuid
import hashlib
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v25.0"


def _sha256(value: Optional[str]) -> Optional[str]:
    """SHA-256 hash a normalized (trim + lowercase) string. None if empty."""
    if not value:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _client_ip(request) -> Optional[str]:
    """Best-effort client IP, honouring the X-Forwarded-For proxy header."""
    if request is None:
        return None
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        if request.client and request.client.host:
            return request.client.host
    except Exception:
        pass
    return None


def _client_user_agent(request) -> Optional[str]:
    if request is None:
        return None
    try:
        return request.headers.get("user-agent")
    except Exception:
        return None


async def send_capi_registration_event(user: dict, request=None, fbp: Optional[str] = None,
                                       fbc: Optional[str] = None) -> None:
    """
    Send a "Lead" event to Meta CAPI for a freshly-registered user.

    Args:
        user: the user document that was just inserted into the DB.
        request: the FastAPI/Starlette Request (for IP + User-Agent).
        fbp: Meta browser cookie `_fbp` (raw, from request body).
        fbc: Meta click cookie `_fbc` (raw, from request body).
    """
    dataset_id = os.environ.get("FB_DATA_SET_ID", "").strip()
    access_token = os.environ.get("FB_ACCESS_TOKEN", "").strip()

    if not dataset_id or not access_token:
        logger.warning("[CAPI] FB_DATA_SET_ID / FB_ACCESS_TOKEN not configured — skipping Lead event")
        return

    lead_source = os.environ.get("META_CAPI_LEAD_SOURCE", "GRAM CITY").strip() or "GRAM CITY"
    test_event_code = os.environ.get("META_TEST_EVENT_CODE", "").strip()

    # Normalise cookie values (empty string -> None)
    fbp = (fbp or "").strip() or None
    fbc = (fbc or "").strip() or None

    # ---- Build user_data ----------------------------------------------------
    user_data: dict = {}

    em = _sha256(user.get("email"))
    if em:
        user_data["em"] = [em]

    external_id = _sha256(user.get("id"))
    if external_id:
        user_data["external_id"] = [external_id]

    if fbp:
        user_data["fbp"] = fbp
    if fbc:
        user_data["fbc"] = fbc

    ip = _client_ip(request)
    if ip:
        user_data["client_ip_address"] = ip
    ua = _client_user_agent(request)
    if ua:
        user_data["client_user_agent"] = ua

    # ---- Hybrid action_source ----------------------------------------------
    has_browser_signals = bool(fbp or fbc)
    if has_browser_signals:
        action_source = "website"
        custom_data = {"lead_event_source": lead_source}
    else:
        action_source = "system_generated"
        custom_data = {"event_source": "crm", "lead_event_source": lead_source}

    event = {
        "event_name": "Lead",
        "event_time": int(time.time()),
        "event_id": str(uuid.uuid4()),  # deduplication key
        "action_source": action_source,
        "user_data": user_data,
        "custom_data": custom_data,
    }

    payload: dict = {"data": [event]}
    if test_event_code:
        payload["test_event_code"] = test_event_code

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{dataset_id}/events?access_token={access_token}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            logger.info(
                "[CAPI] Lead sent (action_source=%s, user=%s): %s",
                action_source, user.get("id"), resp.json(),
            )
        else:
            logger.warning(
                "[CAPI] Lead rejected (status=%s, user=%s): %s",
                resp.status_code, user.get("id"), resp.text,
            )
    except Exception as e:
        # Never break registration because of CAPI issues.
        logger.warning("[CAPI] Lead send failed (user=%s): %s", user.get("id"), e)
