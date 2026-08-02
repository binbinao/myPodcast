"""src.naming_enforce 单元测试（unittest.TestCase 风格，零依赖）。

Hard gate 行为验证：
1. raw 不合规自动 rename
2. drafts 不合规自动 rename
3. output series 不合规自动 rename
4. 冲突目录跳过
5. 全合规情况不动
6. CLI 退出码：0=pass / 2=CI-fail-dry-run-with-violations
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.naming_enforce import (
    enforce_all,
    enforce_drafts_dirs,
    enforce_output_series,
    enforce_raw_files,
    main,
)


class TestEnforceRaw(unittest.TestCase):
    """raw/ 不合规自动 rename。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.raw_dir = Path(self.tmp) / "raw"
        self.raw_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_compliant_no_op(self):
        (self.raw_dir / "2026-08-01-knowledge-management.md").write_text(
            "---\ndate: 2026-08-01\nseries_slug: knowledge-management\ntitle: 知识管理\n---\n\nbody",
            encoding="utf-8",
        )
        moves = enforce_raw_files(self.raw_dir)
        self.assertEqual(moves, [])

    def test_old_chinese_filename_renamed(self):
        """脏文件名（中文拼音长串）自动改到 YYYY-MM-DD-series_slug.md。"""
        (self.raw_dir / "2026-08-01-gong-cheng-shi-de-zhi-shi-guan-li.md").write_text(
            "---\ndate: 2026-08-01\nseries_slug: knowledge-management\ntitle: x\n---\n\nbody",
            encoding="utf-8",
        )
        moves = enforce_raw_files(self.raw_dir)
        self.assertEqual(len(moves), 1)
        src, dst = moves[0]
        self.assertEqual(dst.name, "2026-08-01-knowledge-management.md")
        # 真 mv 了
        self.assertTrue((self.raw_dir / "2026-08-01-knowledge-management.md").exists())
        self.assertFalse(src.exists())

    def test_conflict_skip(self):
        """目标已存在时 skip，不覆盖。"""
        # wrong.md 想 mv 成 → 2026-08-01-knowledge-management.md
        (self.raw_dir / "wrong.md").write_text(
            "---\ndate: 2026-08-01\nseries_slug: knowledge-management\ntitle: x\n---\n\nbody",
            encoding="utf-8",
        )
        # 合规 target 已存在 + 自带合规 frontmatter（不会被 enforce mv）
        (self.raw_dir / "2026-08-01-knowledge-management.md").write_text(
            "---\ndate: 2026-08-01\nseries_slug: knowledge-management\ntitle: x\n---\n\nOK body",
            encoding="utf-8",
        )
        moves = enforce_raw_files(self.raw_dir)
        # 合规 target 不动；wrong.md 想 mv 过去 → target 已存在且 != path → conflict → skip
        self.assertEqual(moves, [])
        self.assertTrue((self.raw_dir / "wrong.md").exists())  # 原 wrong 保留
        self.assertTrue((self.raw_dir / "2026-08-01-knowledge-management.md").exists())


