"""系列上下文（REQ-01 / issue #3）的守护测试 —— 全程零网络。

钉住的契约（与票面验收一一对应）：

1. 节目身份来自 config.yaml 的 ``podcast:`` 块；第 1 集只介绍一次节目；
2. 系列大纲落 ``drafts/<系列>/outline.md``，首次由一次模型调用生成，之后只读
   （手改大纲 = 改下一轮的生成输入，不会被悄悄覆盖）；
3. 上一集结尾从磁盘截断注入，不额外调模型；末集不预告；
4. 分级覆盖：frozen 逐字节不变；reviewed 无 --force 不变、有 --force 才变；
5. 单集不产大纲，走旧路径（prompt 里没有系列上下文）；
6. 无 LLM key 时不崩：仍出骨架稿。
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingest import parse_script
from src.prepare import prepare_file
from src.outline import (
    OUTLINE_FILENAME,
    build_outline_prompt,
    coerce_outline,
    fingerprint,
    parse_outline,
    program_brief,
)
from src.series import compose_context, previous_tail
from src.split import EpisodePlan
from src.stages import STAGE_FROZEN, STAGE_REVIEWED, set_stage

ENV_KEYS = ("LLM_API_KEY", "MINIMAX_API_KEY", "OPENAI_API_KEY", "SCNET_API_KEY")

PODCAST = {
    "title": "测试电台",
    "author": "小搭 & 斌哥",
    "tagline": "把文章变成能听的东西。",
    "about": "这是一个用于测试的节目。\n第二行会被压平。",
}

ARTICLE_3 = """---
title: 测试系列
format: duo
voice: host=zh-CN-XiaoxiaoNeural / guest=zh-CN-YunxiNeural
split_strategy: by_h2
---
# 测试系列

## 第一章
第一章的正文内容，用来喂给模型。

## 第二章
第二章的正文内容。

## 第三章
第三章的正文内容。
"""

ARTICLE_1 = """---
title: 单片测试
format: solo
voice: zh-CN-XiaoxiaoNeural
split_strategy: by_h2
---
# 单片测试

