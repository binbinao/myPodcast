"""src.generate 单元测试（unittest.TestCase 风格，零依赖）。

LLM 链路兜底：`_skeleton` 必须 frontmatter 字段齐全 + body 至少含 [host]
标签；`_auto` 路径需要 key 才能跑（默认测 skip）。
"""
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.generate import _skeleton, generate_script
from src.split import EpisodePlan


def _make_plan(**overrides) -> EpisodePlan:
    base = dict(
        index=1,
        total=3,
        title="测试节目",
        series="测试节目",
        series_slug="test-show",
        chapter="第一章",
        body="第一段内容。\n\n第二段内容。",
        format="duo",
        article_date="2026-08-01",
    )
    base.update(overrides)
    return EpisodePlan(**base)


class TestSkeleton(unittest.TestCase):
    """_skeleton：无 key 路径，应产生干净骨架。"""

    def test_basic_output(self):
        plan = _make_plan()
        out = _skeleton(plan, source="raw/test.md")
        # frontmatter 必含
        self.assertIn("title:", out)
        self.assertIn("series_slug:", out)
        self.assertIn("episode: 1", out)
        self.assertIn("total: 3", out)
        self.assertIn("format: duo", out)
        self.assertIn("source:", out)
        # body 至少一个 [host] 标签
        self.assertIn("[host]", out)

    def test_solo_format(self):
        plan = _make_plan(format="solo")
        out = _skeleton(plan)
        self.assertIn("format: solo", out)

    def test_paragraphs_each_get_host(self):
        plan = _make_plan(body="段落A。\n\n段落B。\n\n段落C。")
        out = _skeleton(plan)
        # 3 段 → 3 个 [host] 行
        self.assertEqual(out.count("[host]"), 3)

    def test_body_after_pipeline_invalidates_no_role(self):
        """如果 _strip_md 把某段全洗成空，那段会被跳过（不会产出空 [host]）。"""
        plan = _make_plan(body="段落A。\n\n   \n\n段落B。")
        out = _skeleton(plan)
        # 空白段被跳过，剩 2 个 [host]
        self.assertEqual(out.count("[host]"), 2)

    def test_no_source_attr(self):
        """缺 source 参数时 frontmatter 不含 source 行（兼容旧调用）。"""
        plan = _make_plan()
        out = _skeleton(plan)
        # 没传 source → 不应有 source 行（但 plan.series_slug 应当保留）
        self.assertNotIn("source:", out)
        self.assertIn('series_slug: "test-show"', out)


class TestGenerateScript(unittest.TestCase):
    """generate_script 入口：未配 key → 走 _skeleton 路径。"""

    def test_no_key_falls_back_to_skeleton(self):
        cfg = {"llm": {"enable": True, "api_key": ""}, "format": "duo"}
        plan = _make_plan()
        out = generate_script(plan, cfg)
        # 应包含 [host]，且无 LLM 调用（这里通过缺 key 走 fallback）
        self.assertIn("[host]", out)

    def test_disabled_falls_back_to_skeleton(self):
        cfg = {"llm": {"enable": False, "api_key": "irrelevant"}, "format": "solo"}
        plan = _make_plan(format="solo")
        out = generate_script(plan, cfg)
        self.assertIn("[host]", out)
        self.assertIn("format: solo", out)

    def test_enable_with_resolvable_env(self):
        """enable=true 但 cfg.api_key="" → 用 env 兜底（如果 env 也无 → 仍走 skeleton）。"""
        import os
        for k in ("LLM_API_KEY", "MINIMAX_API_KEY", "OPENAI_API_KEY"):
            os.environ.pop(k, None)
        cfg = {"llm": {"enable": True, "api_key": ""}, "format": "duo"}
        plan = _make_plan()
        # env 全空 + api_key 空 → resolve_api_key 返回 '' → 走 skeleton
        out = generate_script(plan, cfg)
        self.assertIn("[host]", out)


if __name__ == "__main__":
    unittest.main()
