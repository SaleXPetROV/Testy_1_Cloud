"""Monetag SDK tag pasted by the admin (Данные → Monetag) is parsed into src / zone / function."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
import ads  # noqa: E402


def test_parse_cabinet_tag():
    r = ads.parse_sdk_tag("<script src='//libtl.com/sdk.js' data-zone='10012345' data-sdk='show_10012345'></script>")
    assert r == {"sdk_src": "https://libtl.com/sdk.js", "monetag_zone_id": "10012345", "sdk_fn": "show_10012345"}


def test_parse_double_quotes_and_default_fn():
    r = ads.parse_sdk_tag('<script src="https://libtl.com/sdk.js" data-zone="777"></script>')
    assert r["sdk_fn"] == "show_777" and r["monetag_zone_id"] == "777"


@pytest.mark.parametrize("bad", ["", "10012345", "<script src='http://x.com/a.js' data-zone='1'></script>",
                                 "<script src='//libtl.com/sdk.js'></script>",
                                 "<script src='//libtl.com/sdk.js' data-zone='1' data-sdk='alert(1)'></script>"])
def test_parse_rejects_bad(bad):
    with pytest.raises(ValueError):
        ads.parse_sdk_tag(bad)