整篇只有一段正文，不产生章节。
"""


def _plan(index: int = 1, total: int = 3, chapter: str = "第一章", body: str = "正文。") -> EpisodePlan:
    return EpisodePlan(
        index=index, total=total, title=f"测试系列 · {chapter}", series="测试系列",
        series_slug="test-series", chapter=chapter, body=body, format="duo",
        article_date="2026-01-01",
    )


def _outline_text(series: str = "测试系列", topics=("第一章要点", "第二章要点", "第三章要点")) -> str:
    lines = [f"# 系列大纲：{series}", "", "## 系列总纲", "总纲第一行。", "总纲第二行。", ""]
    for i, topic in enumerate(topics, 1):
        lines += [f"## 第 {i} 集：第{i}章", f"{topic}。与上一集的承接，给下一集的引子。", ""]
    return "\n".join(lines)


class _LLMStub:
    """记录调用次数与 system prompt 的假 LLM。"""

    def __init__(self, outline: str | None = None) -> None:
        self.outline = outline or _outline_text()
        self.outline_calls = 0
        self.gen_calls = 0
        self.systems: list[str] = []

    def outline_fn(self, system: str, user: str, cfg: dict) -> str:
        self.outline_calls += 1
        return self.outline

    def gen_fn(self, system: str, user: str, cfg: dict) -> str:
        self.gen_calls += 1
        self.systems.append(system)
        m = re.search(r"第 (\d+) 集 / 共 (\d+) 集", system)
        idx = m.group(1) if m else "?"
        return f"[host] 第{idx}集-第{self.gen_calls}次生成。"


class TestProgramBrief(unittest.TestCase):
    def test_includes_identity_fields(self) -> None:
        brief = program_brief({"podcast": PODCAST})
        self.assertIn("《测试电台》", brief)
        self.assertIn("小搭 & 斌哥", brief)
        self.assertIn("把文章变成能听的东西。", brief)
        self.assertIn("这是一个用于测试的节目。", brief)

    def test_collapses_whitespace(self) -> None:
        brief = program_brief({"podcast": PODCAST})
        self.assertNotIn("\n第二行", brief)
        self.assertIn("第二行会被压平", brief)

    def test_missing_config_returns_empty(self) -> None:
        self.assertEqual(program_brief({}), "")
        self.assertEqual(program_brief({"podcast": {}}), "")

    def test_about_is_truncated(self) -> None:
        brief = program_brief({"podcast": {"title": "T", "about": "长" * 500}})
        self.assertLess(len(brief), 300)
        self.assertTrue(brief.endswith("…"))


class TestOutlineParsing(unittest.TestCase):
    def test_summary_and_entries(self) -> None:
        outline = parse_outline(_outline_text())
        self.assertIn("总纲第一行", outline.summary)
        self.assertNotIn("# 系列大纲", outline.summary)
        self.assertEqual(len(outline.entries), 3)
        self.assertIn("第一章要点", outline.entry(1))
        self.assertEqual(outline.chapter(2), "第2章")
        self.assertEqual(outline.sha, fingerprint(_outline_text()))

    def test_topic_filters_generic_chapter(self) -> None:
        outline = parse_outline(_outline_text(topics=("要点一", "要点二", "要点三")))
        self.assertEqual(outline.topic(1), "要点一")
        # "第2部分"这种无语义章节名不能当作下一集主题
        self.assertEqual(outline.topic(9, "第2部分"), "")
        self.assertEqual(outline.topic(9, "结论"), "结论")

    def test_stub_section_is_treated_as_missing(self) -> None:
        raw = "# 系列大纲：X\n\n只有总纲。\n"
        text = coerce_outline(raw, [_plan(1), _plan(2)], "X")
        outline = parse_outline(text)
        self.assertEqual(len(outline.entries), 2)
        self.assertEqual(outline.entry(1), "")  # 占位段不当作本集论点

    def test_tolerant_entry_headings(self) -> None:
        # 人手改大纲时可能写成 "## ep-02 x" 或 "## 第3集 x"（无冒号），都要认得
        text = (
            "# 系列大纲：X\n\n## 系列总纲\n总纲。\n\n"
            "## ep-02 无冒号的第二集\n第二集要点。\n\n"
            "## 第3集 无冒号的第三集\n第三集要点。\n"
        )
        outline = parse_outline(text)
        self.assertIn("第二集要点", outline.entry(2))
        self.assertEqual(outline.chapter(2), "无冒号的第二集")
        self.assertIn("第三集要点", outline.entry(3))
        self.assertEqual(outline.chapter(3), "无冒号的第三集")

    def test_chinese_numeral_headings(self) -> None:
        # 模型常把集号写成中文数字：不能因此退化成"全占位"大纲
        text = (
            "# 系列大纲：X\n\n## 系列总纲\n总纲。\n\n"
            "## 第一集：开端\n第一集要点。\n\n"
            "## 第十二集：收束\n第十二集要点。\n"
        )
        outline = parse_outline(text)
        self.assertIn("第一集要点", outline.entry(1))
        self.assertEqual(outline.chapter(1), "开端")
        self.assertIn("第十二集要点", outline.entry(12))


class TestBuildOutlinePrompt(unittest.TestCase):
    def test_prompt_carries_identity_and_all_episodes(self) -> None:
        plans = [
            _plan(1, 3, "第一章", "第一章的正文内容，用来喂给模型。"),
            _plan(2, 3, "第二章", "第二章的正文。"),
            _plan(3, 3, "第三章", "第三章的正文。"),
        ]
        system, user = build_outline_prompt(plans, program_brief({"podcast": PODCAST}))
        self.assertIn("## 第 1 集", system)
        self.assertIn("系列总纲", system)
        self.assertIn("《测试电台》", user)
        for chapter in ("第一章", "第二章", "第三章"):
            self.assertIn(chapter, user)
        self.assertIn("第一章的正文内容", user)


class TestPreviousTail(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, index: int, body: str) -> None:
        (self.dir / f"ep-{index:02d}.md").write_text(
            f"---\ntitle: x\nepisode: {index}\n---\n\n{body}\n", encoding="utf-8"
        )

    def test_first_episode_has_no_tail(self) -> None:
        self.assertEqual(previous_tail(self.dir, 1), "")

    def test_missing_file(self) -> None:
        self.assertEqual(previous_tail(self.dir, 3), "")

    def test_strips_frontmatter_and_role_tags(self) -> None:
        self._write(1, "[host] 上一集最后一句[guest] 对。")
        tail = previous_tail(self.dir, 2)
        self.assertNotIn("title:", tail)
        self.assertNotIn("[host]", tail)
        self.assertIn("主播：", tail)

    def test_truncates_at_sentence_boundary(self) -> None:
        self._write(1, "旧内容。" * 400)
        tail = previous_tail(self.dir, 2)
        self.assertLessEqual(len(tail), 700)
        self.assertTrue(tail.startswith("…"))


class TestEpisodeContext(unittest.TestCase):
    def setUp(self) -> None:
        self.outline = parse_outline(_outline_text())
        self.brief = program_brief({"podcast": PODCAST})

    def test_first_episode_introduces_program_once(self) -> None:
        ctx = compose_context(_plan(1, 3), self.outline, self.brief, "", next_chapter="第二章")
        self.assertIn("节目身份", ctx)
        self.assertIn("系列第一集", ctx)
        self.assertIn("之后各集都不再自我介绍", ctx)
        self.assertIn("第一章要点", ctx)
        self.assertIn("第二章要点", ctx)  # 下一集主题来自大纲而非章节名

    def test_middle_episode_carries_prev_tail_and_next_topic(self) -> None:
        ctx = compose_context(_plan(2, 3), self.outline, self.brief, "上一集说到 GPU。")
        self.assertIn("上一集结尾", ctx)
        self.assertIn("上一集说到 GPU。", ctx)
        self.assertIn("第三章要点", ctx)

    def test_last_episode_has_no_preview(self) -> None:
        ctx = compose_context(_plan(3, 3), self.outline, self.brief, "上一集说到 NPU。")
        self.assertNotIn("下一集主题", ctx)
        self.assertIn("自然收束", ctx)


class TestGenerateWithSeriesContext(unittest.TestCase):
    def test_system_prompt_gets_block_and_frontmatter_gets_sha(self) -> None:
        from src.generate import generate_script

        captured: dict[str, str] = {}

        def fake_llm(system: str, user: str, cfg: dict) -> str:
            captured["system"] = system
            captured["user"] = user
            return "[host] 改写后的正文。"

        plan = _plan()
        outline = parse_outline(_outline_text())
        from src.series import SeriesContext

        ctx = SeriesContext(block="【系列上下文】测试块", outline_sha=outline.sha)
        cfg = {"llm": {"enable": True, "api_key": "stub"}}
        with patch("src.generate.llm_complete", fake_llm):
            out = generate_script(plan, cfg, series=ctx)
        self.assertIn("【系列上下文】测试块", captured["system"])
        self.assertEqual(captured["user"], plan.body)  # 本集正文仍单独作为 user
        meta, _ = parse_script(out)
        self.assertEqual(meta["series_outline_sha"], outline.sha)

    def test_legacy_prompt_unchanged_without_series(self) -> None:
        # 单集场景 / 无大纲时，system prompt 必须与改造前逐字节一致
        from src.generate import generate_script

        captured: dict[str, str] = {}

        def fake_llm(system: str, user: str, cfg: dict) -> str:
            captured["system"] = system
            return "[host] 改写后的正文。"

        cfg = {"llm": {"enable": True, "api_key": "stub"}}
        with patch("src.generate.llm_complete", fake_llm):
            generate_script(_plan(), cfg, series=None)
        self.assertEqual(
            captured["system"],
            "你是一名播客文案编辑。把下面的书面内容改写成双人对话播客稿。"
            "用 [host] 和 [guest] 交替发言，像真实聊天，有来有回、有互动。"
            "保留关键信息，去掉书面冗余。只输出脚本正文，不要解释。",
        )

        solo = EpisodePlan(
            index=1, total=1, title="单片测试", series="单片测试",
            series_slug="single", chapter="全文", body="正文。", format="solo",
            article_date="2026-01-01",
        )
        with patch("src.generate.llm_complete", fake_llm):
            generate_script(solo, cfg, series=None)
        self.assertEqual(
            captured["system"],
            "你是一名播客文案编辑。把下面的书面内容改写成自然、口语化、适合单人朗读的播客稿。"
            "全程用 [host] 标签，去掉书面冗余词，保留关键信息，适当加入过渡句。"
            "只输出脚本正文，不要解释。",
        )


class TestPrepareSeriesPipeline(unittest.TestCase):
    """prepare_file 的端到端行为（LLM 全部打桩）。"""

    def setUp(self) -> None:
        import os
        self.os = os
        self.saved_env = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.raw = self.tmp / "raw" / "2026-01-01-test-series.md"
        self.raw.parent.mkdir(parents=True)
        self.raw.write_text(ARTICLE_3, encoding="utf-8")
        self.drafts = self.tmp / "drafts"
        self.series_dir = self.drafts / "2026-01-01-test-series"
        self.stub = _LLMStub()
        self.cfg = {
            "format": "duo",
            "podcast": PODCAST,
            "split": {},
            "llm": {"enable": True, "api_key": "stub", "base_url": "http://127.0.0.1:1/v1"},
        }

    def tearDown(self) -> None:
        for k, v in self.saved_env.items():
            if v is not None:
                self.os.environ[k] = v
        self._tmp.cleanup()

    def _run(self, **kwargs):
        with patch("src.outline.llm_complete", self.stub.outline_fn), patch(
            "src.generate.llm_complete", self.stub.gen_fn
        ):
            return prepare_file(self.raw, self.cfg, self.drafts, **kwargs)

    def _eps(self) -> list[Path]:
        return sorted(self.series_dir.glob("ep-*.md"))

    def test_outline_created_once_and_reused(self) -> None:
        made = self._run()
        self.assertEqual(len(made), 3)
        outline_file = self.series_dir / OUTLINE_FILENAME
        self.assertTrue(outline_file.is_file())
        self.assertEqual(self.stub.outline_calls, 1)
        self.assertEqual(self.stub.gen_calls, 3)
        # 第二次跑：大纲已存在 → 不再调模型，只读
        self._run()
        self.assertEqual(self.stub.outline_calls, 1)

    def test_prev_tail_and_next_topic_reach_prompts(self) -> None:
        self._run()
        systems = self.stub.systems
        self.assertIn("系列第一集", systems[0])
        # ep-02 的 system 里应该有 ep-01 实际写入的结尾
        self.assertIn("主播：第1集-第1次生成。", systems[1])
        self.assertIn("第三章要点", systems[1])
        self.assertNotIn("下一集主题", systems[2])

    def test_manual_outline_edit_changes_next_run(self) -> None:
        self._run()
        outline_file = self.series_dir / OUTLINE_FILENAME
        text = outline_file.read_text(encoding="utf-8")
        outline_file.write_text(
            text.replace("第二章要点", "手工改过的第二集要点"), encoding="utf-8"
        )
        self.stub.systems.clear()
        self._run()
        self.assertEqual(self.stub.outline_calls, 1)  # 没有覆盖手改的大纲
        self.assertIn("手工改过的第二集要点", self.stub.systems[1])

    def test_stage_gated_overwrite(self) -> None:
        self._run()
        ep2, ep3 = self._eps()[1:]
        set_stage(ep2, STAGE_FROZEN)
        set_stage(ep3, STAGE_REVIEWED)
        frozen_bytes, reviewed_bytes = ep2.read_bytes(), ep3.read_bytes()

        self.stub.systems.clear()
        self.stub.gen_calls = 0
        self._run()
        self.assertEqual(self.stub.gen_calls, 1)  # 只有 ep-01 重生成
        self.assertIn("第 1 集 / 共 3 集", self.stub.systems[0])
        self.assertEqual(ep2.read_bytes(), frozen_bytes)
        self.assertEqual(ep3.read_bytes(), reviewed_bytes)

        # --force 只解锁 reviewed，frozen 永远不动
        self.stub.gen_calls = 0
        self._run(force=True)
        self.assertEqual(self.stub.gen_calls, 2)  # ep-01 + ep-03
        self.assertEqual(ep2.read_bytes(), frozen_bytes)
        self.assertNotEqual(ep3.read_bytes(), reviewed_bytes)

    def test_outline_only_touches_nothing_else(self) -> None:
        self._run()
        eps = self._eps()
        before = {p: p.read_bytes() for p in eps}
        self.stub.outline = _outline_text(topics=("新一集要点", "新二集要点", "新三集要点"))
        with patch("src.outline.llm_complete", self.stub.outline_fn), patch(
            "src.generate.llm_complete", self.stub.gen_fn
        ):
            self.assertEqual(
                prepare_file(self.raw, self.cfg, self.drafts, outline_only=True), []
            )
        self.assertIn(
            "新一集要点", (self.series_dir / OUTLINE_FILENAME).read_text(encoding="utf-8")
        )
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_single_episode_has_no_outline(self) -> None:
        self.raw.write_text(ARTICLE_1, encoding="utf-8")
        self.cfg["llm"]["api_key"] = "stub"
        self._run()
        series_dir = self.drafts / "2026-01-01-test-series"
        self.assertFalse((series_dir / OUTLINE_FILENAME).exists())
        self.assertEqual(len(self.stub.systems), 1)
        self.assertNotIn("【系列上下文】", self.stub.systems[0])

    def test_no_api_key_degrades_without_crash(self) -> None:
        self.cfg["llm"]["api_key"] = ""
        made = self._run()
        self.assertEqual(len(made), 3)
        self.assertFalse((self.series_dir / OUTLINE_FILENAME).exists())
        meta, _ = parse_script(made[0].read_text(encoding="utf-8"))
        self.assertEqual(meta["ai_stage"], "skeleton")

    def test_skeleton_still_records_outline_sha(self) -> None:
        # 大纲已存在但这次没有 key：骨架稿也要记下大纲指纹，否则"大纲换代了
        # 但某集还是旧骨架"永远无法被 prepare 察觉。
        self._run()
        outline_file = self.series_dir / OUTLINE_FILENAME
        sha = parse_outline(outline_file.read_text(encoding="utf-8")).sha
        self.cfg["llm"]["api_key"] = ""
        made = self._run()
        meta, _ = parse_script(made[0].read_text(encoding="utf-8"))
        self.assertEqual(meta["ai_stage"], "skeleton")
        self.assertEqual(meta["series_outline_sha"], sha)

    def test_outline_only_single_episode_writes_nothing(self) -> None:
        self.raw.write_text(ARTICLE_1, encoding="utf-8")
        self.assertEqual(self._run(outline_only=True), [])
        # 不写 ep-01，也不写 _decisions.json（"未改动任何文件"要字面为真；
        # 目录本身由 draft_dir_for 建，不算改动）
        self.assertEqual([p for p in self.drafts.rglob("*") if p.is_file()], [])

    def test_regenerate_outline_overwrites_manual_copy(self) -> None:
        self._run()
        outline_file = self.series_dir / OUTLINE_FILENAME
        outline_file.write_text("手工版本，不许悄悄覆盖\n", encoding="utf-8")
        self._run(regenerate_outline=True)
        self.assertEqual(self.stub.outline_calls, 2)
        self.assertNotEqual(
            outline_file.read_text(encoding="utf-8"), "手工版本，不许悄悄覆盖\n"
        )
        self.assertIn("总纲第一行", outline_file.read_text(encoding="utf-8"))

    def test_invalid_outline_keeps_manual_copy(self) -> None:
        # 模型只回 reasoning、content 为空时不能把 outline.md 写成全占位
        self._run()
        outline_file = self.series_dir / OUTLINE_FILENAME
        manual = outline_file.read_text(encoding="utf-8").replace(
            "第二章要点", "手工版第二集要点"
        )
        outline_file.write_text(manual, encoding="utf-8")
        self.stub.outline = ""
        self.stub.systems.clear()
        made = self._run(regenerate_outline=True)
        self.assertEqual(len(made), 3)  # 仍用保留的旧大纲跑生成
        self.assertEqual(outline_file.read_text(encoding="utf-8"), manual)
        self.assertIn("手工版第二集要点", self.stub.systems[1])

    def test_invalid_outline_without_existing_falls_back(self) -> None:
        self.stub.outline = ""
        made = self._run()
        self.assertEqual(len(made), 3)
        self.assertFalse((self.series_dir / OUTLINE_FILENAME).exists())
        for system in self.stub.systems:
            self.assertNotIn("【系列上下文】", system)

    def test_skeleton_regenerates_to_generated(self) -> None:
        # skeleton / generated 按旧行为重生成：无 key 出骨架，补上 key 后应被改写
        self.cfg["llm"]["api_key"] = ""
        first = self._run()
        meta, _ = parse_script(first[0].read_text(encoding="utf-8"))
        self.assertEqual(meta["ai_stage"], "skeleton")
        before = first[0].read_bytes()

        self.cfg["llm"]["api_key"] = "stub"
        second = self._run()
        meta, _ = parse_script(second[0].read_text(encoding="utf-8"))
        self.assertEqual(meta["ai_stage"], "generated")
        self.assertNotEqual(second[0].read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
