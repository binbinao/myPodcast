"""守护 raw/ → drafts/ → output/ 的血缘与命名契约（纯静态，不依赖网络/模型/TTS 服务）。

为什么要这个文件
----------------
2026-09-21 的一次清理审计中，我（AI）把「raw/ 里没有同名 drafts/ 目录」直接当成了
「从未制作」，据此把两篇稿子标记为「可废弃」。事实恰好相反：

  - ``raw/2026-06-12-codebuddy-ee-final.md`` 是**已上线系列** ``codebuddy-auto-ee``(9 集)
    的上游源稿 —— ``raw/2026-08-20-codebuddy-auto-ee.md`` 的 frontmatter ``source:`` 指向它。
    这属于**二级血缘**，目录名看不出来。
  - ``raw/2026-08-06-cbm-baremetal.md`` 是制作过、后被主动下架的系列，仓库内**最后一份记录**。

教训：**目录名不是血缘的唯一线索，``source:`` frontmatter 才是。**
这个文件把「raw 文件的身份必须显式登记」钉成断言，让同类误判无法再次悄悄发生。

覆盖
1. drafts/<dir>/ep-XX.md 的 ``source:`` 指向的文件必须真实存在（一级血缘不断裂）
2. raw/*.md 自身的 ``source:`` 指向的文件也必须存在（二级血缘不断裂）
3. draft 目录名必须 == ``<date>-<series_slug>``（与 manifest 的 slug 同源）
4. raw/ 顶层文件的身份在 ``RAW_LINEAGE`` 显式登记，且与磁盘**双向一致**
5. episodes/ 下的稿件必须真的能被 build 处理（命名 + series_slug），否则是孤儿稿
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import yaml

    _SKIP_REASON: str | None = None
except ImportError as _exc:  # pragma: no cover
    _SKIP_REASON = f"依赖缺失: {_exc}"

RAW_DIR = ROOT / "raw"
DRAFTS_DIR = ROOT / "drafts"
EPISODES_DIR = ROOT / "episodes"
OUTPUT_SERIES_DIR = ROOT / "output" / "series"

# build 可识别的稿件命名（src/build.py 用 ^ep-\d+\.md$ 过滤）
EP_FILENAME_RE = re.compile(r"^ep-\d+\.md$")
# draft 目录名规范：<YYYY-MM-DD>-<series_slug>
DRAFT_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")

# ---------------------------------------------------------------------------
# raw/ 顶层文件的身份登记表。
#
# ★ 任何对 raw/ 的增删都必须同步改这里 —— 这就是防误判的机制。
#   删除一个 raw 文件前，你被迫回答「它的身份是什么」，而不是靠「有没有同名
#   drafts 目录」去猜。取值前缀：
#     produced:<draft-dir>    → 已产出节目，drafts/<draft-dir>/ 存在
#     upstream-of:<raw-file>  → 自身没直接产出，但是另一个 raw 的上游（二级血缘）
#     withdrawn:<slug>        → 制作过但已下架，仓库内唯一留档
#     attachment:<用途说明>   → 素材/附件，不参与血缘
# ---------------------------------------------------------------------------
RAW_LINEAGE: dict[str, str] = {
    "2026-03-09-ai-infra-redefined.md": "produced:2026-03-09-ai-infra-redefined",
    "2026-03-26-ai-development-history.md": "produced:2026-03-26-ai-development-history",
    "2026-03-30-ai-chips.md": "produced:2026-03-30-ai-chips",
    "2026-04-12-cross-border-ecommerce.md": "produced:2026-04-12-cross-border-ecommerce",
    "2026-06-12-codebuddy-ee-final.md": "upstream-of:2026-08-20-codebuddy-auto-ee.md",
    "2026-06-14-agentic-engineering-wechat-final.md": "produced:2026-06-14-agentic-engineering-wechat-final",
    "2026-07-31-when-platform-absorbs-you.md": "produced:2026-07-31-when-platform-absorbs-you",
    "2026-08-01-knowledge-management.md": "produced:2026-08-01-knowledge-management",
    "2026-08-06-cbm-baremetal.md": "withdrawn:cbm-baremetal",
    "2026-08-16-nasa-se-handbook.md": "produced:2026-08-16-nasa-se-handbook",
    "2026-08-20-codebuddy-auto-ee.md": "produced:2026-08-20-codebuddy-auto-ee",
    "2026-09-05-gapminder2007.md": "produced:2026-09-05-gapminder2007",
    "2026-09-16-data-analytics-10-lesson-introduction.md": "produced:2026-09-16-data-analytics-10-lesson-introduction",
    "NASA系统工程手册.pdf": "upstream-of:2026-08-16-nasa-se-handbook.md",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def read_frontmatter(path: Path) -> dict:
    """解析 markdown 的 YAML frontmatter；没有则返回 {}。"""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", text, re.S)
    if not m:
        return {}
    data = yaml.safe_load(m.group(1))
    return data if isinstance(data, dict) else {}


def raw_top_files() -> set[str]:
    """raw/ 顶层的实体文件（排除隐藏文件与 .gitkeep）。"""
    return {
        p.name
        for p in RAW_DIR.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.name != ".gitkeep"
    }


def draft_dirs() -> list[Path]:
    return sorted(p for p in DRAFTS_DIR.iterdir() if p.is_dir())


def _norm_source(value: object) -> str | None:
    """把 frontmatter 的 source 值归一为字符串（相对路径或 URL）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().strip("\"'")


