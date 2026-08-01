#!/usr/bin/env python3
"""一次性迁移脚本：把现状 raw/ + drafts/ + output/ 重命名为新结构。

- raw 文件名 → YYYY-MM-DD-slug.md
- raw frontmatter 加 slug / series_slug 字段（中文 → pypinyin slug）
- drafts 目录 → drafts/<YYYY-MM-DD-slug>/ep-XX.md（按文章分组，不再按 series）
- drafts frontmatter 加 series_slug
- output → output/series/<series_slug>/ep-XX/episode.mp3 + shownotes.md
- manifest.json 重写为新 schema（series_slug 是主键的一部分）

运行：
  python scripts/migrate_naming.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

# 让脚本能 import src 模块
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml

from src.naming import chinese_to_ascii


def _read_yaml(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    body = text[3:]
    if "---" not in body:
        return {}
    fm = body.split("---", 1)[0]
    try:
        return yaml.safe_load(fm) or {}
    except yaml.YAMLError:
        return {}


def _write_yaml(path: Path, meta: dict, body: str) -> None:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, str):
            lines.append(f'{k}: "{v}"')
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    path.write_text("\n".join(lines), encoding="utf-8")


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    rest = text[3:]
    if "---" not in rest:
        return {}, text
    fm_text, body = rest.split("---", 1)
    meta = yaml.safe_load(fm_text) or {}
    return meta, body.lstrip("\n")


def _article_date_from(path: Path, meta: dict) -> str:
    d = meta.get("date")
    if d:
        return str(d)
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-", path.stem)
    if m:
        return m.group(1)
    return date.today().isoformat()


def _series_slug(meta: dict, title: str) -> str:
    s = meta.get("series_slug") or meta.get("slug")
    if s:
        return chinese_to_ascii(str(s))
    return chinese_to_ascii(title)


# ---------- 1) raw 文件名迁移 ----------

def migrate_raw(raw_dir: Path) -> None:
    print("\n[1] 迁移 raw/")
    for f in sorted(raw_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        meta, body = _split_frontmatter(text)
        title = meta.get("title") or f.stem.split("-", 1)[-1].replace("-", " ")
        art_date = _article_date_from(f, meta)
        slug = chinese_to_ascii(title)
        new_name = f"{art_date}-{slug}.md"
        new_path = raw_dir / new_name
        # 写 frontmatter（加 slug 字段）
        meta["slug"] = slug
        if "title" not in meta:
            meta["title"] = title
        if new_path.exists() and new_path != f:
            print(f"  ⚠ {new_name} 已存在，跳过 {f.name}")
            continue
        _write_yaml(new_path, meta, body)
        if new_path != f:
            f.unlink()
            print(f"  ✓ {f.name} → {new_name}")


# ---------- 2) drafts 重组 ----------

def migrate_drafts(drafts_dir: Path) -> None:
    print("\n[2] 迁移 drafts/")
    # 先收集所有 draft，按 series 重组为按 article_date 分组
    # 旧：drafts/<series_slug>/ep-XX.md
    # 新：drafts/<YYYY-MM-DD-slug>/ep-XX.md
    # 关键：series_slug 是 series 的唯一标识；draft 当前 frontmatter 没 series_slug 时
    # 从 series 字段重新生成
    series_to_articles: dict[str, list[tuple[Path, dict]]] = {}
    for old_dir in sorted(drafts_dir.iterdir()):
        if not old_dir.is_dir():
            continue
        for md in sorted(old_dir.glob("*.md")):
            text = md.read_text(encoding="utf-8")
            meta, _ = _split_frontmatter(text)
            series_slug = _series_slug(meta, meta.get("series", ""))
            meta["series_slug"] = series_slug
            series_to_articles.setdefault(series_slug, []).append((md, meta))

    # 给每个 series 找一个 article_date（用最早一集对应 raw 的 date）
    # 简化：取 series 第一集的 source 路径对应的 raw 文件 date
    raw_dir = ROOT / "raw"
    for series_slug, items in series_to_articles.items():
        first_meta = items[0][1]
        art_date = str(first_meta.get("article_date") or first_meta.get("date") or "")
        if not art_date:
            # 从 source 字段找
            src = first_meta.get("source", "")
            if src:
                src_path = Path(src)
                if src_path.exists():
                    rt = src_path.read_text(encoding="utf-8")
                    rmeta, _ = _split_frontmatter(rt)
                    art_date = _article_date_from(src_path, rmeta)
        if not art_date:
            art_date = date.today().isoformat()
        # series 标题
        series_title = first_meta.get("series", series_slug)
        # 新目录名
        new_dir_name = f"{art_date}-{series_slug}"
        new_dir = drafts_dir / new_dir_name
        new_dir.mkdir(parents=True, exist_ok=True)
        # 排序并写文件
        items.sort(key=lambda kv: int(kv[1].get("episode", 1) or 1))
        for md, meta in items:
            ep_index = int(meta.get("episode", 1) or 1)
            new_path = new_dir / f"ep-{ep_index:02d}.md"
            # 写 frontmatter（保 series_slug 字段）
            if "series_slug" not in meta:
                meta["series_slug"] = series_slug
            text = md.read_text(encoding="utf-8")
            _, body = _split_frontmatter(text)
            _write_yaml(new_path, meta, body)
            md.unlink()
            print(f"  ✓ {md.parent.name}/{md.name} → {new_dir_name}/{new_path.name}")
        # 删空旧目录
        try:
            old_dir.rmdir()
        except OSError:
            pass


# ---------- 3) output 重组 ----------

def migrate_output(out_dir: Path) -> None:
    print("\n[3] 迁移 output/")
    series_root = out_dir / "series"
    series_root.mkdir(exist_ok=True)
    for old_dir in sorted(out_dir.iterdir()):
        if not old_dir.is_dir():
            continue
        if old_dir.name in ("series",):
            continue
        if not (old_dir / "episode.mp3").exists():
            continue
        # 旧目录名是 series 全标题 + "-" + chapter；manifest 没有 series_slug 字段
        # 只能从 manifest.json 旧条目反查，但旧条目已被覆盖——保守做法：
        # 把每个旧目录平铺到 series/<series_slug>/ep-NN/，series_slug 暂用拼音
        text_title = old_dir.name
        # 优先从 shownotes.md 拿 series
        sn = old_dir / "shownotes.md"
        series_title = ""
        ep_index = 1
        if sn.exists():
            sn_text = sn.read_text(encoding="utf-8")
            m = re.search(r"^# (.+)$", sn_text, re.M)
            if m:
                series_title = m.group(1).split(" · ")[0].strip()
            # 从文件名规则看，episode.mp3 没有 ep- 编号；从 shownotes 拿不到 ep_index
            # 取旧目录名尾部数字（如果有）
            m2 = re.search(r"第 (\d+)/", sn_text)
            if m2:
                ep_index = int(m2.group(1))
        if not series_title:
            # 兜底：拿当前目录名作 series 标题
            series_title = text_title.split("-")[0]
        series_slug = chinese_to_ascii(series_title)
        new_series = series_root / series_slug
        new_series.mkdir(exist_ok=True)
        new_ep = new_series / f"ep-{ep_index:02d}"
        new_ep.mkdir(exist_ok=True)
        # 移动 mp3 + shownotes
        for f in old_dir.iterdir():
            shutil.move(str(f), str(new_ep / f.name))
        # 删空旧目录
        try:
            old_dir.rmdir()
        except OSError:
            pass
        print(f"  ✓ {old_dir.name} → series/{series_slug}/ep-{ep_index:02d}/")


# ---------- 4) manifest 重建 ----------

def rebuild_manifest(out_dir: Path) -> None:
    print("\n[4] 重建 manifest.json")
    series_root = out_dir / "series"
    if not series_root.exists():
        return
    today = date.today().isoformat()
    new_entries = []
    for series_dir in sorted(series_root.iterdir()):
        if not series_dir.is_dir():
            continue
        series_slug = series_dir.name
        for ep_dir in sorted(series_dir.iterdir()):
            if not ep_dir.is_dir() or not ep_dir.name.startswith("ep-"):
                continue
            mp3 = ep_dir / "episode.mp3"
            sn = ep_dir / "shownotes.md"
            if not mp3.exists():
                continue
            ep_index = int(ep_dir.name.split("-")[1])
            # 从 shownotes 抽 series 标题
            series_title = series_slug
            if sn.exists():
                st = sn.read_text(encoding="utf-8")
                m = re.search(r"^# (.+)$", st, re.M)
                if m:
                    series_title = m.group(1).split(" · ")[0].strip()
            # 时长
            import subprocess
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(mp3)],
                capture_output=True, text=True,
            )
            try:
                dur = int(float(r.stdout.strip()))
            except ValueError:
                dur = 0
            size = mp3.stat().st_size
            new_entries.append({
                "_key": f"{series_slug}::ep-{ep_index:02d}",
                "slug": series_slug,
                "ep_index": ep_index,
                "title": series_title,
                "description": f"《{series_title}》第 {ep_index} 集",
                "date": today,
                "created": today,
                "updated": today,
                "duration": dur,
                "size": size,
                "url": f"series/{series_slug}/ep-{ep_index:02d}/episode.mp3",
                "series": series_title,
                "episode": ep_index,
                "total": 0,
                "format": "duo",
                "chapter": "",
                "voice": "",
            })
    out_path = out_dir / "manifest.json"
    out_path.write_text(
        json.dumps({"episodes": new_entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  ✓ {len(new_entries)} episodes")


def main() -> None:
    raw_dir = ROOT / "raw"
    drafts_dir = ROOT / "drafts"
    out_dir = ROOT / "output"
    print(f"ROOT = {ROOT}")
    migrate_raw(raw_dir)
    migrate_drafts(drafts_dir)
    migrate_output(out_dir)
    rebuild_manifest(out_dir)
    print("\n✓ 迁移完成。请手动验证后用 build 重跑一遍。")


if __name__ == "__main__":
    main()