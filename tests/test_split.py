"""src.split 单元测试（unittest.TestCase 风格，零依赖）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.split import _strip_md, plan_episodes


def _cfg():
    return {
        "split": {"min_episode_chars": 200, "max_episode_chars": 3000},
        "format": "solo",
    }


class TestPlanEpisodes(unittest.TestCase):
    def test_splits_by_h2(self):
        article = """---
title: 多章节测试
---

# 标题

引言引言引言引言引言引言引言引言引言引言引言引言引言引言引言引言引言引言引言引言。

## 章节一
内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一内容一。

## 章节二
内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二内容二。
"""
        plans = plan_episodes(article, _cfg(), "测试系列", "solo", None,
                              series_slug="test", article_date="2026-08-01")
        self.assertGreaterEqual(len(plans), 2)
        chapter_names = [p.chapter for p in plans]
        self.assertTrue(any("章节一" in c for c in chapter_names))
        self.assertTrue(any("章节二" in c for c in chapter_names))
        self.assertTrue(all(p.series_slug == "test" for p in plans))

    def test_explicit_count(self):
        """无 H2 章节时用 --- 分隔的全文，episodes 字段强制均分。"""
        article = """# T

第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容第一段内容。

---

第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容第二段内容。

---

第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容第三段内容。
"""
        plans = plan_episodes(article, _cfg(), "测试", "solo", 3,
                              series_slug="test", article_date="2026-08-01")
        self.assertEqual(len(plans), 3)
        self.assertEqual(plans[0].index, 1)
        self.assertEqual(plans[2].index, 3)

    def test_article_date_passed_through(self):
        article = """# T
content content content content content content content content content content content content content content content content content content content content content.
"""
        plans = plan_episodes(article, _cfg(), "测试", "solo", 1,
                              series_slug="x", article_date="2026-07-31")
        self.assertEqual(plans[0].article_date, "2026-07-31")


class TestStripMd(unittest.TestCase):
    """_strip_md 必须剔除水平线 `---`：残留会变成纯 `---` 段落，edge-tts 无法合成。"""

    def test_removes_hr_lines(self):
        self.assertEqual(_strip_md("开头。\n---\n结尾。"), "开头。\n结尾。")

    def test_removes_multiple_hr(self):
        self.assertEqual(_strip_md("A\n---\nB\n---\nC"), "A\nB\nC")

    def test_does_not_touch_em_dash_in_text(self):
        self.assertEqual(_strip_md("三个——破折号"), "三个——破折号")

    def test_hr_only_line_not_removed_mid_word(self):
        # 只有整行是 --- 才删；`a---b` 是内容
        self.assertEqual(_strip_md("a---b"), "a---b")


if __name__ == "__main__":
    unittest.main()