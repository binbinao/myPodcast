"""prepare：原始文章 → 分集 → 脚本 → drafts/（评审门）。

用法:
    python -m src.prepare                 # 处理 raw/ 下所有文章
    python -m src.prepare --article raw/foo.md
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from .generate import draft_dir_for, draft_filename, generate_script
from .ingest import parse_script, slugify
from .split import plan_episodes

H1_RE = re.compile(r"^#\s+(.+)$", re.M)


def _article_meta(article: str, path: Path, fmt_default: str) -> tuple[str, str, int | None]:
    meta, _ = parse_script(article)
    title = meta.get("title") or (H1_RE.search(article) and H1_RE.search(article).group(1).strip())
    if not title:
        title = path.stem
    fmt = str(meta.get("format", fmt_default)).lower()
    if fmt not in ("solo", "duo"):
        fmt = fmt_default
    episodes = meta.get("episodes")
    if episodes is not None:
        try:
            episodes = int(episodes)
        except (TypeError, ValueError):
            episodes = None
    return title, fmt, episodes


def prepare_file(path: Path, cfg: dict[str, Any], drafts_dir: Path) -> list[Path]:
    article = path.read_text(encoding="utf-8")
    fmt_default = str(cfg.get("format", "duo")).lower()
    series_title, fmt, episodes = _article_meta(article, path, fmt_default)
    plans = plan_episodes(article, cfg, series_title, fmt, episodes)
    out_dir = Path(draft_dir_for(series_title, str(drafts_dir)))
    made: list[Path] = []
    for plan in plans:
        script = generate_script(plan, cfg)
        f = out_dir / draft_filename(plan)
        f.write_text(script, encoding="utf-8")
        made.append(f)
    print(f"  {path.name} → 《{series_title}》{len(plans)} 集 → {out_dir}")
    return made


def run(raw_dir: Path, drafts_dir: Path, config_path: Path, article: Path | None = None) -> None:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    drafts_dir = Path(drafts_dir)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    if article:
        prepare_file(Path(article), cfg, drafts_dir)
        return
    raw_dir = Path(raw_dir)
    files = sorted(raw_dir.glob("*.md"))
    if not files:
        print(f"⚠ raw/ 下没有 markdown 文章（{raw_dir}）")
        return
    total = 0
    for f in files:
        total += len(prepare_file(f, cfg, drafts_dir))
    print(f"\n✓ 生成 {total} 个草稿脚本到 {drafts_dir}/（审完用 build 生成音频）")


def main() -> None:
    ap = argparse.ArgumentParser(description="myPodcast prepare: 文章→分集脚本")
    ap.add_argument("--article", help="只处理单个文章")
    ap.add_argument("--raw", default="raw", help="原始文章目录 (默认 raw)")
    ap.add_argument("--drafts", default="drafts", help="草稿输出目录 (默认 drafts)")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    art = Path(args.article) if args.article else None
    run(Path(args.raw), Path(args.drafts), Path(args.config), art)


if __name__ == "__main__":
    main()
