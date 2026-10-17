"""
Demo (Sandbox) Guard Middleware
===============================
When the client operates in Demo mode it sends the header `X-Game-Mode: demo`
with every request. This guard hard-blocks mutating requests to REAL endpoints
(finance, P2P market, contracts/offers, credits, tutorial restart, security/2FA,
profile identity changes, wallet & telegram linking, real land purchase) so demo
activity can never touch real assets.

Demo actions have their OWN isolated endpoints under `/api/demo/*` which are
always allowed. Read-only requests (GET/HEAD) are never blocked.
"""
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Mutating requests to any of these prefixes are blocked while in demo mode.
BLOCKED_DEMO_WRITE_PREFIXES = [
    "/api/withdraw",
    "/api/transactions/withdraw",
    "/api/deposit",
    "/api/market/list",
    "/api/market/buy",
    "/api/economy/trade",
    "/api/economy/list-resource",
    "/api/trade/contract",
    "/api/trade/offer",
    "/api/contracts",
    "/api/offers",
    "/api/credit",
    "/api/loans",
    "/api/tutorial/start",
    "/api/tutorial/reset",
    "/api/tutorial/restart",
    "/api/security",
    "/api/auth/link-wallet",
    "/api/auth/unlink-wallet",
    "/api/auth/change-username",
    "/api/auth/change-email",
    "/api/auth/change-password",
    "/api/telegram/link",
    "/api/telegram/unlink",
    "/api/island/buy",
]


def _is_blocked(path: str) -> bool:
    for prefix in BLOCKED_DEMO_WRITE_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


class DemoGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            path = request.url.path
            method = request.method.upper()
            if (
                method in ("POST", "PUT", "PATCH", "DELETE")
                and path.startswith("/api/")
                and not path.startswith("/api/demo/")
            ):
                mode = (
                    request.headers.get("x-game-mode")
                    or request.headers.get("X-Game-Mode")
                    or ""
                ).lower()
                if mode == "demo" and _is_blocked(path):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "demo_mode_blocked",
                            "message": "This action is not available in demo mode.",
                        },
                    )
        except Exception as e:  # never break the request pipeline
            logger.debug(f"[demo_guard] error: {e}")
        return await call_next(request)
