"""对比草稿与上次生成版本的差异。

用法:
    python -m scripts.diff_drafts drafts/2026-07-31-when-platform-absorbs-you
    python -m scripts.diff_drafts drafts/2026-07-31-when-platform-absorbs-you --ref HEAD~1

策略：drafts/ 默认不入 git，所以无法用 git diff。
此脚本用"上次 commit 拷贝"作为基准（如果该文件曾在历史中）；否则用 README 文档中
给出的"上版"快照目录 .workbuddy/drafts_prev/<slug>/ep-XX.md 作 fallback。
"""
from __future__ import annotations

import argparse
import difflib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _try_git_show(ref: str, path: Path) -> str | None:
    """尝试从 git 历史读取文件（drafts/ 不入 git 所以通常 None）。"""
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return None
    r = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ref}:{rel}"],
        capture_output=True, text=True, timeout=5,
    )
    if r.returncode == 0:
        return r.stdout
    return None


def _try_prev_snapshot(slug: str, fname: str) -> str | None:
    """尝试 .workbuddy/drafts_prev/<slug>/<fname>。"""
    p = ROOT / ".workbuddy" / "drafts_prev" / slug / fname
    return p.read_text(encoding="utf-8") if p.exists() else None


def _save_snapshot(slug: str) -> int:
    """备份当前 drafts/<slug>/ 到 .workbuddy/drafts_prev/<slug>/。返回文件数。"""
    src = ROOT / "drafts" / slug
    if not src.exists():
        return 0
    dst = ROOT / ".workbuddy" / "drafts_prev" / slug
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return sum(1 for _ in dst.glob("*.md"))


def diff_one(slug: str, fname: str, ref: str = "HEAD") -> tuple[str, str | None, str]:
    """返回 (filename, old_text, new_text)；old_text 可能为 None（无基准）。"""
    new_p = ROOT / "drafts" / slug / fname
    new_text = new_p.read_text(encoding="utf-8")
    old = _try_git_show(ref, new_p)
    if old is None:
        old = _try_prev_snapshot(slug, fname)
    return fname, old, new_text


def main() -> None:
    ap = argparse.ArgumentParser(description="对比 drafts/ 与上次版本的差异")
    ap.add_argument("draft_dir", help="drafts/<slug>/ 路径（脚本相对路径或绝对）")
    ap.add_argument("--ref", default="HEAD", help="git 历史参考点（默认 HEAD）")
    ap.add_argument("--save-snapshot", action="store_true",
                    help="把当前 drafts 当作基准备份到 .workbuddy/drafts_prev/<slug>/")
    args = ap.parse_args()

    target = Path(args.draft_dir)
    if target.is_absolute():
        slug = target.name
    else:
        # 接受 drafts/2026-07-31-foo 或 2026-07-31-foo
        slug = target.name

    if args.save_snapshot:
        n = _save_snapshot(slug)
        print(f"✓ 已备份 {n} 个文件到 .workbuddy/drafts_prev/{slug}/")
        return

    src = ROOT / "drafts" / slug
    if not src.exists():
        print(f"✗ {src} 不存在", file=sys.stderr)
        sys.exit(1)

    files = sorted(src.glob("*.md"))
    if not files:
        print(f"⚠ {src} 下没有 draft")
        return

    has_changes = False
    for f in files:
        fname, old, new = diff_one(slug, f.name, args.ref)
        if old is None:
            print(f"\n=== {fname} === (无基准，新文件)")
            print(new[:300] + ("…" if len(new) > 300 else ""))
            continue
        if old == new:
            continue
        has_changes = True
        diff = difflib.unified_diff(
            old.splitlines(), new.splitlines(),
            fromfile=f"prev/{fname}", tofile=f"new/{fname}",
            lineterm="",
        )
        print(f"\n=== {fname} ===")
        for line in diff:
            print(line)

    if not has_changes:
        print(f"✓ {slug} 无变更")


if __name__ == "__main__":
    main()