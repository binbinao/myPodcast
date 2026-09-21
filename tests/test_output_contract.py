"""守护「output/ 是发布件 + 状态存储，不是构建产物」这条契约。

为什么要这个文件
----------------
``output/`` 的位置和命名都像「构建产物目录」，于是它天然是「清理/重构」时的第一个目标。
但它实际同时承担三件事，每一件都是站点运行所必需：

1. **站点发布件** —— ``publish.yml`` 把整个 ``output/`` 推到 gh-pages 分支托管。
   ``feed.xml`` / ``index.html`` / ``style.css`` / ``cover.jpg`` 都在这一层。
2. **运行时数据源** —— ``templates/feed.js`` 会 ``fetch('manifest.json')`` 拉全量
   episodes 再渲染首页/系列页/分页。**删掉 manifest.json = 首页空白**。
3. **被超链接指向的页面** —— ``feed.js`` 拼出 ``series/<slug>/ep-NN/shownotes.md`` 的
   ``<a href>``。**删掉 shownotes = 全站 404**。

所以「清理构建产物」这一步在这个目录上是**破坏性操作**，而此前**零测试守护**
（2026-09-21 审计结论）。

覆盖
1. 静态契约：feed.js 仍 fetch manifest.json、仍构造 shownotes.md 链接；feed.py 仍定义 MANIFEST
2. output/ 必须仍被 git 追踪（不得被 .gitignore 吞掉）
3. 站点入口文件齐全（feed.xml / index.html / style.css / manifest.json）
4. manifest 可解析且 episodes 非空
5. 正向一致：manifest 里每集的 url 与 shownotes.md 在磁盘上真实存在，且 mp3 不是 LFS 指针
6. 反向一致：磁盘上每个 ep-NN 目录都在 manifest 里有对应 _key（防孤儿目录）
7. tests/ 不得构建或写入仓库的 output/（防"跑测试就改生产数据"复发）
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT / "output"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
SERIES_DIR = OUTPUT_DIR / "series"
FEED_JS = ROOT / "templates" / "feed.js"
FEED_PY = ROOT / "src" / "feed.py"
TESTS_DIR = ROOT / "tests"

# LFS 指针文件的大小上限（真实内容是 131 字节左右的文本）
_MIN_AUDIO_BYTES = 4096


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1 · 静态契约：站点运行时依赖不能被"顺手重构"掉
# ---------------------------------------------------------------------------
class TestRuntimeDependenciesAreIntact(unittest.TestCase):
    """feed.js / feed.py 对 output 资产的运行时依赖（静态断言，永远可跑）。"""

    def test_feed_js_fetches_manifest(self) -> None:
        """feed.js 仍从 manifest.json 拉数据 —— 这是 manifest 不能删的唯一理由。"""
        src = FEED_JS.read_text(encoding="utf-8")
        self.assertIn(
            "fetch('manifest.json'",
            src,
            "templates/feed.js 不再 fetch('manifest.json')。"
            "若架构确实改了（改为服务端渲染），请先更新本测试的假设，再动 output/manifest.json。",
        )

    def test_feed_js_builds_shownotes_links(self) -> None:
        """feed.js 仍输出指向 shownotes.md 的链接 —— 所以 shownotes 不是可清中间产物。"""
        src = FEED_JS.read_text(encoding="utf-8")
        self.assertIn(
            "shownotes.md",
            src,
            "templates/feed.js 不再链接 shownotes.md。",
        )
        self.assertRegex(
            src,
            r"shownotes\.md",
            "shownotes.md 必须仍作为页面被引用（否则该文件沦为死资产，可另行处理）",
        )

    def test_feed_py_defines_manifest_constant(self) -> None:
        """feed.py 仍以 manifest.json 为状态存储（日期/续传 key 都记在里面）。"""
        src = FEED_PY.read_text(encoding="utf-8")
        self.assertRegex(
            src,
            r'MANIFEST\s*=\s*"manifest\.json"',
            "src/feed.py 不再以 manifest.json 为状态存储 —— 契约已变，请复核本测试",
        )


# ---------------------------------------------------------------------------
# 2-6 · output/ 的真实一致性
# ---------------------------------------------------------------------------
@unittest.skipUnless(MANIFEST_PATH.exists(), "缺 output/manifest.json（未构建过？）")
class TestOutputIsPublishArtifact(unittest.TestCase):
    """output/ 必须保持「发布件 + 状态存储」的完整性。"""

    def test_output_is_git_tracked(self) -> None:
        """output/ 不得被 .gitignore 排除 —— 它是发布件，被忽略就上不了站。"""
        try:
            proc = subprocess.run(
                ["git", "check-ignore", "-q", "output/manifest.json"],
                cwd=ROOT,
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):  # pragma: no cover
            self.skipTest("git 不可用")
        self.assertNotEqual(
            proc.returncode,
            0,
            "output/manifest.json 被 .gitignore 忽略了。"
            "output/ 是发布件 + 状态存储，不是构建产物目录，被忽略后站点会缺数据。",
        )

    def test_site_entrypoints_exist(self) -> None:
        """站点入口文件齐全。"""
        for name in ("feed.xml", "index.html", "style.css", "manifest.json"):
            p = OUTPUT_DIR / name
            self.assertTrue(p.is_file(), f"缺站点入口文件 output/{name}")
            self.assertGreater(p.stat().st_size, 0, f"output/{name} 是空文件")

    def test_manifest_parsable_and_non_empty(self) -> None:
        data = _manifest()
        self.assertIn("episodes", data)
        self.assertGreater(len(data["episodes"]), 0, "manifest.episodes 为空 —— 站点会没有内容")

    def test_manifest_entries_have_required_fields(self) -> None:
        """每集必须带 _key / slug / url —— feed.js 与续传都依赖它们。"""
        for ep in _manifest()["episodes"]:
            for field in ("_key", "slug", "url", "ep_index"):
                self.assertIn(field, ep, f"manifest 条目缺 {field}: {ep.get('_key')!r}")

    def test_manifest_audio_files_exist_on_disk(self) -> None:
        """正向一致：manifest 指向的 mp3 必须真实存在，且不是 LFS 指针。"""
        problems: list[str] = []
        for ep in _manifest()["episodes"]:
            url = ep.get("url", "")
            if not url:
                continue
            audio = OUTPUT_DIR / url
            if not audio.is_file():
                problems.append(f"{ep['_key']} → 缺 {url}")
            elif audio.stat().st_size < _MIN_AUDIO_BYTES:
                problems.append(f"{ep['_key']} → {url} 只有 {audio.stat().st_size}B，疑似 LFS 指针")
        self.assertEqual(problems, [], "manifest 与磁盘不一致（音频缺失）：\n  " + "\n  ".join(problems))

    def test_manifest_shownotes_exist_on_disk(self) -> None:
        """正向一致：每集的 shownotes.md 必须存在 —— 它被 feed.js 超链接指向。"""
        missing: list[str] = []
        for ep in _manifest()["episodes"]:
            url = ep.get("url", "")
            if not url:
                continue
            notes = (OUTPUT_DIR / url).parent / "shownotes.md"
            if not notes.is_file():
                missing.append(f"{ep['_key']} → 缺 {notes.relative_to(ROOT)}")
        self.assertEqual(
            missing,
            [],
            "shownotes.md 缺失。它是被 feed.js 链接的**页面**，不是可删的中间产物：\n  " + "\n  ".join(missing),
        )

    def test_no_orphan_episode_dirs(self) -> None:
        """反向一致：磁盘上每个 ep-NN 目录都必须有 manifest 条目（防孤儿目录）。"""
        keys = {ep.get("_key") for ep in _manifest()["episodes"]}
        orphans: list[str] = []
        if SERIES_DIR.is_dir():
            for series in sorted(p for p in SERIES_DIR.iterdir() if p.is_dir()):
                for ep_dir in sorted(p for p in series.iterdir() if p.is_dir()):
                    m = re.match(r"^ep-(\d+)$", ep_dir.name)
                    if not m:
                        continue
                    key = f"{series.name}::ep-{int(m.group(1)):02d}"
                    if key not in keys:
                        orphans.append(f"{ep_dir.relative_to(ROOT)} → manifest 里没有 {key}")
        self.assertEqual(
            orphans,
            [],
            "磁盘上有 manifest 未登记的集（孤儿目录）。"
            "若是产物残留请清理；若是新集请重跑 build 注册：\n  " + "\n  ".join(orphans),
        )


# ---------------------------------------------------------------------------
# 7 · 测试自身不得改生产 output（复用本文件守护同一个边界）
# ---------------------------------------------------------------------------
_WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "replace", "touch"}


def _subprocess_build_calls(path: Path) -> list[int]:
    """找出用 subprocess 调 src.build 的行号（除非显式 --out 到非 output 目录）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover
        return []
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "subprocess"):
            continue
        strings = [
            sub.value
            for arg in node.args
            for sub in ast.walk(arg)
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
        ]
        if not any("src.build" in s for s in strings):
            continue
        # 允许：显式把产物写到临时目录
        out_ok = any(s.startswith("--out") for s in strings)
        if not out_ok:
            hits.append(node.lineno)
    return hits


