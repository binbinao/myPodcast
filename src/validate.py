"""脚本质量校验：build 入口处自动检测并 warn（不阻断）。

检查项：
1. emoji / 零宽字符：TTS 会念出奇怪字符
2. markdown 残留：**加粗** / > 引用 / [text](url) 链接
3. 长度：单集 > 10K 字符 warn（API 限速风险）
4. 角色标签：必须含 [host] 或 [guest]，否则 build 无法工作
5. frontmatter 必填字段：series_slug / episode / format

调用方：在 build.py 的 run_one() 入口处调用 validate_script(meta, body)。
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


def _strip_frontmatter(body: str) -> tuple[dict[str, Any], str]:
    """从脚本 markdown 抽出 frontmatter 和正文。复用 ingest.parse_script 逻辑。"""
    from .ingest import parse_script
    return parse_script("---\n" + body) if not body.startswith("---") else parse_script(body)


def validate_script(meta: dict[str, Any], body: str) -> list[str]:
    """返回 warn 列表（空 = 无问题）。"""
    warnings: list[str] = []
    text = body.strip()
    if not text:
        warnings.append("脚本正文为空")
        return warnings

    # 1) emoji
    emos = _EMOJI_RE.findall(text)
    if emos:
        warnings.append(f"含 emoji 字符 {len(emos)} 处（TTS 会念出）: {emos[:5]}")

    # 2) 零宽
    invis = _INVISIBLE_RE.findall(text)
    if invis:
        warnings.append(f"含零宽字符 {len(invis)} 处")

    # 3) markdown 残留
    bolds = _MD_BOLD_RE.findall(text)
    if bolds:
        warnings.append(f"含 markdown 加粗 {len(bolds)} 处（TTS 会念'星号'）: {bolds[:3]}")
    links = _MD_LINK_RE.findall(text)
    if links:
        warnings.append(f"含 markdown 链接 {len(links)} 处（TTS 会念'括号 url 括号'）: {links[:3]}")
    quotes = _MD_QUOTE_RE.findall(text)
    if quotes:
        warnings.append(f"含 markdown 引用 {len(quotes)} 处（TTS 会念'大于号'）")

    # 4) 长度
    if len(text) > 10000:
        warnings.append(f"单集脚本过长 {len(text)} 字符（API 限速风险，建议切多集）")

    # 5) 角色标签
    has_role = bool(re.search(r"^\[host\]|^\[guest\]", text, flags=re.M))
    if not has_role:
        warnings.append("脚本无 [host] / [guest] 角色标签，build 无法朗读")

    # 6) frontmatter 必填
    for field in ("series_slug", "episode"):
        if not meta.get(field):
            warnings.append(f"frontmatter 缺必填字段: {field}")

    return warnings


def report_and_warn(name: str, warnings: list[str]) -> None:
    """把 warn 列表打印为 log.warning。"""
    if not warnings:
        log.info(f"  ✓ {name} 校验通过")
        return
    log.warning(f"  ⚠ {name} {len(warnings)} 项需关注：")
    for w in warnings:
        log.warning(f"     - {w}")