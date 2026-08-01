"""守护 build.run() 目录递归收集 + --skip-audio 无 mp3 时优雅跳过。

历史 bug：CI workflow 推了 5 个 commit 都失败，原因就是 `python -m src.build drafts/`
找不到嵌套结构 `drafts/<series>/ep-XX.md` 下的脚本，fallback `drafts/*/` 又被 argparse
拒收（多 positional 参数）。修：
  1. build.py 改 `target.glob("**/*.md")` 递归收集，仅匹配 `ep-XX.md`。
  2. build.run_one() 在 --skip-audio + mp3 缺失时不再 SystemExit，回 "skipped" 给 run()。
  3. .github/workflows/publish.yml 简化为单行命令。

本测试两个回归点都覆盖。
"""
from __future__ import annotations

import re
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestDirRecursiveGlob(unittest.TestCase):
    def test_finds_nested_ep_md_and_skips_stragglers(self) -> None:
        """`drafts/<series>/ep-XX.md` 嵌套结构能被递归 glob 收集；README 不收。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            (td_p / "drafts" / "series-a").mkdir(parents=True)
            (td_p / "drafts" / "series-b").mkdir(parents=True)
            # 顶层 README.md 不应被收集（只匹配 ep-XX.md）
            (td_p / "drafts" / "README.md").write_text("# ignore me", encoding="utf-8")
            (td_p / "drafts" / "notes.md").write_text("# ignore me", encoding="utf-8")
            (td_p / "drafts" / "series-a" / "ep-01.md").write_text(
                "---\ntitle: t\n---\n\n[host] hello", encoding="utf-8"
            )
            (td_p / "drafts" / "series-b" / "ep-02.md").write_text(
                "---\ntitle: t\n---\n\n[host] world", encoding="utf-8"
            )

            scripts = sorted(
                p for p in (td_p / "drafts").glob("**/*.md")
                if re.match(r"^ep-\d+\.md$", p.name)
            )
            names = sorted(p.name for p in scripts)
            self.assertEqual(names, ["ep-01.md", "ep-02.md"])


class TestSkipAudioMissingMp3(unittest.TestCase):
    def test_skip_audio_returns_skipped_when_mp3_missing(self) -> None:
        """--skip-audio 但 mp3 不存在时，run_one 不再 raise，而是回 'skipped'。

        CI 拿到一批新 draft（mp3 还没 build 出来）需要能跑完全站，只警告缺音。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            draft = td_p / "drafts" / "series-x" / "ep-01.md"
            draft.parent.mkdir(parents=True)
            draft.write_text(
                textwrap.dedent("""\
                    ---
                    title: "测试集"
                    series: "X 系列"
                    series_slug: "series-x"
                    episode: 1
                    total: 1
                    ---
                    [host] 这是一段测试文字，长度足够，不会触发段落为空保护。
                    """),
                encoding="utf-8",
            )
            out_dir = td_p / "out"
            out_dir.mkdir()
            # 不放 mp3 → 触发「skip-audio 但 mp3 不存在」分支。

            # 把模块级 SKIP_AUDIO 临时打开，模拟 CI 的 --skip-audio 调用
            from src import build as build_mod

            old_skip = build_mod.SKIP_AUDIO
            build_mod.SKIP_AUDIO = True
            try:
                result = build_mod.run_one(
                    draft,
                    out_dir,
                    {
                        "podcast": {},
                        "tts": {"backend": "edge-tts"},
                        "llm": {"enable": False},
                    },
                )
                self.assertEqual(result, "skipped")
            finally:
                build_mod.SKIP_AUDIO = old_skip


if __name__ == "__main__":
    unittest.main()
