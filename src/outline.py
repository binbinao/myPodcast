"""系列大纲：一份可手改、只读复用的「系列总纲 + 每集论点」。

为什么需要（REQ-01 / issue #3）
-------------------------------
prepare 逐集独立调 LLM：system prompt 只有「你是播客文案编辑…」，user 只有本集正文。
模型不知道节目叫什么、不知道系列里有几集、不知道上一集讲到哪里 —— 于是每集开场
互相不认识、承接靠猜、预告会漂。

系列大纲把「整个系列讲什么」提前定下来：**一次**模型调用覆盖全篇，落
``drafts/<系列>/outline.md``，之后只读。人手改大纲即改行为，不必改代码。

格式（``coerce_outline`` 会把模型输出整成这个形状）::

    # 系列大纲：<系列名>

    ## 系列总纲
    3–5 行：整体讲什么、脉络怎么推进。

    ## 第 1 集：<章节名>
    本集核心论点；与上一集的承接；给下一集留的引子。

解析对人气宽容：``## 第 2 集 x`` / ``## ep-02 x`` 都认（见 ``_ENTRY_RE``）。

约定：outline.md 只做生成阶段的上下文，不进 build（build 只收 ep-XX.md）。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm import llm_complete, resolve_api_key
from .log import logger as log
from .split import EpisodePlan, FENCE_RE, _strip_md

OUTLINE_FILENAME = "outline.md"

# draft frontmatter 里记录「本集基于哪一版大纲」的字段名。生成侧写、prepare 读，
# build 不消费。集中定义，避免字面量散落在 generate / prepare / docs 里漂移。
OUTLINE_SHA_KEY = "series_outline_sha"

# 生成大纲时每集正文只采样开头：给模型"这一集讲什么"的钩子，不喂全文。
_EXCERPT_CHARS = 400
_EXCERPT_BUDGET = 12_000

# 模型漏写某些集时补的占位段。带这个前缀的条目视为"大纲没有该集"，
# 注入时退化为"按章节名自行判断"，不会把占位文字当成本集论点。
_STUB_MARK = "（大纲待补"
_STUB_SECTION = "（大纲待补：本集核心论点、与上一集的承接、给下一集留的引子。）"

# 宽容解析每集小节标题：生成时写 "## 第 N 集：<章节名>"，但人手改大纲时可能写成
# "## 第2集 x" / "## ep-02 x" / "## 第一集：x"（票面 Q2 推荐的就是 ep-XX 形式，
# 模型也常写中文数字集号），都要认得。
_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_NUMERALS = "".join(_CN_DIGITS) + "十百"
_ENTRY_RE = re.compile(
    rf"^##[ \t]*(?:第[ \t]*(\d+|[{_CN_NUMERALS}]+)[ \t]*集|ep[ \t]*[\-—]?[ \t]*(\d+))"
    r"[ \t]*[：:·\-—]?[ \t]*(.*)$",
    re.M | re.I,
)


def _collapse(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _cn_number(text: str) -> int:
    """中文集号 → 整数，只覆盖大纲里会出现的 1–999。"""
    if not text:
        return 0
    if "十" in text:
        tens, _, ones = text.partition("十")
        high = _CN_DIGITS.get(tens, 0) if tens else 1
        low = _CN_DIGITS.get(ones, 0) if ones else 0
        return high * 10 + low
    return _CN_DIGITS.get(text, 0)


def fingerprint(text: str) -> str:
    """大纲指纹（sha256 前 16 位）。写进 draft frontmatter，用来判断某集是否基于旧大纲。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def program_brief(cfg: dict[str, Any], about_chars: int = 200) -> str:
    """节目身份短摘要：title / author / tagline / about。

    没配 ``podcast:`` 块时返回 ""（调用方据此跳过注入，不编造节目名）。
    """
    podcast = cfg.get("podcast") or {}
    title = _collapse(podcast.get("title"))
    author = _collapse(podcast.get("author"))
    tagline = _collapse(podcast.get("tagline"))
    about = _collapse(podcast.get("about"))
    if len(about) > about_chars:
        about = about[:about_chars].rstrip() + "…"
    lines: list[str] = []
    if title and author:
        lines.append(f"节目：《{title}》｜主播：{author}")
    elif title:
        lines.append(f"节目：《{title}》")
    if tagline:
        lines.append(f"定位：{tagline}")
    if about:
        lines.append(f"简介：{about}")
    return "\n".join(lines)


