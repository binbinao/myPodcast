"""系列上下文：节目身份 + 系列大纲 + 跨集承接 → 单集注入块。

为什么需要（REQ-01 / issue #3）
-------------------------------
prepare 逐集独立调 LLM：system prompt 只有「你是播客文案编辑…」，user 只有本集正文。
模型不知道节目叫什么、不知道系列里有几集、不知道上一集讲到哪里 —— 于是：

- 每集开场互相不认识，重复自我介绍；
- 跨集指代靠猜（"上期我们聊了…"其实是模型编的），预告漂移；
- 同一系列各集深浅不一（有的复述背景，有的直接上结论）。

本模块只负责「把系列变成显式输入」这一层：

- previous_tail —— 读第 N−1 集 draft 的结尾（**从磁盘截断**，不额外调模型）；
- compose_context —— 纯拼装注入 system prompt 的文本块；
- context_for_episode —— 读盘 + 拼装的入口，返回 SeriesContext。

大纲的读写/解析/指纹在 src/outline.py；覆盖策略与落盘在 src/episodes.py。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .naming import draft_filename
from .outline import Outline
from .split import EpisodePlan, _body_without_frontmatter, _strip_md

# 上一集结尾注入的字符预算（票面 600–800，取中位）。够模型接住语气与落点，
# 又不至于把上一集正文整段塞进 prompt。
PREV_TAIL_CHARS = 700


def previous_tail(out_dir: Path | str, index: int, chars: int = PREV_TAIL_CHARS) -> str:
    """第 index−1 集 draft 的结尾（去掉 frontmatter 与 markdown 标记）。

    从磁盘读，不调模型：上一集可能是人手改过的，读盘才能与最终稿一致。
    """
    if index <= 1:
        return ""
    path = Path(out_dir) / draft_filename(index - 1)
    if not path.is_file():
        return ""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    body = _strip_md(_body_without_frontmatter(raw)).strip()
    body = re.sub(r"\[host\]\s*", "主播：", body)
    body = re.sub(r"\[guest\]\s*", "嘉宾：", body)
    body = re.sub(r"\n{2,}", "\n", body)
    if not body:
        return ""
    if len(body) <= chars:
        return body
    cut = body[-chars:]
    # 从句子边界起切，别让注入内容从半句话开始（"…那一刻他决定"）。
    m = re.search(r"[。！？!?…]", cut)
    if m and m.end() < len(cut) - 40:
        cut = cut[m.end():]
    return "…" + cut.strip()


def compose_context(
    plan: EpisodePlan,
    outline: Outline,
    brief: str,
    prev_tail: str,
    next_chapter: str = "",
) -> str:
    """组装注入 system prompt 的上下文块（只给信息，写作要求集中在末尾）。"""
    parts: list[str] = [
        "【系列上下文】以下信息只用于保证跨集连贯：不要把这些标题或要求原样写进正文。"
    ]
    if brief:
        parts.append("【节目身份】\n" + brief)
    if outline.summary:
        parts.append("【系列总纲】\n" + outline.summary)
    pos = f"第 {plan.index} 集 / 共 {plan.total} 集：{plan.chapter}"
    entry = outline.entry(plan.index)
    if entry:
        parts.append(f"【本集位置】{pos}\n本集要点：{entry}")
    else:
        parts.append(
            f"【本集位置】{pos}\n本集要点：大纲未给出，按章节名与正文自行判断，不要与相邻集抢内容。"
        )
    if plan.index == 1:
        parts.append(
            "【上一集】无 —— 本集是系列第一集：用一两句话介绍一次节目（谁做的、讲什么、什么节奏）。"
            "之后各集都不再自我介绍，也不要重述整个系列主题。"
        )
    elif prev_tail:
        parts.append(
            "【上一集结尾】\n" + prev_tail
            + "\n（接着这段往下讲，让听众知道自己在系列里的位置；不要整段复述。）"
        )
    else:
        parts.append("【上一集结尾】无（上一集稿不在或为空）：按大纲承接，不要编造上一集的具体内容。")
    if plan.index < plan.total:
        nxt = outline.topic(plan.index + 1, next_chapter)
        if nxt:
            parts.append(
                f"【下一集主题】第 {plan.index + 1} 集：{nxt}"
                "（本集结尾可以自然引一句，不要展开，也不要编造大纲以外的内容。）"
            )
        else:
            parts.append("【下一集】有，但大纲没给出主题：做自然收束即可，不要预告具体内容。")
    else:
        parts.append(
            "【下一集】无 —— 本集是系列最后一集：做自然收束即可（回扣本集主题、给出可行动的结论），"
            "不要预告下一集，也不要编造后续内容。"
        )
    parts.append(
        "【写作纪律】\n"
        "- 不要每集重复介绍节目，不要重述整个系列主题。\n"
        "- 不要把「大纲」「提示词」「这一集」等制作流程用语写进正文。\n"
        "- 承接与预告只能用上面给出的信息，不要自行编造。"
    )
    return "\n\n".join(parts)


@dataclass(frozen=True)
class SeriesContext:
    """传给 generate 的单集系列上下文 + 大纲指纹（写入 draft frontmatter）。"""

    block: str
    outline_sha: str = ""


def context_for_episode(
    plan: EpisodePlan,
    outline: Outline,
    brief: str,
    out_dir: Path | str,
    next_chapter: str = "",
) -> SeriesContext:
    prev = previous_tail(out_dir, plan.index)
    block = compose_context(plan, outline, brief, prev, next_chapter=next_chapter)
    return SeriesContext(block=block, outline_sha=outline.sha)
