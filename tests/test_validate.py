"""src.validate 单元测试（unittest.TestCase 风格，零依赖）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.validate import validate_script


class TestCleanScript(unittest.TestCase):
    def test_no_warnings(self):
        meta = {"series_slug": "foo", "episode": 1, "format": "solo"}
        body = "[host] 你好，这是测试。"
        self.assertEqual(validate_script(meta, body), [])


class TestDetects(unittest.TestCase):
    def setUp(self):
        self.meta = {"series_slug": "x", "episode": 1}

    def test_emoji(self):
        warns = validate_script(self.meta, "[host] 含 emoji 🎉 一处")
        self.assertTrue(any("emoji" in w for w in warns))

    def test_zero_width(self):
        warns = validate_script(self.meta, "[host] 含\u200b零宽")
        self.assertTrue(any("零宽" in w for w in warns))

    def test_markdown_bold(self):
        warns = validate_script(self.meta, "[host] 含 **加粗** 一处")
        self.assertTrue(any("加粗" in w for w in warns))

    def test_markdown_link(self):
        warns = validate_script(self.meta, "[host] 含 [link](http://x) 一处")
        self.assertTrue(any("链接" in w for w in warns))

    def test_long_body(self):
        body = "[host] " + "x" * 12000
        warns = validate_script(self.meta, body)
        self.assertTrue(any("过长" in w for w in warns))

    def test_missing_role_tag(self):
        warns = validate_script(self.meta, "一段没有角色标签的文字")
        self.assertTrue(any("角色标签" in w for w in warns))

    def test_missing_meta_field(self):
        warns = validate_script({}, "[host] 文本")
        self.assertTrue(any("series_slug" in w for w in warns))
        self.assertTrue(any("episode" in w for w in warns))


if __name__ == "__main__":
    unittest.main()