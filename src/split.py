"""分集切分：把一篇文章按章节/长度拆成若干集计划。

规则：
- 按 H2 切章节；无 H2 则整体为一集。
- 单章超过 max_episode_chars 时，再按 H3 切；仍超长则按段落窗口切。
- 过小的章节（< min_episode_chars）合并进上一集，避免一堆碎集。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

H2_RE = re.compile(r"^##\s+(.+)$", re.M)
H3_RE = re.compile(r"^###\s+(.+)$", re.M)


@dataclass
class EpisodePlan:
    index: int
    total: int
    title: str        # 集标题（系列 + 章节）
    series: str       # 系列 / 节目名
    chapter: str      # 章节名
    body: str         # 待转口播的正文
    format: str = "duo"  # solo / duo


def _strip_md(text: str) -> str:
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)        # 图片
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)        # 链接保留文字
    t = re.sub(r"[#*`>_~|]", "", t)                       # markdown 符号
    return t


def _count(text: str) -> int:
    return len(_strip_md(text).strip())


def _sections(article: str) -> list[tuple[str, str]]:
    """返回 [(章节名, 正文)]，按 H2 切；无 H2 则整体为 1 段。"""
    lines = article.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    body = "\n".join(lines[start:])
    parts = H2_RE.split(body)
    chunks: list[tuple[str, str]] = []
    intro = re.sub(r"^#\s+.*$", "", parts[0], flags=re.M).strip()
    if intro:
        chunks.append(("引言", intro))
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        text = parts[i + 1].strip() if i + 1 < len(parts) else ""
        chunks.append((name, text))
    if not chunks:
        chunks = [("全文", body.strip())]
    return chunks


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


def plan_episodes(
    article: str, cfg: dict[str, Any], series_title: str, fmt: str
) -> list[EpisodePlan]:
    split_cfg = cfg.get("split", {})
    min_c = split_cfg.get("min_episode_chars", 600)
    max_c = split_cfg.get("max_episode_chars", 3000)

    sections = _sections(article)

    # 引言过短且有正文章节时，并入第一章，避免单独碎集
    if len(sections) > 1 and sections[0][0] == "引言" and _count(sections[0][1]) < min_c:
        _, text0 = sections[0]
        name1, text1 = sections[1]
        sections = [(name1, f"{text0}\n\n{text1}")] + sections[2:]

    episodes: list[tuple[str, str]] = []
    if len(sections) == 1:
        # 单块：按长度切
        name, text = sections[0]
        if _count(text) <= max_c:
            episodes.append((name, text))
        else:
            for sub in _split_long(text, max_c):
                episodes.append((name, sub))
    else:
        # 多章节：每章独立成一集；超长单章再细分
        for name, text in sections:
            if _count(text) <= max_c:
                episodes.append((name, text))
            else:
                for sub in _split_long(text, max_c):
                    episodes.append((name, sub))

    total = len(episodes)
    plans: list[EpisodePlan] = []
    for i, (name, text) in enumerate(episodes, 1):
        plans.append(
            EpisodePlan(
                index=i,
                total=total,
                title=f"{series_title} · {name}" if total > 1 else series_title,
                series=series_title,
                chapter=name,
                body=text,
                format=fmt,
            )
        )
    return plans