def _writes_repo_output(path: Path) -> list[tuple[int, str]]:
    """找出对仓库 output/ 路径做写操作的行（接收者里硬编码了 'output' 字面量）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover
        return []
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _WRITE_METHODS:
            continue
        recv = ast.unparse(node.func.value)
        if "'output'" not in recv and '"output"' not in recv:
            continue
        low = recv.lower()
        if "tmp" in low or "temp" in low:  # 显式临时目录，放行
            continue
        hits.append((node.lineno, f"{recv}.{node.func.attr}(...)"))
    return hits


class TestSuiteDoesNotTouchProductionOutput(unittest.TestCase):
    """测试必须只读生产 output/。

    背景：``tests/test_mini_player.py`` 曾在 ``setUpClass`` 里跑
    ``python -m src.build drafts/ --skip-audio`` 写真实 output/。``--skip-audio``
    只在 ``source_hash`` 命中时幂等跳过，所以只要有一集改稿后未重渲，跑一次测试
    就会重渲它、**刷掉 shownotes 日期**并改写 manifest。该行为已于 2026-09-21 移除。
    """

    def test_no_test_invokes_build_on_repo_output(self) -> None:
        offenders: list[str] = []
        for f in sorted(TESTS_DIR.glob("test_*.py")):
            for lineno in _subprocess_build_calls(f):
                offenders.append(f"{f.name}:{lineno} 用 subprocess 调 src.build（未指定 --out）")
        self.assertEqual(
            offenders,
            [],
            "测试不得触发对仓库 output/ 的构建 —— 用 TemporaryDirectory + --out 代替：\n  "
            + "\n  ".join(offenders),
        )

    def test_no_test_writes_repo_output(self) -> None:
        offenders: list[str] = []
        for f in sorted(TESTS_DIR.glob("test_*.py")):
            for lineno, expr in _writes_repo_output(f):
                offenders.append(f"{f.name}:{lineno} → {expr}")
        self.assertEqual(
            offenders,
            [],
            "测试对仓库 output/ 有写操作，会污染生产数据：\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
