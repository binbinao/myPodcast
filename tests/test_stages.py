"""src.stages 单元测试 + draft 只读契约守卫（unittest，零外部依赖）。

两类断言：
1. stages 模块本身：stage 读写、legacy 兼容、frontmatter 逐字节保留
2. **契约守卫**：build.py 不得再调 polish() —— 这是本次重构的核心不变量，
   靠 AST 扫描机械 enforce，防止后人"顺手加回来"。
"""
import ast
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.generate import _skeleton
from src.ingest import parse_script
from src.split import EpisodePlan
from src.stages import (
    STAGE_FROZEN,
    STAGE_GENERATED,
    STAGE_REVIEWED,
    STAGE_SKELETON,
    is_human_approved,
    iter_drafts,
    mark_reviewed,
    set_stage,
    stage_of,
    stage_warning,
)

_DRAFT = """---
title: "测试节目 · 第一章"
series_slug: "test-show"
episode: 1
total: 3
source: "raw/test.md"
ai_stage: generated
---

[host] 第一段内容。
[guest] 第二段内容。
"""

_LEGACY_DRAFT = """---
title: "存量节目"
series_slug: "legacy-show"
episode: 1
---

[host] 存量正文。
"""


class TestStageOf(unittest.TestCase):
    def test_reads_valid_stage(self):
        meta, _ = parse_script(_DRAFT)
        self.assertEqual(stage_of(meta), STAGE_GENERATED)

    def test_legacy_missing_field_returns_empty(self):
        meta, _ = parse_script(_LEGACY_DRAFT)
        self.assertEqual(stage_of(meta), "")

    def test_unknown_value_treated_as_legacy(self):
        """非法值不能被当成合法 stage 放行，否则 `ai_stage: whatever` 就能绕过告警。"""
        self.assertEqual(stage_of({"ai_stage": "bogus"}), "")

    def test_case_and_whitespace_tolerant(self):
        self.assertEqual(stage_of({"ai_stage": "  REVIEWED "}), STAGE_REVIEWED)

    def test_none_value(self):
        self.assertEqual(stage_of({"ai_stage": None}), "")


class TestHumanApproved(unittest.TestCase):
    def test_reviewed_and_frozen_are_approved(self):
        self.assertTrue(is_human_approved(STAGE_REVIEWED))
        self.assertTrue(is_human_approved(STAGE_FROZEN))

    def test_generated_and_skeleton_are_not(self):
        self.assertFalse(is_human_approved(STAGE_GENERATED))
        self.assertFalse(is_human_approved(STAGE_SKELETON))
        self.assertFalse(is_human_approved(""))


class TestStageWarning(unittest.TestCase):
    def test_approved_stages_silent(self):
        self.assertEqual(stage_warning(STAGE_REVIEWED), "")
        self.assertEqual(stage_warning(STAGE_FROZEN), "")

    def test_unapproved_stages_warn(self):
        for stage in (STAGE_GENERATED, STAGE_SKELETON, ""):
            self.assertTrue(stage_warning(stage), f"{stage!r} 应当告警")

    def test_skeleton_warning_mentions_key(self):
        """骨架稿的根因是缺 LLM key，告警要说出来，否则用户不知道怎么修。"""
        self.assertIn("key", stage_warning(STAGE_SKELETON))

    def test_generated_warning_points_to_fix_command(self):
        self.assertIn("--mark-reviewed", stage_warning(STAGE_GENERATED))


class TestSetStage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_replaces_existing_stage(self):
        p = self._write("ep-01.md", _DRAFT)
        old = set_stage(p, STAGE_REVIEWED)
        self.assertEqual(old, STAGE_GENERATED)
        meta, _ = parse_script(p.read_text(encoding="utf-8"))
        self.assertEqual(stage_of(meta), STAGE_REVIEWED)

    def test_inserts_into_legacy_draft(self):
        p = self._write("ep-01.md", _LEGACY_DRAFT)
        old = set_stage(p, STAGE_REVIEWED)
        self.assertEqual(old, "")
        meta, _ = parse_script(p.read_text(encoding="utf-8"))
        self.assertEqual(stage_of(meta), STAGE_REVIEWED)

    def test_body_preserved_byte_for_byte(self):
        """核心不变量：改 stage 绝不能碰正文，否则 build 只读契约就是假的。"""
        p = self._write("ep-01.md", _DRAFT)
        before = _DRAFT.split("---\n", 2)[2]
        set_stage(p, STAGE_FROZEN)
        after = p.read_text(encoding="utf-8").split("---\n", 2)[2]
        self.assertEqual(before, after)

    def test_other_frontmatter_fields_preserved(self):
        p = self._write("ep-01.md", _DRAFT)
        set_stage(p, STAGE_FROZEN)
        meta, _ = parse_script(p.read_text(encoding="utf-8"))
        self.assertEqual(meta["title"], "测试节目 · 第一章")
        self.assertEqual(meta["series_slug"], "test-show")
        self.assertEqual(meta["episode"], 1)
        self.assertEqual(meta["total"], 3)
        self.assertEqual(meta["source"], "raw/test.md")

    def test_idempotent(self):
        p = self._write("ep-01.md", _DRAFT)
        set_stage(p, STAGE_REVIEWED)
        first = p.read_text(encoding="utf-8")
        set_stage(p, STAGE_REVIEWED)
        self.assertEqual(first, p.read_text(encoding="utf-8"))

    def test_rejects_unknown_stage(self):
        p = self._write("ep-01.md", _DRAFT)
        with self.assertRaises(ValueError):
            set_stage(p, "bogus")

    def test_rejects_file_without_frontmatter(self):
        p = self._write("ep-01.md", "[host] 没有 frontmatter。\n")
        with self.assertRaises(ValueError):
            set_stage(p, STAGE_REVIEWED)


