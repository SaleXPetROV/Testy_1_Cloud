"""F37: Honeytoken / canary endpoints.

These paths look like juicy admin/backup routes but expose no real data. Any
request to them is almost certainly reconnaissance or a breach in progress, so
we log a high-visibility SECURITY ALERT (IP, UA, path) to the server log. They
always return a bland 404-like payload so a scanner can't tell they are traps.

No external services, no secrets — pure server-side logging as requested.
"""
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("honeytokens")

honeytokens_router = APIRouter(prefix="/api/admin", tags=["honeytokens"])

_TRAP_PATHS = [
    "/backup-download",
    "/db-dump",
    "/users/export.csv",
    "/secrets",
]


def _alert(request: Request, name: str):
    client_ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else "unknown"
    )
    ua = request.headers.get("user-agent", "unknown")
    logger.warning(
        "🍯 SECURITY ALERT honeytoken hit name=%s ip=%s ua=%s path=%s",
        name, client_ip, ua, request.url.path,
    )


async def _trap(request: Request):
    _alert(request, request.url.path.rsplit("/", 1)[-1])
    # Look like a boring not-found so scanners don't flag it as interesting.
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


for _p in _TRAP_PATHS:
    honeytokens_router.add_api_route(_p, _trap, methods=["GET", "POST"], include_in_schema=False)
