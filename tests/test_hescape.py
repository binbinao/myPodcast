"""HTML 属性注入防回归（重构 P0-C）。

历史 bug：feed.py 用 `xml.sax.saxutils.escape` 默认不转义引号。
PoC：标题含 `"` → data-slug 属性被击穿，攻击者可注入 onmouseover=alert(1)。
已修复：`_hescape()` 用 `html.escape(quote=True)` 覆盖 & < > " '。
"""
from __future__ import annotations

import unittest

from src.feed import _hescape


class HescapeTest(unittest.TestCase):
    def test_ampersand(self) -> None:
        self.assertEqual(_hescape("a & b"), "a &amp; b")

    def test_lt_gt(self) -> None:
        self.assertEqual(_hescape("<script>"), "&lt;script&gt;")

    def test_double_quote(self) -> None:
        # 关键：属性场景下，标题里出现双引号必须转义为 &quot;
        # PoC: data-slug="abc" onmouseover="alert(1)"
        self.assertEqual(_hescape('abc" onmouseover="alert(1)'), "abc&quot; onmouseover=&quot;alert(1)")

    def test_single_quote(self) -> None:
        self.assertEqual(_hescape("it's"), "it&#x27;s")

    def test_none(self) -> None:
        self.assertEqual(_hescape(None), "")

    def test_int(self) -> None:
        self.assertEqual(_hescape(123), "123")

    def test_no_special_chars(self) -> None:
        self.assertEqual(_hescape("工程师电台"), "工程师电台")


if __name__ == "__main__":
    unittest.main()