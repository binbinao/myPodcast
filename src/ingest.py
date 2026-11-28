"""解析播客脚本：frontmatter 元数据 + [角色] 标签分段。"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .naming import ascii_slug, chinese_to_ascii

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
TAG_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


def parse_script(text: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """返回 (metadata, segments)。segments: [{role, text}]。

    防御：frontmatter YAML 解析失败时 **log warning** 而不是静默吞错——
    之前静默处理导致整集 meta 空、build 把 output 写到 `series/<path.stem>/ep-01/`
    的诡异路径还不报错（2026-08-02 跨境电商 ep-13 翻车）。
    """
    from .log import logger as log
    meta: dict[str, Any] = {}
    body = text
    m = FRONTMATTER_RE.match(text)
    if m:
        try:
            loaded = yaml.safe_load(m.group(1))
            meta = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError as e:
            log.warning(f"frontmatter YAML 解析失败（meta 置空）: {str(e).splitlines()[0]}")
            meta = {}
        body = m.group(2)

    segments: list[dict[str, str]] = []
    current_role: str | None = None
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        tag = TAG_RE.match(line)
        if tag:
            current_role = tag.group(1).strip().lower()
            content = tag.group(2).strip()
        else:
            content = line.strip()
            if current_role is None:
                current_role = "default"
        if content:
            segments.append({"role": current_role, "text": content})
    return meta, segments


def load_episode(path: str | Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    return parse_script(Path(path).read_text(encoding="utf-8"))


H1_RE = re.compile(r"^#\s+(.+)$", re.M)


def article_meta(
    article: str, path: Path, fmt_default: str
) -> tuple[str, str, int | None, str, str]:
    """读文章级 frontmatter，返回 (title, format, episodes_n, article_date, slug)。

    slug 优先 frontmatter series_slug → slug → 从 raw 文件名（去掉日期前缀）兜底。
    **不走 chinese_to_ascii(title)** —— 2026-08-02 拍板，pipeline 不越权决定命名。
    """
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
    # 日期：优先 frontmatter date → 否则从 raw 文件名 YYYY-MM-DD- 抽 → 否则今日
    art_date = str(meta.get("date") or "")
    if not art_date:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-", path.stem)
        if m:
            art_date = m.group(1)
    if not art_date:
        art_date = date.today().isoformat()
    explicit_slug = (
        str(meta.get("series_slug") or "").strip()
        or str(meta.get("slug") or "").strip()
    )
    if not explicit_slug:
        m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", path.stem)
        if m:
            explicit_slug = m.group(1).strip()
    return title, fmt, episodes, art_date, explicit_slug


def duo_voices_from_meta(meta: dict[str, Any]) -> tuple[str, str]:
    """从 frontmatter 解析 duo 的 host/guest 音色，返回 (host, guest)。

    两个来源，显式键优先：host_voice/guest_voice，或 voice 标签 "host=X / guest=Y"
    （decisions.py 的交互门正是按后者写的）。只认键不认标签会让三件套齐全的 raw
    静默丢音色（2026-09-21 回归）。
    """
    host = str(meta.get("host_voice") or "").strip()
    guest = str(meta.get("guest_voice") or "").strip()
    if not (host and guest):
        m = re.search(
            r"host\s*=\s*([^\s/]+)\s*/\s*guest\s*=\s*([^\s/]+)",
            str(meta.get("voice") or ""),
        )
        if m:
            host = host or m.group(1)
            guest = guest or m.group(2)
    return host, guest


# 兼容旧 import：返回 ASCII kebab-case slug（不再保留中文）
def slugify(title: str) -> str:
    """ASCII kebab-case slug。中文标题会转拼音（无 pypinyin 时降级）。"""
    return chinese_to_ascii(title)
