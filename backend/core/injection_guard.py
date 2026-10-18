"""Reject JSON request bodies that contain MongoDB operators ($ne, $gt, $where …) as keys.

Legitimate clients never send keys starting with "$"; an attacker would, to turn
{"email": X} into {"email": {"$ne": null}}. Pure ASGI middleware: the body is read
once (capped), checked, and replayed to the app unchanged.
"""
import json

MAX_BODY = 2 * 1024 * 1024


def _has_operator(obj, depth=0) -> bool:
    if depth > 40:
        return True
    if isinstance(obj, dict):
        return any((isinstance(k, str) and k.startswith("$")) or _has_operator(v, depth + 1) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_has_operator(v, depth + 1) for v in obj)
    return False


class InjectionGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH", "DELETE"):
            return await self.app(scope, receive, send)
        ctype = dict(scope.get("headers") or []).get(b"content-type", b"").decode().lower()
        if "application/json" not in ctype:
            return await self.app(scope, receive, send)
        body, more = b"", True
        while more:
            msg = await receive()
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
            if len(body) > MAX_BODY:
                return await self._reject(send, 413, "Request body too large")
        try:
            data = json.loads(body) if body else None
        except ValueError:
            data = None                                   # let the app answer with its own 422
        if data is not None and _has_operator(data):
            return await self._reject(send, 400, "Invalid request")
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()
        return await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send, status, text):
        payload = json.dumps({"detail": text}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": payload})