class TestIterDrafts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_collects_ep_files_only(self):
        (self.dir / "ep-01.md").write_text(_DRAFT, encoding="utf-8")
        (self.dir / "ep-02.md").write_text(_DRAFT, encoding="utf-8")
        (self.dir / "README.md").write_text("# 笔记\n", encoding="utf-8")
        found = [p.name for p in iter_drafts(self.dir)]
        self.assertEqual(found, ["ep-01.md", "ep-02.md"])

    def test_recurses_into_series_dirs(self):
        sub = self.dir / "2026-08-01-series"
        sub.mkdir()
        (sub / "ep-01.md").write_text(_DRAFT, encoding="utf-8")
        self.assertEqual(len(iter_drafts(self.dir)), 1)

    def test_single_file_target(self):
        p = self.dir / "ep-07.md"
        p.write_text(_DRAFT, encoding="utf-8")
        self.assertEqual(iter_drafts(p), [p])


class TestMarkReviewed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_marks_all_drafts_in_dir(self):
        for n in ("ep-01.md", "ep-02.md"):
            (self.dir / n).write_text(_DRAFT, encoding="utf-8")
        changed = mark_reviewed(self.dir)
        self.assertEqual(len(changed), 2)
        for p, old in changed:
            self.assertEqual(old, STAGE_GENERATED)
            meta, _ = parse_script(p.read_text(encoding="utf-8"))
            self.assertEqual(stage_of(meta), STAGE_REVIEWED)

    def test_raises_on_empty_dir(self):
        with self.assertRaises(ValueError):
            mark_reviewed(self.dir)


class TestGenerateStampsStage(unittest.TestCase):
    """prepare 产出的 draft 必须自带 stage，否则全是 legacy 告警。"""

    def _plan(self, **kw) -> EpisodePlan:
        base = dict(
            index=1, total=2, title="节目", series="节目", series_slug="show",
            chapter="第一章", body="第一段。\n\n第二段。", format="duo",
            article_date="2026-08-01",
        )
        base.update(kw)
        return EpisodePlan(**base)

    def test_skeleton_marked_skeleton(self):
        meta, _ = parse_script(_skeleton(self._plan(), source="raw/t.md"))
        self.assertEqual(stage_of(meta), STAGE_SKELETON)

    def test_skeleton_stage_not_human_approved(self):
        """骨架稿不能被当成审过的稿子静默放行。"""
        meta, _ = parse_script(_skeleton(self._plan()))
        self.assertFalse(is_human_approved(stage_of(meta)))


class TestBuildReadOnlyContract(unittest.TestCase):
    """契约守卫：build.py 不得对 draft 做 LLM 改写。

    重构前 build.py 调 polish() 二次改写，吃掉人工在 drafts/ 的修改。
    规范若只写在注释里就会被后人改回去，所以用 AST 机械 enforce。
    """

    @staticmethod
    def _build_tree() -> ast.Module:
        return ast.parse((ROOT / "src" / "build.py").read_text(encoding="utf-8"))

    def test_no_polish_import(self):
        names = set()
        for node in ast.walk(self._build_tree()):
            if isinstance(node, ast.ImportFrom):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
        self.assertNotIn(
            "polish", names,
            "build.py 不得 import polish —— draft 只读契约要求 build 不改写正文",
        )

    def test_no_polish_call(self):
        called = {
            node.func.id
            for node in ast.walk(self._build_tree())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn(
            "polish", called,
            "build.py 不得调用 polish() —— 会吃掉 drafts/ 里的人工修改",
        )

    def test_no_llm_complete_call(self):
        """build 阶段不该有任何 LLM 文本改写入口。

        白名单：prosody/voicecaster 在 build 期调 LLM 是允许的（它们只决定
        "怎么念"，不碰文本），但那发生在各自模块内，不在 build.py。
        """
        src = (ROOT / "src" / "build.py").read_text(encoding="utf-8")
        self.assertNotIn("llm_complete", src)


class TestMaxTokensWired(unittest.TestCase):
    """config 的 llm.max_tokens / temperature 必须真的进 payload。

    这两个键曾经写在 config.yaml 里但 polish.py 从不读取（死配置）。
    """

    def test_polish_reads_both_keys(self):
        src = (ROOT / "src" / "polish.py").read_text(encoding="utf-8")
        self.assertIn('llm.get("max_tokens"', src)
        self.assertIn('llm.get("temperature"', src)

    def test_no_hardcoded_temperature(self):
        src = (ROOT / "src" / "polish.py").read_text(encoding="utf-8")
        self.assertNotIn('"temperature": 0.7', src,
                         "temperature 应从 cfg 读，不能硬编码")


if __name__ == "__main__":
    unittest.main()
