"""扫描 raw/ 下文件名，按 frontmatter 里的 series_slug（或 slug）推到
frontmatter-driven 的规范名：YYYY-MM-DD-<canonical-slug>.md。不一致则 git mv。

策略：
- frontmatter 优先级 series_slug → slug → ascii(title)
- canonical 文件名按 raw_filename(article_date, title, explicit_slug)
- 物理 mv 用 `git mv` 保留历史
- 只在文件内容完全不变时执行（git status 会重新计算 diff）
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# 复用项目内命名函数 + frontmatter 解析
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.naming import ascii_slug, chinese_to_ascii, raw_filename  # noqa: E402

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def pick_canonical_slug(meta: dict[str, str], title: str) -> str:
    """命名身份：series_slug 优先 → slug → ascii(title)。"""
    for key in ("series_slug", "slug"):
        v = (meta.get(key) or "").strip()
        if v:
            return ascii_slug(v)
    return chinese_to_ascii(title)


def normalize_file(path: Path, *, dry_run: bool) -> str | None:
    """返回新路径（如需重命名）。内容不变、已是规范名时返回 None。"""
    text = path.read_text(encoding="utf-8")
    meta = parse_frontmatter(text)
    title = (meta.get("title") or path.stem).strip()
    article_date = (meta.get("date") or "").strip() or None
    canonical_slug = pick_canonical_slug(meta, title)
    canonical_name = raw_filename(article_date, title, explicit_slug=canonical_slug)
    canonical_path = path.parent / canonical_name
    if canonical_path == path:
        return None
    if dry_run:
        return canonical_name
    subprocess.run(["git", "mv", str(path), str(canonical_path)], check=True)
    return canonical_name


def main(raw_dir: str, dry_run: bool) -> int:
    raw_path = Path(raw_dir)
    actions: list[tuple[Path, str]] = []
    skips: list[Path] = []
    for f in sorted(raw_path.glob("*.md")):
        if f.name == ".gitkeep":
            continue
        new_name = normalize_file(f, dry_run=dry_run)
        if new_name:
            actions.append((f, new_name))
        else:
            skips.append(f)
    verb = "[DRY] " if dry_run else ""
    print(f"{verb}扫描 {len(skips) + len(actions)} 文件，需要改动 {len(actions)}：")
    for old, new in actions:
        print(f"  mv  {old.name}  →  {new}")
    for s in skips:
        print(f"  ok  {s.name}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="raw")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印改动，不实际 git mv（默认 false = 真执行）",
    )
    args = ap.parse_args()
    sys.exit(main(args.raw_dir, args.dry_run))
