"""Unit tests for server._tg_send_announcement — NEW spec (iter 13).

Behavior contract (image+text ALWAYS delivered together):
  (A) image=None                        → ONE send_message only.
  (B) URL image, caption≤1024, OK       → ONE send_photo (with caption),
                                          NO send_message.
  (C) URL image, caption>1024           → ONE send_message with
                                          link_preview_options
                                          {url=image, show_above_text=True}.
                                          NO send_photo (photo caption would
                                          have to be clipped; we deliver photo
                                          as a large preview above the FULL
                                          text instead).
  (D) data: URI image, long caption     → send_photo(caption='') +
                                          send_message(full text). Both parts
                                          delivered — data URIs cannot be used
                                          as a link preview.
  (E) URL image, short caption but
      send_photo ALWAYS fails           → fallback to send_message with the
                                          link_preview showing the image above
                                          the text.
Invariant: whenever image is provided, the image is delivered (either as a
photo message OR as a large link-preview attached to a send_message).
"""
import asyncio
import sys

sys.path.insert(0, "/app/backend")
from server import _tg_send_announcement  # noqa: E402


class MockBot:
    def __init__(self, photo_result=True, message_result=True,
                 photo_side_effect=None, message_side_effect=None):
        self.photo_calls = []
        self.message_calls = []
        self._photo_result = photo_result
        self._msg_result = message_result
        self._photo_side = photo_side_effect
        self._msg_side = message_side_effect

    async def send_photo(self, chat_id, photo_url, caption="",
                          parse_mode="HTML", reply_markup=None):
        call = {"chat_id": chat_id, "photo_url": photo_url, "caption": caption,
                "parse_mode": parse_mode, "reply_markup": reply_markup}
        self.photo_calls.append(call)
        if self._photo_side is not None:
            return self._photo_side(len(self.photo_calls) - 1, call)
        return self._photo_result

    async def send_message(self, chat_id, text, parse_mode="HTML",
                            reply_markup=None, link_preview_options=None):
        call = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                "reply_markup": reply_markup,
                "link_preview_options": link_preview_options}
        self.message_calls.append(call)
        if self._msg_side is not None:
            return self._msg_side(len(self.message_calls) - 1, call)
        return self._msg_result


def _run(coro):
    return asyncio.run(coro)


# (A) no image → only send_message
def test_A_no_image_text_only():
    bot = MockBot()
    ok = _run(_tg_send_announcement(bot, 111, "hello <b>world</b>", None))
    assert ok is True
    assert len(bot.photo_calls) == 0
    assert len(bot.message_calls) == 1
    assert bot.message_calls[0]["text"] == "hello <b>world</b>"


# (B) URL image + short caption + send_photo OK → single photo, no message
def test_B_url_image_short_caption_single_photo():
    bot = MockBot()
    cap = "short caption"
    ok = _run(_tg_send_announcement(bot, 222, cap, "https://x/y.png"))
    assert ok is True
    assert len(bot.photo_calls) == 1
    assert bot.photo_calls[0]["caption"] == cap
    assert bot.photo_calls[0]["photo_url"] == "https://x/y.png"
    assert len(bot.message_calls) == 0, "no separate text message when photo carries caption"


# (C) URL image + long caption → single send_message with link_preview above text
def test_C_url_image_long_caption_uses_large_link_preview():
    bot = MockBot()
    long_cap = "L" * 1500  # >1024
    img = "https://cdn/example/big.png"
    ok = _run(_tg_send_announcement(bot, 333, long_cap, img))
    assert ok is True
    # No sendPhoto with a clipped caption
    assert len(bot.photo_calls) == 0, f"photo must NOT be sent with clipped caption; calls={bot.photo_calls}"
    assert len(bot.message_calls) == 1
    msg = bot.message_calls[0]
    assert msg["text"] == long_cap, "full caption must be preserved (not clipped)"
    lpo = msg["link_preview_options"]
    assert isinstance(lpo, dict), "must attach link_preview_options"
    assert lpo.get("url") == img
    assert lpo.get("show_above_text") is True


# (D) data: URI image + long caption → send_photo(no caption) + send_message(full text)
def test_D_data_uri_image_long_caption_photo_plus_text():
    bot = MockBot()
    long_cap = "D" * 2000
    data_uri = "data:image/png;base64,iVBORw0KGgo="
    ok = _run(_tg_send_announcement(bot, 444, long_cap, data_uri))
    assert ok is True
    assert len(bot.photo_calls) == 1
    assert bot.photo_calls[0]["photo_url"] == data_uri
    assert bot.photo_calls[0]["caption"] == "", "photo caption must be empty for data URI fallback"
    assert len(bot.message_calls) == 1
    assert bot.message_calls[0]["text"] == long_cap


# (E) URL image + short caption + send_photo ALWAYS fails → send_message with link_preview
def test_E_url_image_short_caption_photo_all_fail_fallback_to_preview():
    def photo_fail(i, call):
        return False
    bot = MockBot(photo_side_effect=photo_fail)
    cap = "short caption"
    img = "https://cdn/example/tiny.png"
    ok = _run(_tg_send_announcement(bot, 555, cap, img))
    assert ok is True
    # send_message must be invoked as fallback, with link_preview above text
    assert len(bot.message_calls) >= 1
    lpo = bot.message_calls[0]["link_preview_options"]
    assert isinstance(lpo, dict) and lpo.get("url") == img and lpo.get("show_above_text") is True


# Invariant: image always delivered somehow
def test_invariant_image_always_delivered():
    scenarios = [
        ("short", "https://i/1.png"),
        ("L" * 1200, "https://i/2.png"),
        ("L" * 5000, "https://i/3.png"),
        ("L" * 5000, "data:image/png;base64,AAA"),
    ]
    for cap, img in scenarios:
        bot = MockBot()
        _run(_tg_send_announcement(bot, 999, cap, img))
        # Either a send_photo call OR a send_message with link_preview_options
        delivered_via_photo = len(bot.photo_calls) >= 1
        delivered_via_preview = any(
            (mc.get("link_preview_options") or {}).get("url") == img
            for mc in bot.message_calls
        )
        assert delivered_via_photo or delivered_via_preview, \
            f"image lost for caption len={len(cap)}, img={img[:30]}"
