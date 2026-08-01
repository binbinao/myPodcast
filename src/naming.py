"""统一命名规则。所有路径/文件名都从这里走，禁止在调用点硬编码。

约定：

raw/      → YYYY-MM-DD-slug.md          （作者原文章）
drafts/   → YYYY-MM-DD-slug/ep-XX.md    （一篇文章一个目录，按系列分组）
output/   → series/<series_slug>/ep-XX/  （一档节目一个目录，URL 友好）

slug 与 series_slug 都用 **英文 kebab-case**（ASCII），中文标题通过：
  1. frontmatter 显式 `slug:` / `series_slug:` 优先
  2. 否则 pypinyin 转写（可选依赖；无则降级到时间戳兜底）

文件名示例：
  raw/2026-07-31-when-platform-absorbs-you.md
  drafts/2026-07-31-when-platform-absorbs-you/ep-01.md
  output/series/when-platform-absorbs-you/ep-01/episode.mp3
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any


# ---------- ASCII slug ----------

_ASCII_SLUG_RE = re.compile(r"[^a-z0-9]+")


def ascii_slug(text: str, fallback: str = "untitled") -> str:
    """把任意字符串变成 ASCII kebab-case slug。无 ASCII 时返回 fallback。"""
    s = text.strip().lower()
    s = _ASCII_SLUG_RE.sub("-", s).strip("-")
    return (s[:60] or fallback)


# ---------- pypinyin（可选）----------

def _has_pypinyin() -> bool:
    try:
        import pypinyin  # noqa: F401
        return True
    except ImportError:
        return False


def chinese_to_ascii(text: str) -> str:
    """中文标题 → ASCII slug。优先 pypinyin，无则降级。"""
    if not _has_pypinyin():
        # 兜底：去掉所有非 ASCII 字符
        return ascii_slug(text)
    try:
        from pypinyin import lazy_pinyin, Style
        parts = lazy_pinyin(text, style=Style.NORMAL)
        s = "-".join(parts)
        return ascii_slug(s)
    except Exception:
        return ascii_slug(text)


# ---------- raw ----------

def raw_filename(article_date: str | date | None, title: str, explicit_slug: str | None = None) -> str:
    """生成 raw/ 文件名：YYYY-MM-DD-slug.md。"""
    if isinstance(article_date, date):
        d = article_date.isoformat()
    else:
        d = (article_date or date.today().isoformat())
    slug = explicit_slug or chinese_to_ascii(title)
    return f"{d}-{slug}.md"


# ---------- drafts ----------

def drafts_dir_for(article_date: str | date | None, title: str, explicit_slug: str | None, drafts_root: str = "drafts") -> str:
    """drafts/<YYYY-MM-DD-slug>/ — 一篇文章一个目录。"""
    slug = explicit_slug or chinese_to_ascii(title)
    if isinstance(article_date, date):
        d = article_date.isoformat()
    else:
        d = (article_date or date.today().isoformat())
    return f"{drafts_root}/{d}-{slug}"


def draft_filename(ep_index: int, chapter: str = "") -> str:
    """单集 draft 文件名：ep-XX.md（XX 从 01 开始）。"""
    return f"ep-{ep_index:02d}.md"


# ---------- output（series 嵌套）----------

def series_slug_from(series_title: str, explicit: str | None = None) -> str:
    return explicit or chinese_to_ascii(series_title)


def output_root(out_dir: str = "output") -> str:
    return f"{out_dir}/series"


def ep_output_dir(out_dir: str, series_title: str, ep_index: int, explicit_series_slug: str | None = None) -> str:
    """output/series/<series_slug>/ep-XX/ — 一档节目一个目录。"""
    slug = series_slug_from(series_title, explicit_series_slug)
    return f"{output_root(out_dir)}/{slug}/ep-{ep_index:02d}"


def ep_output_filename() -> str:
    return "episode.mp3"


def shownotes_filename() -> str:
    return "shownotes.md"


# ---------- 反查（兼容旧的 manifest 读法）----------

def parse_legacy_dirname(name: str) -> tuple[str, str] | None:
    """从旧 output 目录名（"系列标题-章节首句"）反推 series 与 chapter。"""
    # 旧规则是 series 标题 + '-' + chapter 首句
    # 没有稳定的分割点，保守返回 None
    return None


# ---------- 辅助：frontmatter 提取 ----------

def pick_slug(meta: dict[str, Any], title: str) -> str:
    """按优先级：meta.slug → meta.series_slug → ascii slug(title)。

    适合 generate / split 场景：slug 优先（文件级 KV）。
    """
    s = meta.get("slug") or meta.get("series_slug")
    if s:
        return ascii_slug(str(s))
    return chinese_to_ascii(title)


def pick_series_slug(meta: dict[str, Any], title: str) -> str:
    """按优先级：meta.series_slug → meta.slug → ascii slug(title)。

    适合 naming_enforce / drafts dir / output series 等"系列目录名"场景：
    series_slug 是 dir 名权威。raw 文件名也走它（与 drafts/output 对齐）。
    """
    s = meta.get("series_slug") or meta.get("slug")
    if s:
        return ascii_slug(str(s))
    return chinese_to_ascii(title)