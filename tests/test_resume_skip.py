"""守护断点续传的跳过判定（``src/build.py::_is_unchanged``）。

为什么要这个文件
----------------
2026-09-21 发现真实缺陷：跳过判定原写成 ``if src_h and old.source_hash == src_h``，
要求内容指纹 truthy。而 ``_hash_source("")`` 对**没有 source: 字段**的稿件返回 None，
于是条件恒假 —— 这类稿件**每次 build 都被重渲**。

它的危害不是报错，而是静默地毁掉可复现性：
``manifest`` 的 ``updated`` / 条目顺序、``feed.xml`` 每次部署都变，
``--skip-audio`` 对它们彻底失效，CI 产出无意义 diff。属于"不会让任何测试变红"的缺陷，
所以在此显式钉住判定语义。

判定语义（三条）
1. 有 ``source:`` 且 hash 与 manifest 一致 → 未变，可跳过
2. **无** ``source:`` → 视为「无可比对」，按未变处理（早期 demo 稿属此类）
3. 有 ``source:`` 但文件缺失 → 视为已变，不静默放过
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.build import _is_unchanged
from src.feed import _hash_source


class TestIsUnchanged(unittest.TestCase):
    """_is_unchanged(meta_pre, old) 的三种判定。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.raw = self.tmp / "raw.md"
        self.raw.write_text("原始文章内容", encoding="utf-8")
        self.hash = _hash_source(str(self.raw))
        assert self.hash is not None, "fixture 应能算出指纹"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_source_field_is_unchanged(self) -> None:
        """无 source: 的稿件按未变处理 —— 这正是修复的缺陷点。

        若这里变成 False，说明"无 source 则每次重渲"的缺陷又回来了。
        """
        self.assertTrue(
            _is_unchanged({"series_slug": "x", "episode": 1}, {"source_hash": None}),
            "无 source 字段的稿件必须可跳过，否则每次 build 都重渲、断点续传失效",
        )
        self.assertTrue(_is_unchanged({}, {}))
        self.assertTrue(_is_unchanged({"source": ""}, {"source_hash": "whatever"}))

    def test_same_hash_is_unchanged(self) -> None:
        """常规路径：指纹一致 → 跳过。"""
        self.assertTrue(_is_unchanged({"source": str(self.raw)}, {"source_hash": self.hash}))

    def test_different_hash_is_changed(self) -> None:
        """raw 改了 → 必须重跑。"""
        self.assertFalse(
            _is_unchanged({"source": str(self.raw)}, {"source_hash": "deadbeefdeadbeef"}),
            "指纹不一致时必须重跑，否则改稿不会被重渲",
        )

    def test_missing_source_file_is_changed(self) -> None:
        """有 source 但文件不存在 → 判为已变，不静默放过。"""
        self.assertFalse(
            _is_unchanged(
                {"source": str(self.tmp / "not-there.md")},
                {"source_hash": self.hash},
            ),
            "source 指向的文件缺失时不应静默跳过",
        )

    def test_old_entry_without_hash_is_changed(self) -> None:
        """manifest 里该集没有 source_hash（历史遗留）→ 重跑一次把指纹补上。"""
        self.assertFalse(_is_unchanged({"source": str(self.raw)}, {}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
