"""src.naming 单元测试（unittest.TestCase 风格，零依赖）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.naming import chinese_to_ascii, drafts_dir_for, ep_output_dir


class TestChineseToAscii(unittest.TestCase):
    def test_pure_chinese(self):
        out = chinese_to_ascii("用三个晚上做的小工具")
        self.assertTrue(out.isascii(), out)
        self.assertTrue(out.replace("-", "").isalnum(), out)
        self.assertEqual(out, "yong-san-ge-wan-shang-zuo-de-xiao-gong-ju")

    def test_english_passthrough(self):
        self.assertEqual(chinese_to_ascii("Hello World"), "hello-world")

    def test_mixed(self):
        out = chinese_to_ascii("工程师 podcast")
        self.assertTrue(out.startswith("gong-cheng-shi"))
        self.assertIn("podcast", out)


class TestDraftsDirFor(unittest.TestCase):
    def test_explicit_slug(self):
        self.assertEqual(
            drafts_dir_for("2026-07-31", "任何标题", "when-platform-absorbs-you"),
            "drafts/2026-07-31-when-platform-absorbs-you",
        )

    def test_fallback_to_pinyin(self):
        path = drafts_dir_for("2026-08-01", "工程师的知识管理", "")
        self.assertTrue(path.startswith("drafts/2026-08-01-"))
        self.assertIn("gong-cheng", path)


class TestEpOutputDir(unittest.TestCase):
    def test_path(self):
        self.assertEqual(
            ep_output_dir("output", "测试系列", 3, "test-slug"),
            "output/series/test-slug/ep-03",
        )


if __name__ == "__main__":
    unittest.main()