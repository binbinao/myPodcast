"""脚本质量校验：build 入口处自动检测并 warn（不阻断）。

检查项分成两类：
- BLOCK（阻塞）：TTS 真的会念出奇怪字符或污染音频，下游必须拦截
  - emoji / 零宽字符 / 代码块 / Markdown 标题残留 / HTML 标签 / pipe 表格 /
    *斜体* / **加粗** / [link](url) / > 引用
- WARN（警告）：heuristic 路径仍能工作，但有风险需要关注
  - 长度 > 10K 字符（API 限速风险）
  - 缺 [host] / [guest] 角色标签
  - frontmatter 缺必填字段

调用方：
- src/build.py:42 入口仍调 validate_script（warn 收尾）
- src/generate.py 出口拦截 BLOCK：命中则 heuristic 二次清洗，仍命中则降级 _skeleton
"""
from __future__ import annotations

import re
from typing import Any

from .log import logger as log


# emoji 范围（粗略覆盖；不全但常见）
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F9FF"   # 符号与表情
    "\U0001FA00-\U0001FAFF"      # 扩展 A
    "\u2600-\u26FF"              # 杂项符号
    "\u2700-\u27BF"              # dingbats
    "]",
    flags=re.UNICODE,
)

# 零宽字符
_INVISIBLE_RE = re.compile(r"[\u200B-\u200F\uFEFF\u2060]")

# markdown 残留模式
_MD_BOLD_RE = re.compile(r"\*\*[^*]+\*\*")
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_MD_QUOTE_RE = re.compile(r"(?m)^>\s")  # 行首 > 引用

# 代码块 fence（``` / ~~~）
_MD_CODE_FENCE_RE = re.compile(r"```|~~~")

# Markdown 标题残留（# / ## / ### ...）。LLM 输出常见的是行内残留：
# `[host] ## 这是 H2 标题` —— 不在行首，但 TTS 会念'井号'，算 BLOCK。
_MD_HEADING_RE = re.compile(r"#{1,6}\s+\S")

# HTML 标签（如 <br>、<a href="...">）
_HTML_TAG_RE = re.compile(r"<[a-zA-Z][a-zA-Z0-9_-]*(?:\s+[^>]*)?>")

# pipe 表格分隔行（| --- | --- | 或多列 row）
_PIPE_TABLE_RE = re.compile(r"(?m)^\s*\|?[\s\-:|]+\|[\s\-:|]+\s*$")

# *斜体*（单星号且不在 ** 之中）
_ASTERISK_ITALIC_RE = re.compile(r"(?<![*\w])\*[^*\n]{1,200}\*(?![*\w])")

# Setext 标题（下划线 === / --- 整行）
_SETEXT_HEADING_RE = re.compile(r"(?m)^[=\-]{3,}\s*$")

# Markdown 脚注引用 [^1] / [^note]
_FOOTNOTE_RE = re.compile(r"\[\^[^\]]+\]")

# 行内 `code`（TTS 会念'反引号'）
_INLINE_CODE_RE = re.compile(r"`[^`\n]{1,200}`")

# 裸 URL（http(s):// 或 www. 开头）—— TTS 会逐字念出
_BARE_URL_RE = re.compile(r"(?:https?://|www\.)[^\s)]+")

# 全角竖线（｜）—— 中文写作常用，但 TTS 不会自动转语义
_FULLWIDTH_PIPE_RE = re.compile(r"｜")

# Emoji 键帽 0-9（U+0030..U+0039 + U+20E3）
_KEYCAP_RE = re.compile(r"[\u0030-\u0039]\u20E3")

# BLOCK 级别违规的前缀
_BLOCK_PREFIX = "[block] "


def _strip_frontmatter(body: str) -> tuple[dict[str, Any], str]:
    """从脚本 markdown 抽出 frontmatter 和正文。复用 ingest.parse_script 逻辑。"""
    from .ingest import parse_script
    return parse_script("---\n" + body) if not body.startswith("---") else parse_script(body)


