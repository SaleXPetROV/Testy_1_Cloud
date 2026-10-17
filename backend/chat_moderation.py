"""F40 (remainder) — lightweight, dependency-free chat moderation.

No external API (per user's choice): a word/phrase blocklist covering profanity
and the most common crypto-scam / phishing lures, plus a simple auto-mute after
repeated violations. Everything is in-memory and self-contained so it deploys via
git with zero server/config changes.
"""
import re
import time
import os
from collections import defaultdict

# --- Blocklist -------------------------------------------------------------
# Phrases are matched case-insensitively; word-boundary where it makes sense.
# Focus: scam/phishing lures that endanger players' wallets + basic profanity.
_SCAM_PATTERNS = [
    r"seed\s*phrase", r"secret\s*phrase", r"recovery\s*phrase", r"mnemonic",
    r"private\s*key", r"приватн\w*\s*ключ", r"сид[\s-]*фраз\w*", r"мнемоник\w*",
    r"send\s+\d+\s*ton", r"отправь\w*\s+\d+\s*ton", r"double\s+your\s+ton",
    r"free\s+ton\s+airdrop", r"connect\s+your\s+wallet\s+here",
    r"верифи\w*\s+кошел\w*", r"validate\s+wallet", r"claim\s+your\s+reward",
    r"t\.me/[a-z0-9_]*support", r"admin\s+dm\w*\s+you\s+first",
]
_PROFANITY = [
    r"fuck", r"shit", r"bitch", r"asshole", r"cunt",
    r"бля\w*", r"хуй\w*", r"пизд\w*", r"еба\w*", r"ебан\w*", r"сук[аи]", r"мудак\w*",
]

_SCAM_RE = re.compile("|".join(_SCAM_PATTERNS), re.IGNORECASE)
_PROFANITY_RE = re.compile("|".join(_PROFANITY), re.IGNORECASE)

# --- Auto-mute state (in-memory) ------------------------------------------
_MUTE_THRESHOLD = int(os.environ.get("CHAT_MUTE_THRESHOLD", "5"))      # violations
_MUTE_WINDOW = int(os.environ.get("CHAT_MUTE_WINDOW_SEC", "300"))       # count window
_MUTE_DURATION = int(os.environ.get("CHAT_MUTE_DURATION_SEC", "600"))   # mute length
_violations = defaultdict(list)   # user_id -> [timestamps]
_muted_until = {}                 # user_id -> epoch seconds


def is_muted(user_id: str) -> float:
    """Return remaining mute seconds (>0) if the user is currently muted, else 0."""
    if not user_id:
        return 0
    until = _muted_until.get(user_id, 0)
    remaining = until - time.time()
    return remaining if remaining > 0 else 0


def _record_violation(user_id: str) -> bool:
    """Record a violation; return True if this pushes the user into a mute."""
    if not user_id:
        return False
    now = time.time()
    hits = [t for t in _violations[user_id] if now - t < _MUTE_WINDOW]
    hits.append(now)
    _violations[user_id] = hits
    if len(hits) >= _MUTE_THRESHOLD:
        _muted_until[user_id] = now + _MUTE_DURATION
        _violations[user_id] = []
        return True
    return False


def moderate_message(content: str, user_id: str = "") -> dict:
    """Check a chat message.

    Returns dict:
      {"allowed": bool, "content": <possibly masked>, "reason": str, "muted_for": int}
    - Scam/phishing lures are BLOCKED outright (high risk to wallets).
    - Profanity is MASKED (message still sent) but counts as a violation.
    - Repeated violations trigger an auto-mute.
    """
    text = content or ""
    # Hard block: scam / phishing
    if _SCAM_RE.search(text):
        muted = _record_violation(user_id)
        return {
            "allowed": False,
            "content": text,
            "reason": "Сообщение заблокировано: похоже на фишинг/скам (никогда не делитесь seed-фразой и не переводите TON по просьбе в чате).",
            "muted_for": _MUTE_DURATION if muted else 0,
        }
    # Soft: mask profanity
    if _PROFANITY_RE.search(text):
        masked = _PROFANITY_RE.sub(lambda m: "*" * len(m.group(0)), text)
        muted = _record_violation(user_id)
        if muted:
            return {"allowed": False, "content": masked,
                    "reason": "Вы временно заглушены за повторные нарушения.",
                    "muted_for": _MUTE_DURATION}
        return {"allowed": True, "content": masked, "reason": "", "muted_for": 0}
    return {"allowed": True, "content": text, "reason": "", "muted_for": 0}