def _is_url(value: str) -> bool:
    """source: 可以是远程 URL（如 gapminder 那篇取自报告站点），无需本地存在。"""
    return value.startswith(("http://", "https://"))


# ---------------------------------------------------------------------------
# 1-3 · drafts 侧
# ---------------------------------------------------------------------------
@unittest.skipIf(_SKIP_REASON, _SKIP_REASON or "")
class TestDraftLineage(unittest.TestCase):
    """drafts/ 的血缘与命名。"""

    def test_draft_source_must_exist(self) -> None:
        """每个 draft 的 source: 指向的文件必须存在（一级血缘）。"""
        broken: list[str] = []
        for d in draft_dirs():
            for ep in sorted(d.glob("ep-*.md")):
                src = _norm_source(read_frontmatter(ep).get("source"))
                if src is None or _is_url(src):
                    continue
                if not (ROOT / src).exists():
                    broken.append(f"{ep.relative_to(ROOT)} → source 指向不存在的 {src!r}")
        self.assertEqual(
            broken,
            [],
            "血缘断裂：draft 引用的源稿已不存在。"
            "若确要删除源稿，必须先清空对应 draft 的 source: 字段并说明理由。\n  "
            + "\n  ".join(broken),
        )

    def test_draft_dirname_matches_series_slug(self) -> None:
        """draft 目录名必须 == <date>-<series_slug>（目录名与 manifest slug 同源）。"""
        problems: list[str] = []
        for d in draft_dirs():
            first = d / "ep-01.md"
            if not first.exists():
                cands = sorted(d.glob("ep-*.md"))
                if not cands:
                    continue
                first = cands[0]
            meta = read_frontmatter(first)
            slug = meta.get("series_slug")
            m = DRAFT_DIR_RE.match(d.name)
            if not m:
                problems.append(f"{d.name}：目录名不符合 <YYYY-MM-DD>-<series_slug>")
                continue
            if not slug:
                problems.append(f"{d.name}：ep-01.md 缺 series_slug（build 会用标题生成 slug，可能漂移）")
                continue
            if m.group(2) != slug:
                problems.append(f"{d.name}：目录名尾段 {m.group(2)!r} != series_slug {slug!r}")
        self.assertEqual(problems, [], "draft 命名与 series_slug 不一致：\n  " + "\n  ".join(problems))

    def test_draft_series_slug_has_output_series(self) -> None:
        """有 series_slug 的 draft，其 output/series/<slug>/ 应当存在（已产出）。"""
        missing: list[str] = []
        for d in draft_dirs():
            metad = read_frontmatter(d / "ep-01.md") if (d / "ep-01.md").exists() else {}
            slug = metad.get("series_slug")
            if not slug:
                continue
            if not (OUTPUT_SERIES_DIR / slug).is_dir():
                missing.append(f"{d.name} → slug={slug}，但 output/series/{slug}/ 不存在")
        self.assertEqual(
            missing,
            [],
            "draft 尚无对应产出目录（如果是有意为之可忽略，但请确认不是产物被误删）：\n  "
            + "\n  ".join(missing),
        )