@dataclass(frozen=True)
class Outline:
    """系列大纲。``summary`` = 文件头总纲；``entries`` = 第 N 集 → 该集一段。"""

    text: str
    summary: str
    entries: dict[int, str] = field(default_factory=dict)
    chapters: dict[int, str] = field(default_factory=dict)
    sha: str = ""

    def entry(self, index: int) -> str:
        """第 index 集的大纲段落；占位段返回 ""（视为没有）。"""
        text = self.entries.get(index, "").strip()
        return "" if text.startswith(_STUB_MARK) else text

    def chapter(self, index: int, fallback: str = "") -> str:
        return self.chapters.get(index) or fallback

    def topic(self, index: int, fallback: str = "") -> str:
        """第 index 集的"主题"短句：取大纲段落首句，没有则用 fallback 章节名。"""
        text = self.entry(index)
        if text:
            first = re.split(r"[。！？!?\n]", text, maxsplit=1)[0].strip()
            if first:
                return first[:80]
        fallback = fallback.strip()
        return "" if _GENERIC_TOPIC_RE.match(fallback) else fallback


# chars 模式 / single 模式下的章节名没有语义（src/split.py 硬编码"第N部分"），
# 不能拿来当"下一集主题"。
_GENERIC_TOPIC_RE = re.compile(r"^(第\s*\d+\s*部分|全文|引言)$")


def parse_outline(text: str) -> Outline:
    """解析 outline.md。对格式宽容：缺"## 第 N 集"小节时只得到总纲。"""
    matches = list(_ENTRY_RE.finditer(text))
    head = text[: matches[0].start()] if matches else text
    head = FENCE_RE.sub("", head)
    head = re.sub(r"^#[ \t]*系列大纲[^\n]*\n?", "", head, flags=re.M)
    entries: dict[int, str] = {}
    chapters: dict[int, str] = {}
    for i, m in enumerate(matches):
        raw_idx = m.group(1)
        if raw_idx is None:
            idx = int(m.group(2))
        elif raw_idx.isdigit():
            idx = int(raw_idx)
        else:
            idx = _cn_number(raw_idx)
        if idx <= 0:
            continue
        chapters.setdefault(idx, m.group(3).strip())
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        entries.setdefault(idx, text[m.end():end].strip())
    return Outline(
        text=text,
        summary=head.strip(),
        entries=entries,
        chapters=chapters,
        sha=fingerprint(text),
    )


