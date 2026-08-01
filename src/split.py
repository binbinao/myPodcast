"""分集切分：把一篇文章按章节/长度拆成若干集计划。

规则（v2，兼容性更强）：
- 先清洗：去掉 HTML 注释、围栏代码块(mermaid)、图片、图注、以及已知写作元数据段落。
- 章节边界优先级：
  1. 若存在多个非元数据的 `## ` 章节 → 每章一集（多章节不合并）。
  2. 否则若正文用 `---` 分割线分节 → 按 `---` 切块，再按 episodes 数均分组合。
  3. 否则整体一集（超长再细切）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

H2_RE = re.compile(r"^##\s+(.+)$", re.M)
H3_RE = re.compile(r"^###\s+(.+)$", re.M)
HR_RE = re.compile(r"^-{3,}\s*$", re.M)
H1_RE = re.compile(r"^#\s+(.+)$", re.M)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
FENCE_RE = re.compile(r"```.*?```", re.S)
IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
FIGCAP_RE = re.compile(r"^\*\s*图[^*\n]*\*\s*$", re.M)

DEFAULT_META_SECTIONS = ["Metadata", "未验证项汇总表", "视觉汇总"]


@dataclass
class EpisodePlan:
    index: int
    total: int
    title: str        # 集标题（系列 + 章节）
    series: str       # 系列 / 节目名
    series_slug: str  # 系列英文 slug（用于 output 路径）
    chapter: str      # 章节名
    body: str         # 待转口播的正文
    format: str = "duo"  # solo / duo
    article_date: str = ""   # 文章日期（YYYY-MM-DD），用于 drafts 目录


# ---------- 清洗 ----------

def clean_article(text: str, meta_sections: list[str] | None = None) -> str:
    """去除不适合朗读/切分的元素。meta_sections 用于后续丢弃元段落。"""
    t = COMMENT_RE.sub("", text)      # HTML 注释
    t = FENCE_RE.sub("", t)           # 代码块 / mermaid
    t = IMG_RE.sub("", t)             # 图片
    t = FIGCAP_RE.sub("", t)          # 图注 *图：...*
    t = H1_RE.sub("", t)              # 文档 H1 标题（系列名另取，不进正文）
    return t


def _strip_md(text: str) -> str:
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[#*`>_~|]", "", t)
    return t


def _count(text: str) -> int:
    return len(_strip_md(text).strip())


def _body_without_frontmatter(article: str) -> str:
    lines = article.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    return "\n".join(lines[start:])


# ---------- 切块 ----------

def _h2_content_sections(body: str, meta_sections: set[str]) -> list[tuple[str, str]]:
    """按 ## 切，丢弃元段落，返回 [(章节名, 正文)]。"""
    parts = H2_RE.split(body)
    chunks: list[tuple[str, str]] = []
    intro = re.sub(r"^#\s+.*$", "", parts[0], flags=re.M).strip()
    if intro:
        chunks.append(("引言", intro))
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        text = parts[i + 1].strip() if i + 1 < len(parts) else ""
        chunks.append((name, text))
    kept = [(n, t) for (n, t) in chunks if n not in meta_sections]
    return kept


def _split_on_hr(body: str) -> list[str]:
    return [p.strip() for p in HR_RE.split(body)]


def _drop_meta_blocks(blocks: list[str], meta_sections: set[str]) -> list[str]:
    out = []
    for b in blocks:
        m = H2_RE.match(b.strip())
        if m and m.group(1).strip() in meta_sections:
            continue
        if b.strip():
            out.append(b)
    return out


def _auto_title(block: str, fallback: str) -> str:
    txt = _strip_md(block).strip()
    lines = [l for l in txt.splitlines() if l.strip()]
    if not lines:
        return fallback
    first = lines[0]
    parts = re.split(r"(?<=[。！？])", first, maxsplit=1)
    title = parts[0].strip()
    if not title:
        title = first.strip()
    if len(title) > 24:
        title = title[:24] + "…"
    return title or fallback