# ---------------------------------------------------------------------------
# 2 + 4 · raw 侧（这条是本次事件的正主）
# ---------------------------------------------------------------------------
@unittest.skipIf(_SKIP_REASON, _SKIP_REASON or "")
class TestRawLineageRegistry(unittest.TestCase):
    """raw/ 顶层文件必须显式登记身份，且登记表与磁盘双向一致。"""

    def test_raw_files_match_registry(self) -> None:
        """磁盘上的 raw 文件集合 == 登记表键集合（双向）。

        新增一个 raw 文件 → 必须登记它的身份（否则本轮禁止入库）；
        删除一个 raw 文件 → 必须先把登记项删掉（强制回答「它是什么」）。
        """
        disk = raw_top_files()
        registered = set(RAW_LINEAGE)
        added = sorted(disk - registered)
        removed = sorted(registered - disk)
        self.assertEqual(
            (added, removed),
            ([], []),
            "raw/ 与 RAW_LINEAGE 登记表不一致：\n"
            f"  磁盘有但未登记：{added}\n"
            f"  已登记但磁盘没有：{removed}\n"
            "删 raw 前请先确认它是否被某个 draft 的 source: 引用、或是否是下架内容的唯一留档。",
        )

    def test_registry_targets_exist(self) -> None:
        """登记项指向的目标必须存在（produced 的 draft 目录 / upstream-of 的 raw 文件）。"""
        problems: list[str] = []
        for name, spec in RAW_LINEAGE.items():
            kind, _, target = spec.partition(":")
            if kind == "produced":
                if not (DRAFTS_DIR / target).is_dir():
                    problems.append(f"{name} → produced:{target}，但 drafts/{target}/ 不存在")
            elif kind == "upstream-of":
                if not (RAW_DIR / target).is_file():
                    problems.append(f"{name} → upstream-of:{target}，但该 raw 不存在")
            elif kind in {"withdrawn", "attachment"}:
                pass
            else:
                problems.append(f"{name} → 未知身份前缀 {kind!r}（应用 produced/upstream-of/withdrawn/attachment）")
        self.assertEqual(problems, [], "RAW_LINEAGE 登记项目标无效：\n  " + "\n  ".join(problems))

    def test_upstream_relation_is_bidirectional(self) -> None:
        """标记为 upstream-of:X 的文件，X 的 frontmatter source: 必须确实指向它。"""
        problems: list[str] = []
        for name, spec in RAW_LINEAGE.items():
            kind, _, target = spec.partition(":")
            if kind != "upstream-of":
                continue
            child = RAW_DIR / target
            if not child.is_file():
                continue  # 已由 test_registry_targets_exist 报错
            src = _norm_source(read_frontmatter(child).get("source"))
            if src is None or Path(src).name != name:
                problems.append(f"{child.name} 的 source: 是 {src!r}，未指向登记的 {name!r}")
        self.assertEqual(problems, [], "二级血缘声明与实际不符：\n  " + "\n  ".join(problems))

    def test_raw_second_level_source_must_exist(self) -> None:
        """raw/*.md 自身的 source: 指向的文件必须存在（二级血缘）。"""
        broken: list[str] = []
        for f in sorted(RAW_DIR.glob("*.md")):
            src = _norm_source(read_frontmatter(f).get("source"))
            if src is None or _is_url(src):
                continue
            if not (ROOT / src).exists():
                broken.append(f"raw/{f.name} → source 指向不存在的 {src!r}")
        self.assertEqual(broken, [], "raw 二级血缘断裂：\n  " + "\n  ".join(broken))


# ---------------------------------------------------------------------------
# 5 · episodes/ 侧（孤儿稿守护）
# ---------------------------------------------------------------------------
@unittest.skipIf(_SKIP_REASON, _SKIP_REASON or "")
class TestEpisodesAreBuildable(unittest.TestCase):
    """episodes/ 下每篇稿件都必须真的能被 build 处理，否则是孤儿稿。"""

    def test_episodes_scripts_are_buildable(self) -> None:
        """episodes/*.md 必须满足：文件名 ^ep-\\d+\\.md$ 且 frontmatter 带 series_slug。

        src/build.py 用 ``target.glob("**/*.md")`` + ``^ep-\\d+\\.md$`` 过滤，
        而 ``_key`` 由 frontmatter 的 ``series_slug`` 决定（缺失则用标题转拼音）。
        任一条不满足，稿件要么扫不到、要么会在站点上造出一个新系列。
        """
        if not EPISODES_DIR.is_dir():
            self.skipTest("episodes/ 不存在")
        problems: list[str] = []
        for f in sorted(EPISODES_DIR.glob("**/*.md")):
            if not EP_FILENAME_RE.match(f.name):
                problems.append(f"episodes/{f.name}：文件名不符合 ep-XX.md，build 扫描不到（孤儿稿）")
                continue
            meta = read_frontmatter(f)
            if not meta.get("series_slug"):
                problems.append(
                    f"episodes/{f.name}：缺 series_slug —— build 会用标题生成拼音 slug，"
                    "在站点上另造一个系列"
                )
        self.assertEqual(
            problems,
            [],
            "episodes/ 下存在无法安全 build 的稿件：\n  "
            + "\n  ".join(problems)
            + "\n处理方式：补 frontmatter 的 series_slug 后迁入 drafts/<date>-<slug>/ep-01.md。",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