def build_outline_prompt(plans: list[EpisodePlan], brief: str) -> tuple[str, str]:
    """一次调用覆盖全篇：system 带输出格式，user 给节目身份 + 每集正文开头。"""
    series = plans[0].series if plans else ""
    per = min(_EXCERPT_CHARS, _EXCERPT_BUDGET // max(len(plans), 1))
    system = (
        "你是播客系列策划。输入是同一个系列每一集（集号 / 章节名 / 正文开头），"
        "请为整个系列写一份大纲，供后续逐集写稿时共享上下文。\n\n"
        "输出格式（严格遵守，不要额外解释，不要代码块）：\n"
        f"# 系列大纲：{series or '<系列名>'}\n\n"
        "## 系列总纲\n"
        "<3–5 行：这个系列整体讲什么、脉络怎么推进、听众按顺序听完能获得什么>\n\n"
        "## 第 1 集：<章节名>\n"
        "<2–4 句：本集核心论点；与上一集的承接；给下一集留的引子>\n\n"
        "## 第 2 集：<章节名>\n<同上>\n\n"
        "要求：\n"
        "- 只使用给出的材料，不要补充材料之外的事实、数字或结论。\n"
        "- 每集一段，写清这一集只讲什么、和前后集是什么关系；各集不要写重复内容。\n"
        "- 总纲要能看出各集之间的递进，而不是并列的主题清单。\n"
    )
    chunks: list[str] = []
    if brief:
        chunks.append(brief)
    chunks.append(f"系列名：{series}")
    for plan in plans:
        excerpt = re.sub(r"\s+", " ", _strip_md(plan.body).strip())[:per]
        chunks.append(f"第 {plan.index} 集（共 {plan.total} 集）· {plan.chapter}\n{excerpt}")
    return system, "\n\n".join(chunks)


def coerce_outline(raw: str, plans: list[EpisodePlan], series: str) -> str:
    """把模型输出整成可解析的大纲：补 H1、给漏写的集补占位段。"""
    text = FENCE_RE.sub("", raw).strip()
    if not text:
        text = f"# 系列大纲：{series}"
    if not re.search(r"^#[ \t]", text, re.M):
        text = f"# 系列大纲：{series}\n\n{text}"
    parsed = parse_outline(text)
    missing = [p for p in plans if not parsed.entry(p.index)]
    if missing:
        parts = [text.rstrip()]
        for plan in missing:
            parts.append(f"## 第 {plan.index} 集：{plan.chapter}\n{_STUB_SECTION}")
        text = "\n\n".join(parts)
    return text.rstrip() + "\n"


def _outline_usable(raw: str) -> bool:
    """模型输出是否真的包含可用的分集大纲（空串 / 只有总纲 → False）。"""
    text = FENCE_RE.sub("", str(raw or "")).strip()
    if not text:
        return False
    parsed = parse_outline(text)
    return any(parsed.entry(i) for i in parsed.entries)


def outline_path(out_dir: Path | str) -> Path:
    return Path(out_dir) / OUTLINE_FILENAME


def _llm_ready(cfg: dict[str, Any]) -> bool:
    llm = cfg.get("llm") or {}
    return bool(llm.get("enable")) and bool(resolve_api_key(llm))


def ensure_outline(
    out_dir: Path | str,
    plans: list[EpisodePlan],
    cfg: dict[str, Any],
    regenerate: bool = False,
) -> Outline | None:
    """读/建系列大纲。

    返回 None 表示本次没有可用大纲（单集 / 无 LLM / 调用失败），调用方按旧行为
    逐集独立生成。**已存在的大纲默认只读**：手改 outline.md 即改行为，不会被悄悄覆盖。
    """
    if len(plans) <= 1:
        return None
    path = outline_path(out_dir)
    if path.is_file() and not regenerate:
        return parse_outline(path.read_text(encoding="utf-8"))
    if not _llm_ready(cfg):
        log.warning(
            "  系列大纲未生成：llm.enable=false 或拿不到 api_key —— 本系列仍按逐集独立生成（老行为）。"
        )
        return None
    system, user = build_outline_prompt(plans, program_brief(cfg))
    try:
        raw = llm_complete(system, user, cfg)
    except Exception as e:  # noqa: BLE001 —— 大纲失败不该让整条流水线中断
        log.warning(f"  系列大纲生成失败（{e}）—— 本系列仍按逐集独立生成（老行为）。")
        return None
    # 模型偶尔只回 reasoning、content 为空（llm.py 里会变成 ""），或写不出任何
    # "## 第 N 集" 小节。这种输出 coerce 后会变成一份全占位的 outline.md，若直接
    # 落盘就会吃掉手改版本 —— 先判定有效，无效则保留现有文件、本轮不写。
    if not _outline_usable(raw):
        if path.is_file():
            log.warning(
                "  系列大纲生成无效（模型没返回可用的分集内容）—— 保留现有 outline.md，本轮不覆盖。"
            )
            return parse_outline(path.read_text(encoding="utf-8"))
        log.warning(
            "  系列大纲生成无效（模型没返回可用的分集内容）—— 本系列仍按逐集独立生成（老行为）。"
        )
        return None
    text = coerce_outline(raw, plans, plans[0].series)
    path.write_text(text, encoding="utf-8")
    log.info(f"  📝 系列大纲（{len(plans)} 集）→ {path}")
    return parse_outline(text)
