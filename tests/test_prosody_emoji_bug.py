"""prosody.py emoji 正则防回归（重构 P0-G）。

历史 bug：`_EMOJI_RE` 用 `\u1F000`（4 位）→ Python 实际生成 U+0030–U+1FAF 区间，
会把英文句子里的 ASCII 字母数字全部吞掉。已修为 `\U0001F000` 8 位形式。

本测试钉死两件事：
1. ASCII 字母/数字/汉字不能被误删；
2. 真 emoji 必须仍被命中。
"""
from __future__ import annotations

import unittest

from src.prosody import _EMOJI_RE


class ProsodyEmojiRegexTest(unittest.TestCase):
    """_EMOJI_RE 必须精准命中 emoji 而不误伤 ASCII。"""

    def test_ascii_passthrough(self) -> None:
        sample = "GPT-4 的 API 在 2025 年涨价了 30%"
        cleaned = _EMOJI_RE.sub("", sample)
        self.assertEqual(
            cleaned, sample,
            f"ASCII/中文/数字不应被 _EMOJI_RE 误删，实际清理结果：{cleaned!r}",
        )

    def test_emoji_still_stripped(self) -> None:
        sample = "🎙 host 来了"
        cleaned = _EMOJI_RE.sub("", sample)
        self.assertNotIn("🎙", cleaned)
        self.assertIn("host", cleaned)

    def test_keycap_combining_mark_stripped(self) -> None:
        # 键帽 1️⃣ = U+0031 + U+20E3（数字 + 组合符）。_EMOJI_RE 单独删 U+20E3。
        sample = "1\u20e3 hello"
        cleaned = _EMOJI_RE.sub("", sample)
        self.assertNotIn("\u20e3", cleaned)
        self.assertEqual(cleaned.strip(), "1 hello")


if __name__ == "__main__":
    unittest.main()