def validate_script(meta: dict[str, Any], body: str) -> list[str]:
    """返回 warn 列表（空 = 无问题）。

    警告文本以 `[block]` 开头的属于 BLOCK 级别违规——
    TTS 真会念出奇怪字符或污染音频，下游必须拦截。
    `has_blocking(warnings)` 可筛选。
    """
    warnings: list[str] = []
    text = body.strip()
    if not text:
        warnings.append("脚本正文为空")
        return warnings

    # 1) emoji（BLOCK）
    emos = _EMOJI_RE.findall(text)
    if emos:
        warnings.append(_BLOCK_PREFIX + f"含 emoji 字符 {len(emos)} 处: {emos[:5]}")

    # 2) 零宽字符（BLOCK）
    invis = _INVISIBLE_RE.findall(text)
    if invis:
        warnings.append(_BLOCK_PREFIX + f"含零宽字符 {len(invis)} 处")

    # 3) markdown 残留（全部 BLOCK）
    bolds = _MD_BOLD_RE.findall(text)
    if bolds:
        warnings.append(_BLOCK_PREFIX + f"含 markdown 加粗 {len(bolds)} 处: {bolds[:3]}")
    links = _MD_LINK_RE.findall(text)
    if links:
        warnings.append(_BLOCK_PREFIX + f"含 markdown 链接 {len(links)} 处: {links[:3]}")
    quotes = _MD_QUOTE_RE.findall(text)
    if quotes:
        warnings.append(_BLOCK_PREFIX + f"含 markdown 引用 {len(quotes)} 处")
    fences = _MD_CODE_FENCE_RE.findall(text)
    if fences:
        warnings.append(_BLOCK_PREFIX + f"含代码块 fence {len(fences)} 处（TTS 会念'反引号'）")
    headings = _MD_HEADING_RE.findall(text)
    if headings:
        warnings.append(_BLOCK_PREFIX + f"含 markdown 标题残留 {len(headings)} 处（TTS 会念'井号'）: {headings[:3]}")
    htmls = _HTML_TAG_RE.findall(text)
    if htmls:
        warnings.append(_BLOCK_PREFIX + f"含 HTML 标签 {len(htmls)} 处: {htmls[:3]}")
    pipes = _PIPE_TABLE_RE.findall(text)
    if pipes:
        warnings.append(_BLOCK_PREFIX + f"含 pipe 表格 {len(pipes)} 处（TTS 会念'竖线'）")
    italics = _ASTERISK_ITALIC_RE.findall(text)
    if italics:
        warnings.append(_BLOCK_PREFIX + f"含 *斜体* 残留 {len(italics)} 处: {italics[:3]}")

    # 3b) 漏网补充 BLOCK
    setext = _SETEXT_HEADING_RE.findall(text)
    if setext:
        warnings.append(_BLOCK_PREFIX + f"含 setext 标题下划线 {len(setext)} 处（TTS 会念'等号'/'减号'）")
    notes = _FOOTNOTE_RE.findall(text)
    if notes:
        warnings.append(_BLOCK_PREFIX + f"含 markdown 脚注 {len(notes)} 处: {notes[:3]}")
    inlines = _INLINE_CODE_RE.findall(text)
    if inlines:
        warnings.append(_BLOCK_PREFIX + f"含行内代码 {len(inlines)} 处（TTS 会念'反引号'）")
    urls = _BARE_URL_RE.findall(text)
    if urls:
        warnings.append(_BLOCK_PREFIX + f"含裸 URL {len(urls)} 处: {urls[:3]}")
    fw_pipes = _FULLWIDTH_PIPE_RE.findall(text)
    if fw_pipes:
        warnings.append(_BLOCK_PREFIX + f"含全角竖线 {len(fw_pipes)} 处")
    keycaps = _KEYCAP_RE.findall(text)
    if keycaps:
        warnings.append(_BLOCK_PREFIX + f"含 emoji 键帽 {len(keycaps)} 处: {keycaps[:3]}")

    # 4) 长度（WARN）
    if len(text) > 10000:
        warnings.append(f"单集脚本过长 {len(text)} 字符（API 限速风险，建议切多集）")

    # 5) 角色标签（WARN）
    has_role = bool(re.search(r"^\[host\]|^\[guest\]", text, flags=re.M))
    if not has_role:
        warnings.append("脚本无 [host] / [guest] 角色标签，build 无法朗读")

    # 6) frontmatter 必填（WARN）
    for field in ("series_slug", "episode"):
        if not meta.get(field):
            warnings.append(f"frontmatter 缺必填字段: {field}")

    return warnings


def has_blocking(warnings: list[str]) -> bool:
    """返回 True 当 warn 列表中含 BLOCK 级别违规。generate.py 出口用此拦截。"""
    return any(w.startswith(_BLOCK_PREFIX) for w in warnings)


def blocking_summary(warnings: list[str]) -> str:
    """把 BLOCK 行抽出来拼成单行摘要，供 PipelineError.hint 给人类看。"""
    blocks = [w[len(_BLOCK_PREFIX):] for w in warnings if w.startswith(_BLOCK_PREFIX)]
    if not blocks:
        return ""
    return "BLOCK 项：\n  - " + "\n  - ".join(blocks)


def report_and_warn(name: str, warnings: list[str]) -> None:
    """把 warn 列表打印为 log.warning。"""
    if not warnings:
        log.info(f"  ✓ {name} 校验通过")
        return
    log.warning(f"  ⚠ {name} {len(warnings)} 项需关注：")
    for w in warnings:
        log.warning(f"     - {w}")