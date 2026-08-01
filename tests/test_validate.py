"""src.validate 单元测试（unittest.TestCase 风格，零依赖）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.validate import has_blocking, validate_script


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
        self.assertTrue(has_blocking(warns))

    def test_zero_width(self):
        warns = validate_script(self.meta, "[host] 含\u200b零宽")
        self.assertTrue(any("零宽" in w for w in warns))
        self.assertTrue(has_blocking(warns))

    def test_markdown_bold(self):
        warns = validate_script(self.meta, "[host] 含 **加粗** 一处")
        self.assertTrue(any("加粗" in w for w in warns))
        self.assertTrue(has_blocking(warns))

    def test_markdown_link(self):
        warns = validate_script(self.meta, "[host] 含 [link](http://x) 一处")
        self.assertTrue(any("链接" in w for w in warns))
        self.assertTrue(has_blocking(warns))

    def test_markdown_quote(self):
        warns = validate_script(self.meta, "[host]\n> 引用文字")
        self.assertTrue(any("引用" in w for w in warns))
        self.assertTrue(has_blocking(warns))

    def test_long_body(self):
        body = "[host] " + "x" * 12000
        warns = validate_script(self.meta, body)
        self.assertTrue(any("过长" in w for w in warns))
        # 长 body 不应触发 blocking（heuristic 仍可工作）
        self.assertFalse(has_blocking(warns))

    def test_missing_role_tag(self):
        warns = validate_script(self.meta, "一段没有角色标签的文字")
        self.assertTrue(any("角色标签" in w for w in warns))
        # 角色标签缺失也属 heuristic 可兜底，不算 blocking
        self.assertFalse(has_blocking(warns))

    def test_missing_meta_field(self):
        warns = validate_script({}, "[host] 文本")
        self.assertTrue(any("series_slug" in w for w in warns))
        self.assertTrue(any("episode" in w for w in warns))


# P0 新增：QA 报告里 enumerate 的 5 类 LLM 常见坏输出
class TestNewBlockRules(unittest.TestCase):
    """LLM 输出常见 BLOCK 类坏样本（commit 之后回归保护用）。"""

    def setUp(self):
        self.meta = {"series_slug": "x", "episode": 1}

    def test_code_fence(self):
        body = "[host] 这里有一段代码：\n```python\nprint(1)\n```\n结尾"
        warns = validate_script(self.meta, body)
        self.assertTrue(any("代码块" in w for w in warns))
        self.assertTrue(has_blocking(warns))

    def test_heading_residue(self):
        body = "[host] ## 这是标题残留\n正文"
        warns = validate_script(self.meta, body)
        self.assertTrue(any("标题残留" in w for w in warns))
        self.assertTrue(has_blocking(warns))

    def test_html_tag(self):
        body = "[host] 这里有 <br> 换行标签"
        warns = validate_script(self.meta, body)
        self.assertTrue(any("HTML" in w for w in warns))
        self.assertTrue(has_blocking(warns))

    def test_pipe_table(self):
        body = "[host] 这是表：\n| 列1 | 列2 |\n| --- | --- |\n完了"
        warns = validate_script(self.meta, body)
        self.assertTrue(any("pipe 表格" in w for w in warns))
        self.assertTrue(has_blocking(warns))

    def test_asterisk_italic(self):
        body = "[host] 这是 *斜体* 残留"
        warns = validate_script(self.meta, body)
        self.assertTrue(any("斜体" in w for w in warns))
        self.assertTrue(has_blocking(warns))

    def test_blocking_strictness(self):
        """纯 WARN（非 BLOCK）不应触发 has_blocking，便于 generate.py 区分。"""
        warns = validate_script(self.meta, "[host] 内容" + "x" * 12000)
        # 长 body 触发 WARN 但不 blocking
        self.assertTrue(any("过长" in w for w in warns))
        self.assertFalse(has_blocking(warns))

    def test_has_blocking_empty(self):
        self.assertFalse(has_blocking([]))


if __name__ == "__main__":
    unittest.main()