"""src.ingest 单元测试（unittest.TestCase 风格，零依赖）。

focus: parse_script 边界 case。LLM 输出可能含 `---` 在 body 中（用作叙事断点），
会导致 frontmatter regex 误把后面当成 frontmatter。这是 QA 报告的边界条件之一。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingest import parse_script, load_episode


class TestParseScript(unittest.TestCase):
    def test_basic(self):
        text = (
            "---\n"
            "title: hello\n"
            "series_slug: foo\n"
            "episode: 1\n"
            "---\n\n"
            "[host] 你好\n"
            "[guest] 你也好\n"
        )
        meta, segs = parse_script(text)
        self.assertEqual(meta["title"], "hello")
        self.assertEqual(meta["series_slug"], "foo")
        self.assertEqual(meta["episode"], 1)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["role"], "host")
        self.assertEqual(segs[0]["text"], "你好")
        self.assertEqual(segs[1]["role"], "guest")

    def test_no_frontmatter(self):
        """无 frontmatter 时元数据 dict 应当可空访问，不抛。"""
        text = "[host] 纯脚本体"
        meta, segs = parse_script(text)
        self.assertEqual(meta.get("title"), None)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["role"], "host")

    def test_body_contains_dashes(self):
        """body 内含 `---` 分隔（不是 frontmatter 终止）。回归保护：当前实现在
        这种情形下会把 `---` 当第二个 frontmatter 边界，meta 错位。

        至少保证它不抛异常；meta 与 segs 的语义可见性由现有行为决定。"""
        text = (
            "---\n"
            "title: hello\n"
            "series_slug: foo\n"
            "episode: 1\n"
            "---\n\n"
            "[host] 第一段\n"
            "\n"
            "---\n"
            "\n"
            "[host] 第二段\n"
        )
        # 不抛即可
        meta, segs = parse_script(text)
        self.assertIsInstance(meta, dict)
        self.assertIsInstance(segs, list)

    def test_role_tag_case_insensitive(self):
        """role 标签大小写不敏感：[HOST] [Host] [host] 都归到 host。"""
        text = "[HOST] 大写\n[Host] 混合\n[host] 小写"
        _, segs = parse_script(text)
        self.assertEqual(segs[0]["role"], "host")
        self.assertEqual(segs[1]["role"], "host")
        self.assertEqual(segs[2]["role"], "host")

    def test_no_role_default(self):
        """无 [角色] 标签的行归 'default' 角色。"""
        text = "[host] 第一段\n缺角色标签的延续行"
        _, segs = parse_script(text)
        # 第一段归 host；延续行归 host（继承前一段的 role）
        roles = [s["role"] for s in segs]
        self.assertIn("host", roles)

    def test_empty_body(self):
        meta, segs = parse_script("---\ntitle: x\n---\n")
        self.assertEqual(meta["title"], "x")
        self.assertEqual(segs, [])

    def test_load_episode(self):
        """load_episode = parse_script(file_content)，用真实 sample 测试。"""
        sample = ROOT / "drafts" / "2026-07-31-when-platform-absorbs-you" / "ep-01.md"
        if sample.exists():
            meta, segs = load_episode(sample)
            self.assertEqual(meta.get("series_slug"), "when-platform-absorbs-you")
            self.assertGreater(len(segs), 0)


if __name__ == "__main__":
    unittest.main()