class TestEnforceDrafts(unittest.TestCase):
    """drafts/ 不合规目录自动 rename。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.drafts_dir = Path(self.tmp) / "drafts"
        self.drafts_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dir_rename(self):
        # date 字段必须给：缺它时 enforce_drafts_dirs 回落 date.today()，
        # 断言里的固定日期就会在次日起全部失败。fixture 固定 date 使断言可精确匹配。
        old = self.drafts_dir / "wrong-dir-name"
        old.mkdir()
        (old / "ep-01.md").write_text(
            "---\nseries_slug: ai-infra-redefined\ndate: 2026-08-01\ntitle: 测试\n---\n\nbody",
            encoding="utf-8",
        )
        moves = enforce_drafts_dirs(self.drafts_dir)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0][1].name, "2026-08-01-ai-infra-redefined")

    def test_dir_compliant_no_op(self):
        """目录名已合规（YYYY-MM-DD-slug）→ 不动。"""
        target = self.drafts_dir / "2026-08-01-knowledge-management"
        target.mkdir()
        (target / "ep-01.md").write_text(
            "---\ndate: 2026-08-01\nseries_slug: knowledge-management\ntitle: x\n---\n",
            encoding="utf-8",
        )
        moves = enforce_drafts_dirs(self.drafts_dir)
        self.assertEqual(moves, [])

    def test_dir_name_provides_date_fallback(self):
        """ep frontmatter 缺 date，从目录名 YYYY-MM-DD- 前缀反推。"""
        target = self.drafts_dir / "2026-03-09-ai-infra-redefined"
        target.mkdir()
        (target / "ep-01.md").write_text(
            "---\nseries_slug: ai-infra-redefined\ntitle: x\n---\n",  # 缺 date
            encoding="utf-8",
        )
        moves = enforce_drafts_dirs(self.drafts_dir)
        # 2026-03-09（来自 dir name） + ai-infra-redefined → 与 dir name 一致 → PASS
        self.assertEqual(moves, [])


class TestEnforceOutput(unittest.TestCase):
    """output/series/ 不合规目录自动 rename（依赖 manifest.json 反查）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out_dir = Path(self.tmp) / "output"
        self.out_dir.mkdir()
        (self.out_dir / "series").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_manifest(self, episodes):
        (self.out_dir / "manifest.json").write_text(
            json.dumps({"episodes": episodes}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_output_dir_rename(self):
        """物理 dir 名 ≠ manifest series_slug 时 rename。"""
        wrong = self.out_dir / "series" / "wrong-name"
        wrong.mkdir()
        (wrong / "ep-01").mkdir()
        (wrong / "ep-01" / "shownotes.md").write_text(
            "---\nseries_slug: knowledge-management\ntitle: x\n---\n",
            encoding="utf-8",
        )
        # manifest 必须不含同名 series（否则 enforce 视作合规）
        self._write_manifest([
            {"slug": "knowledge-management", "series_slug": "knowledge-management", "episode": 1},
        ])
        moves = enforce_output_series(self.out_dir)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0][1].name, "knowledge-management")

    def test_output_compliant_no_op(self):
        """物理 dir 与 manifest 一致 → 跳过。"""
        target = self.out_dir / "series" / "knowledge-management"
        target.mkdir()
        (target / "ep-01").mkdir()
        (target / "ep-01" / "shownotes.md").write_text(
            "---\nseries_slug: knowledge-management\ntitle: x\n---\n",
            encoding="utf-8",
        )
        self._write_manifest([
            {"slug": "knowledge-management", "series_slug": "knowledge-management", "episode": 1},
        ])
        moves = enforce_output_series(self.out_dir)
        self.assertEqual(moves, [])

    def test_no_manifest_skip(self):
        """无 manifest 时警告不报错。"""
        target = self.out_dir / "series" / "anything"
        target.mkdir()
        moves = enforce_output_series(self.out_dir)
        self.assertEqual(moves, [])


class TestEnforceAll(unittest.TestCase):
    """enforce_all 集成 + 退出码。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.raw = Path(self.tmp) / "raw"
        self.drafts = Path(self.tmp) / "drafts"
        self.output = Path(self.tmp) / "output"
        self.raw.mkdir()
        self.drafts.mkdir()
        self.output.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_compliant(self):
        """种一个全合规的 baseline，让违规测试都用此 + 自己加一个 dirty 文件。"""
        (self.raw / "2026-08-01-knowledge-management.md").write_text(
            "---\ndate: 2026-08-01\nseries_slug: knowledge-management\ntitle: k\n---\n",
            encoding="utf-8",
        )
        target = self.drafts / "2026-08-01-knowledge-management"
        target.mkdir()
        (target / "ep-01.md").write_text(
            "---\ndate: 2026-08-01\nseries_slug: knowledge-management\ntitle: k\n---\n",
            encoding="utf-8",
        )

    def test_all_compliant_pass(self):
        self._seed_compliant()
        rc = enforce_all(self.raw, self.drafts, self.output, dry_run=True)
        self.assertEqual(rc, 0)

    def test_dry_run_violation_returns_2(self):
        """CI 用：dry_run 模式下存在违规时返回 2（让 CI fail）。"""
        self._seed_compliant()
        # 加一个不合规的 raw 文件
        (self.raw / "脏名.md").write_text(
            "---\ndate: 2026-08-01\nseries_slug: ai-infra-redefined\ntitle: k\n---\n",
            encoding="utf-8",
        )
        rc = enforce_all(self.raw, self.drafts, self.output, dry_run=True)
        self.assertEqual(rc, 2)

    def test_apply_violation_returns_0(self):
        """实测（非 dry-run）：违规被自动 fix 后返回 0。"""
        self._seed_compliant()
        (self.raw / "脏名.md").write_text(
            "---\ndate: 2026-08-01\nseries_slug: ai-infra-redefined\ntitle: k\n---\n",
            encoding="utf-8",
        )
        rc = enforce_all(self.raw, self.drafts, self.output, dry_run=False)
        self.assertEqual(rc, 0)
        self.assertTrue((self.raw / "2026-08-01-ai-infra-redefined.md").exists())


class TestCliExitCodes(unittest.TestCase):
    """main() 退出码契约。"""

    def test_dry_run_with_violation_returns_2(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        raw = tmp / "raw"; raw.mkdir()
        (raw / "bad.md").write_text(
            "---\ndate: 2026-08-01\nseries_slug: foo\ntitle: x\n---\n",
            encoding="utf-8",
        )
        drafts = tmp / "drafts"; drafts.mkdir()
        out = tmp / "output"; out.mkdir()
        try:
            rc = main([
                "--raw", str(raw),
                "--drafts", str(drafts),
                "--output", str(out),
                "--dry-run",
                "--log-level", "ERROR",
            ])
            self.assertEqual(rc, 2)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
