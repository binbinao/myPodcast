"""命名规则 hard gate：扫 raw/、drafts/、output/series/，把不符合命名约定的自动 rename。

约定（与 src/naming.py pick_series_slug/raw_filename/drafts_dir_for 对齐）：

- raw/<filename>                    := ``YYYY-MM-DD-<slug>.md``
- drafts/<dirname>/<ep-XX.md>      := ``<YYYY-MM-DD>-<slug>/``
- output/series/<dirname>/ep-NN/    := ``<slug>/`` （slug 来自 series_slug）

slug 优先级：``meta.series_slug`` → ``meta.slug`` → ``chinese_to_ascii(title)``。

Destructive 行为是 design，但 git 是兜底——rename 后 ``git status`` 立即可见、
可 ``git checkout`` 回滚。CI 应当 dry-run（fail on divergence，但不要 in-place 修改）。

退出码：
- 0：全部合规
- 1：原状态不合规但已自动修复（实测下不会发生；CLI 是 silent fix）
- 2：CI-only 模式发现不合规且 dry-run 不修改
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

from .log import configure as configure_logging, logger as log
from .naming import pick_series_slug

_RAW_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")
_DRAFT_DIR_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")


def _parse_frontmatter_text(text: str) -> dict[str, Any]:
    """极简 frontmatter 解析：不引 yaml 依赖，容忍常见写法。"""
    out: dict[str, Any] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    in_fm = False
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip()
        if line.strip() == "---":
            if in_fm:
                break
            in_fm = True
            i += 1
            continue
        if in_fm and ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            out[k] = v
        i += 1
    return out


def _read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        return _parse_frontmatter_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def _is_valid_date(s: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", s))


def _expected_raw_slug_and_date(
    meta: dict[str, Any], fallback_title: str,
    fallback_date_from: Path | None = None,
) -> tuple[str, str]:
    """从 frontmatter 推导 (date, slug)。

    日期优先级：
    1. frontmatter ``date``（合法 YYYY-MM-DD）
    2. 物理名/物理目录名前缀（``YYYY-MM-DD-...``），用于 drafts ep 没 date 字段的情况
    3. 今天

    slug 优先级：``meta.series_slug`` → ``meta.slug`` → ``chinese_to_ascii(title)``。
    """
    d = str(meta.get("date", "")).strip()
    if not _is_valid_date(d):
        if fallback_date_from:
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-", fallback_date_from.name)
            if m:
                d = m.group(1)
    if not _is_valid_date(d):
        d = date.today().isoformat()
    slug = pick_series_slug(meta, fallback_title)
    # 如果 slug 已含日期前缀，剥掉（避免 expected_name 重复日期）
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", slug)
    return d, slug


def enforce_raw_files(raw_dir: Path, *, dry_run: bool = False) -> list[tuple[Path, Path]]:
    """扫 ``raw/*.md``，对不合规的物理 rename 到 ``YYYY-MM-DD-<slug>.md``。"""
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        return []
    moves: list[tuple[Path, Path]] = []
    for path in sorted(raw_dir.glob("*.md")):
        meta = _read_frontmatter(path)
        fallback_title = meta.get("title") or path.stem
        expected_date, expected_slug = _expected_raw_slug_and_date(meta, fallback_title)
        expected_name = f"{expected_date}-{expected_slug}.md"
        if path.name == expected_name:
            continue
        target = raw_dir / expected_name
        if target.exists() and target != path:
            log.error(
                "[enforce/raw] 冲突: %s → %s (目标已存在，跳过)",
                path.name, expected_name,
            )
            continue
        log.warning("[enforce/raw] rename: %s → %s", path.name, expected_name)
        moves.append((path, target))
        if not dry_run:
            shutil.move(str(path), str(target))
    return moves


def enforce_drafts_dirs(drafts_dir: Path, *, dry_run: bool = False) -> list[tuple[Path, Path]]:
    """扫 ``drafts/``，把目录名不合规的 mv 到 ``<YYYY-MM-DD>-<slug>/``。"""
    drafts_dir = Path(drafts_dir)
    if not drafts_dir.is_dir():
        return []
    moves: list[tuple[Path, Path]] = []
    for entry in sorted(drafts_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        ep_files = sorted(entry.glob("ep-*.md"))
        if not ep_files:
            continue
        meta = _read_frontmatter(ep_files[0])
        fallback_title = meta.get("series") or meta.get("title") or entry.name
        expected_date, expected_slug = _expected_raw_slug_and_date(
            meta, fallback_title, fallback_date_from=entry,
        )
        expected_name = f"{expected_date}-{expected_slug}"
        if entry.name == expected_name:
            continue
        target = drafts_dir / expected_name
        if target.exists() and target != entry:
            log.error(
                "[enforce/drafts] 冲突: %s → %s (目标已存在，跳过)",
                entry.name, expected_name,
            )
            continue
        log.warning("[enforce/drafts] rename: %s → %s", entry.name, expected_name)
        moves.append((entry, target))
        if not dry_run:
            shutil.move(str(entry), str(target))
    return moves


def enforce_output_series(output_dir: Path, *, dry_run: bool = False) -> list[tuple[Path, Path]]:
    """扫 ``output/series/``，把 series 目录名不合规的 mv。

    output 用 ``manifest.json`` 作为 source of truth：读全局 manifest 的
    ``series_slug`` 字段，定位"应当叫什么"。物理目录名与服务端路径完全一致，
    否则 RSS / 站点 / feed 全部 404。
    """
    output_dir = Path(output_dir)
    series_dir = output_dir / "series"
    if not series_dir.is_dir():
        return []
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        log.warning("[enforce/output] 缺 manifest.json, 跳过 series")
        return []
    try:
        import json
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("[enforce/output] manifest.json 解析失败, 跳过")
        return []

    # 收集当前 series_slug → physical_dir 映射
    moves: list[tuple[Path, Path]] = []
    # 从 episodes 列表里抽（slug, dir_name）映射
    # series_slug 仅决定 manifest 上的 key；物理目录路径由 build.py 写入时确定
    # 同一个 series 在不同 ep 里 series_slug 应一致
    series_seen: dict[str, str] = {}
    for ep in data.get("episodes", []):
        slug = ep.get("series_slug") or ep.get("slug")
        if not slug:
            continue
        if slug not in series_seen:
            series_seen[slug] = slug  # manifest 默认符合

    # 物理目录与 manifest 对照
    for entry in sorted(series_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        physical_name = entry.name
        # 如果 current 已在 manifest 系列 → 一定合规
        if physical_name in series_seen.values():
            continue
        # 找这个目录代表哪个 series_slug：扫其下 ep-XX/shownotes.md 查 frontmatter
        ep_dirs = sorted([d for d in entry.iterdir() if d.is_dir() and d.name.startswith("ep-")])
        canonical: str | None = None
        for ep_dir in ep_dirs:
            sn = ep_dir / "shownotes.md"
            if not sn.is_file():
                continue
            meta = _read_frontmatter(sn)
            canonical = pick_series_slug(meta, meta.get("series") or physical_name)
            if canonical:
                break
        if not canonical or canonical == physical_name:
            continue
        target = series_dir / canonical
        if target.exists() and target != entry:
            log.error(
                "[enforce/output] 冲突: %s/ → %s/ (目标已存在，跳过)",
                physical_name, canonical,
            )
            continue
        log.warning("[enforce/output] rename: %s/ → %s/", physical_name, canonical)
        moves.append((entry, target))
        if not dry_run:
            shutil.move(str(entry), str(target))
    return moves


def enforce_all(
    raw_dir: Path = Path("raw"),
    drafts_dir: Path = Path("drafts"),
    output_dir: Path = Path("output"),
    *,
    dry_run: bool = False,
) -> int:
    """扫描 + 自动 rename 三层（raw/drafts/output/series）。返回 0=pass / 2=CI fail。"""
    log.info("[enforce] raw=%s drafts=%s output=%s dry_run=%s",
             raw_dir, drafts_dir, output_dir, dry_run)
    raw_moves = enforce_raw_files(raw_dir, dry_run=dry_run)
    drafts_moves = enforce_drafts_dirs(drafts_dir, dry_run=dry_run)
    output_moves = enforce_output_series(output_dir, dry_run=dry_run)
    total = len(raw_moves) + len(drafts_moves) + len(output_moves)
    log.info("[enforce] done: %d rename(s)%s",
             total, " (dry-run)" if dry_run else "")
    if dry_run and total > 0:
        return 2  # CI 用：dry_run 但有违规 → fail
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="命名 hard gate：扫 raw/drafts/output/series 把不合规自动 rename"
    )
    ap.add_argument("--raw", default="raw", help="raw 目录 (默认 raw)")
    ap.add_argument("--drafts", default="drafts", help="drafts 目录 (默认 drafts)")
    ap.add_argument("--output", default="output", help="output 目录 (默认 output)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只检视不修改（CI 用）")
    ap.add_argument("--log-level", default="INFO",
                    help="DEBUG/INFO/WARNING/ERROR")
    args = ap.parse_args(argv)
    configure_logging(level=args.log_level)
    return enforce_all(
        Path(args.raw), Path(args.drafts), Path(args.output),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
