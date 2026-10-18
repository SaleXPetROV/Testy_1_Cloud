"""Unified translation service.

Provider selection:
  • If LIBRETRANSLATE_URL is configured → use the self-hosted LibreTranslate
    server (free, no per-request cost).
  • Otherwise (or if LibreTranslate is unreachable) → fall back to the Emergent
    universal LLM key so translation never hard-fails.

All 9 project languages share ISO-639-1 codes that LibreTranslate understands
directly: ru, en, es, zh (sent as zh-Hans), fr, de, ja, ko, id.
"""
import os
import re
import uuid
import logging

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Supported project languages -> English names (used by the LLM fallback prompt).
CHAT_LANGS = {
    "ru": "Russian", "en": "English", "es": "Spanish", "zh": "Chinese (Simplified)",
    "fr": "French", "de": "German", "ja": "Japanese", "ko": "Korean", "id": "Indonesian",
}


async def _translate_libre(text: str, target_lang: str, source_lang: str) -> str:
    """Translate via a self-hosted LibreTranslate server."""
    url = (os.environ.get("LIBRETRANSLATE_URL") or "").rstrip("/")
    # LibreTranslate/Argos expects "zh-Hans" for Chinese; the project uses "zh".
    _code = lambda c: "zh-Hans" if c == "zh" else c
    payload = {
        "q": text,
        "source": _code(source_lang) if source_lang and source_lang != "auto" else "auto",
        "target": _code(target_lang),
        "format": "html" if "<" in text else "text",
    }
    api_key = os.environ.get("LIBRETRANSLATE_API_KEY")
    if api_key:
        payload["api_key"] = api_key
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{url}/translate", json=payload)
        r.raise_for_status()
        data = r.json()
        return (data.get("translatedText") or "").strip()


