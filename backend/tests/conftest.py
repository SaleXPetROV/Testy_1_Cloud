"""Shared conftest for backend tests.

Ensures the backend module directory is on sys.path so tests can `import promo_service`,
`import telegram_bot`, etc. without depending on a PYTHONPATH env override.
"""
import os
import sys

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


# ── pymongo >= 4.18 passes `sort=` to bulk update builders; mongomock (test-only fake DB)
#    does not accept it yet. Accept and ignore it so the test DB behaves like MongoDB.
try:
    import inspect as _inspect
    from mongomock.collection import BulkOperationBuilder as _BOB
    for _name in ("add_update", "add_replace"):
        _orig = getattr(_BOB, _name, None)
        if _orig and "sort" not in _inspect.signature(_orig).parameters:
            def _wrap(orig):
                def f(self, *a, sort=None, **k):
                    return orig(self, *a, **k)
                return f
            setattr(_BOB, _name, _wrap(_orig))
except Exception:  # pragma: no cover
    pass