def _group_even(items: list, k: int) -> list[list]:
    n = len(items)
    k = max(1, min(k, n))
    base, rem = divmod(n, k)
    groups: list[list] = []
    idx = 0
    for i in range(k):
        size = base + (1 if i < rem else 0)
        groups.append(items[idx:idx + size])
        idx += size
    return groups


def _split_long(text: str, max_chars: int) -> list[str]:
    sub = H3_RE.split(text)
    pieces: list[str] = []
    if len(sub) > 1:
        head = sub[0].strip()
        if head:
            pieces.append(head)
        for i in range(1, len(sub), 2):
            title = sub[i]
            rest = sub[i + 1] if i + 1 < len(sub) else ""
            pieces.append(f"{title}\n{rest}".strip())
    else:
        pieces = [text]

    out: list[str] = []
    for p in pieces:
        if _count(p) <= max_chars:
            out.append(p.strip())
            continue
        paras = [x for x in p.split("\n\n") if x.strip()]
        buf = ""
        for para in paras:
            if buf and _count(buf) + _count(para) > max_chars:
                out.append(buf.strip())
                buf = para
            else:
                buf = (buf + "\n\n" + para).strip() if buf else para
        if buf:
            out.append(buf.strip())
    return [x for x in out if x.strip()]


# ---------- 主入口 ----------

def plan_episodes(
    article: str,
    cfg: dict[str, Any],
    series_title: str,
    fmt: str,
    episodes: int | None = None,
    series_slug: str = "",
    article_date: str = "",
) -> list[EpisodePlan]:
    split_cfg = cfg.get("split", {})
    min_c = split_cfg.get("min_episode_chars", 600)
    max_c = split_cfg.get("max_episode_chars", 3000)
    meta = set(split_cfg.get("meta_sections", DEFAULT_META_SECTIONS))

    body = _body_without_frontmatter(article)
    cleaned = clean_article(body, list(meta))

    h2 = _h2_content_sections(cleaned, meta)
    if len(h2) >= 2:
        mode = "h2"
    else:
        hr_blocks = _drop_meta_blocks(_split_on_hr(cleaned), meta)
        mode = "hr" if len(hr_blocks) >= 2 else "single"

    # 组装 (章节名, 正文) 列表
    if mode == "h2":
        sections = h2
        if len(sections) > 1 and sections[0][0] == "引言" and _count(sections[0][1]) < min_c:
            _, t0 = sections[0]
            n1, t1 = sections[1]
            sections = [(n1, f"{t0}\n\n{t1}")] + sections[2:]
        pairs: list[tuple[str, str]] = []
        for name, text in sections:
            if _count(text) <= max_c:
                pairs.append((name, text))
            else:
                for sub in _split_long(text, max_c):
                    pairs.append((name, sub))
    elif mode == "hr":
        hr_blocks = _drop_meta_blocks(_split_on_hr(cleaned), meta)
        titles = [_auto_title(b, f"第{i+1}部分") for i, b in enumerate(hr_blocks)]
        k = episodes or len(hr_blocks)
        groups = _group_even(list(range(len(hr_blocks))), k)
        pairs = []
        for g in groups:
            combined = "\n\n".join(hr_blocks[i] for i in g)
            pairs.append((titles[g[0]], combined))
    else:
        text = cleaned.strip()
        if _count(text) <= max_c:
            pairs = [("全文", text)]
        else:
            pairs = [("全文", sub) for sub in _split_long(text, max_c)]

    total = len(pairs)
    plans: list[EpisodePlan] = []
    for i, (name, text) in enumerate(pairs, 1):
        plans.append(
            EpisodePlan(
                index=i,
                total=total,
                title=f"{series_title} · {name}" if total > 1 else series_title,
                series=series_title,
                series_slug=series_slug,
                chapter=name,
                body=text,
                format=fmt,
                article_date=article_date,
            )
        )
    return plans