async def _translate_emergent(text: str, target_lang: str) -> str:
    """Fallback translation via the Emergent universal LLM key."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Translation is not configured")
    target_name = CHAT_LANGS.get(target_lang, target_lang)
    chat = LlmChat(
        api_key=key,
        session_id=f"translate-{uuid.uuid4()}",
        system_message=(
            f"You are a translation engine. Translate the user's message into {target_name}. "
            "Output ONLY the translated text — no quotes, no explanations, no notes, "
            "no language labels. Preserve emojis and line breaks."
        ),
    ).with_model("openai", "gpt-5.4-mini")
    result = await chat.send_message(UserMessage(text=text))
    return (result or "").strip()


async def translate_text(text: str, target_lang: str, source_lang: str = "auto") -> str:
    """Translate `text` into `target_lang`. Returns ONLY the translated string.

    Uses LibreTranslate when LIBRETRANSLATE_URL is set; on any error it falls
    back to the Emergent LLM so a temporarily-down LibreTranslate never breaks
    chat/support translation.
    """
    if not text or not text.strip():
        return ""
    if os.environ.get("LIBRETRANSLATE_URL"):
        try:
            out = await _translate_libre(text, target_lang, source_lang)
            if out:
                return out
        except Exception as e:  # noqa: BLE001 — fall back gracefully
            logger.warning(f"LibreTranslate failed ({e}); falling back to Emergent LLM")
    return await _translate_emergent(text, target_lang)


PROJECT_LANGS = ["en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id"]

_PROTECT_RE = re.compile(r"\{\{[^{}]+\}\}|\{[^{}]+\}|%[sd]|\$CITY|GRAM[ -]?City|\bTON\b|https?://\S+")
_RESTORE_RE = re.compile(r'<b\s+data-p="(\d+)"\s*(?:/>|>\s*</b>)')


def libretranslate_configured() -> bool:
    return bool(os.environ.get("LIBRETRANSLATE_URL"))


async def translate_libre_protected(text: str, target_lang: str, source_lang: str = "en") -> str:
    """LibreTranslate ONLY (no LLM fallback), with placeholders protected.

    {amount}, {{x}}, %s, $CITY, TON, GRAM City and URLs are swapped for empty
    tags before translation and put back afterwards. Raises ValueError if the
    engine dropped any of them, so callers never store a broken string.
    """
    if not text or not text.strip():
        return ""
    if not libretranslate_configured():
        raise RuntimeError("LIBRETRANSLATE_URL is not set")
    tokens = []

    def _sub(m):
        tokens.append(m.group(0))
        return f'<b data-p="{len(tokens) - 1}"></b>'

    protected = _PROTECT_RE.sub(_sub, text).replace("\n", '<br data-nl="1">')
    out = await _translate_libre(protected, target_lang, source_lang)
    seen = set()

    def _back(m):
        i = int(m.group(1))
        if i >= len(tokens) or i in seen:
            raise ValueError("placeholder duplicated")
        seen.add(i)
        return tokens[i]

    out = _RESTORE_RE.sub(_back, out)
    out = re.sub(r'<br\s+data-nl="1"\s*/?>', "\n", out).strip()
    if len(seen) != len(tokens) or "data-p=" in out or "data-nl=" in out or not out:
        raise ValueError("placeholder lost in translation")
    return out


def translation_configured() -> bool:
    return bool(os.environ.get("LIBRETRANSLATE_URL") or os.environ.get("EMERGENT_LLM_KEY"))


async def translate_cached(db, text: str, target_lang: str, source_lang: str = "auto") -> str:
    """Перевод с кэшем в Mongo (translation_cache). При любой ошибке — исходный текст."""
    if not text or not text.strip() or not translation_configured():
        return text
    import hashlib
    key = hashlib.sha1(f"{target_lang}|{text}".encode("utf-8")).hexdigest()
    try:
        hit = await db.translation_cache.find_one({"_id": key}, {"text": 1})
        if hit and hit.get("text"):
            return hit["text"]
    except Exception:
        pass
    try:
        out = await translate_text(text, target_lang, source_lang)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"translate_cached failed: {e}")
        return text
    if not out:
        return text
    try:
        from datetime import datetime, timezone
        await db.translation_cache.update_one(
            {"_id": key},
            {"$set": {"text": out, "lang": target_lang, "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    except Exception:
        pass
    return out


async def translate_html_preserving(db, html: str, target_lang: str, source_lang: str = "ru") -> str:
    """Translate the TEXT inside an HTML string while leaving every tag (and,
    crucially, embedded <img src="data:..."> pictures) completely untouched.

    We split the markup into tag / text chunks and translate ONLY the text
    chunks (via the cached translator). This keeps images and formatting
    (<b>/<i>/<u>/<span style=color>) intact and never sends a huge base64 data
    URI to the translation backend — perfect for the admin-authored game rules.
    """
    if not html or not html.strip():
        return html
    if not target_lang or target_lang == source_lang:
        return html
    parts = re.split(r'(<[^>]+>)', html)
    out = []
    for p in parts:
        if not p:
            continue
        if p.startswith('<') and p.endswith('>'):
            out.append(p)  # tag (incl. <img> with data-URI) — keep verbatim
            continue
        if not p.strip():
            out.append(p)  # whitespace-only — keep spacing
            continue
        # Preserve leading/trailing whitespace so words next to inline tags
        # (<b>, <span>, <img>) don't get glued together after translation.
        m = re.match(r'^(\s*)(.*?)(\s*)$', p, re.DOTALL)
        lead, core, trail = (m.group(1), m.group(2), m.group(3)) if m else ('', p, '')
        try:
            tr = await translate_cached(db, core, target_lang, source_lang)
        except Exception:  # noqa: BLE001
            tr = core
        out.append(f"{lead}{tr or core}{trail}")
    return ''.join(out)


def script_language(text: str) -> str | None:
    """Return the language implied by the text's script when it is unambiguous
    for our 8-language set (Cyrillic→ru, Hangul→ko, Kana→ja, Han-only→zh).
    Returns None for Latin/empty text (needs statistical detection)."""
    if not text or not text.strip():
        return None
    t = text
    if re.search(r'[\u0400-\u04FF]', t):
        return "ru"
    if re.search(r'[\uAC00-\uD7A3]', t):
        return "ko"
    if re.search(r'[\u3040-\u30FF]', t):
        return "ja"
    if re.search(r'[\u4E00-\u9FFF]', t):
        return "zh"
    return None


def detect_language(text: str) -> str | None:
    """Best-effort detection of a message's language, mapped to the project's
    8 supported languages. Offline & fast (no external service needed):

    • Script shortcuts are 100% reliable for our language set (Cyrillic→ru,
      Hangul→ko, Kana→ja, Han-only→zh).
    • Latin text is disambiguated among en/es/fr/de via `langdetect`.
    Returns a 2-letter code from CHAT_LANGS, or None if the text is empty.
    """
    if not text or not text.strip():
        return None
    scripted = script_language(text)
    if scripted:
        return scripted
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
        code = detect(text.strip())
        if code in CHAT_LANGS:
            return code
        if code in ("ca", "gl"):                # Catalan/Galician ~ Spanish
            return "es"
    except Exception:
        pass
    return "en"  # default for Latin-script text we can't pin down

