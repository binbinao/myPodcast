"""src.voicecaster 单元测试（unittest.TestCase 风格，零依赖）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.voicecaster import cast, _score_article, _load_types, DEFAULT_ARTICLE_TYPES


class TestExplicit(unittest.TestCase):
    def test_explicit_voice_wins(self):
        self.assertEqual(
            cast("任何文章", {}, explicit="explicit-voice-id"),
            "explicit-voice-id",
        )


class TestLoadTypes(unittest.TestCase):
    def test_default_keys(self):
        types = _load_types({})
        for k in DEFAULT_ARTICLE_TYPES:
            self.assertIn(k, types)

    def test_user_override(self):
        cfg = {
            "voicecaster": {
                "keywords": {"reflective": ["我的自定义词"]},
                "voices": {"reflective": ["my-voice"]},
            }
        }
        types = _load_types(cfg)
        self.assertEqual(types["reflective"]["voices"], ["my-voice"])
        self.assertIn("我的自定义词", types["reflective"]["keywords"])


class TestScoring(unittest.TestCase):
    def test_reflective_wins(self):
        text = "我意识到这件事，被碾压后的心路历程，回头看，结构本身就没给独立开发者留位置。"
        scores = _score_article(text, DEFAULT_ARTICLE_TYPES)
        self.assertGreater(scores["reflective"], 0)
        self.assertGreaterEqual(scores["reflective"], scores["tutorial"])

    def test_tutorial_wins(self):
        text = "架构设计，API 接口，协议实现，源码分析。性能测试与算法对比，步骤详细。"
        scores = _score_article(text, DEFAULT_ARTICLE_TYPES)
        self.assertGreater(scores["tutorial"], scores["casual"])


class TestCast(unittest.TestCase):
    def test_reflective_returns_audiobook(self):
        out = cast("我反思这件事，意识到被碾压后的心路历程", {})
        self.assertEqual(out, "audiobook_male_1")

    def test_empty_returns_default(self):
        cfg = {"voices_minimax": {"default": "fallback-voice"}}
        self.assertEqual(cast("", cfg), "fallback-voice")


if __name__ == "__main__":
    unittest.main()