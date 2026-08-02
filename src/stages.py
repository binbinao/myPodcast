"""draft 生命周期状态机（`ai_stage` frontmatter 字段）。

drafts/ 是评审门：prepare 写入，人工审阅，build **只读**消费。
`ai_stage` 是这条契约的唯一机器可读标记。

    skeleton  ── prepare 拿不到 LLM key 时的骨架稿，未口语化
    generated ── prepare 经 LLM 改写产出，未经人工审阅
    reviewed  ── 人工审阅通过（`prepare --mark-reviewed`）
    frozen    ── 锁稿：语义同 reviewed，额外声明"不要再重生成覆盖"

**build 对所有 stage 一律只读**——stage 只决定告警等级，永不改变正文。
重构前 build 会跑 `polish()` 二次 LLM 改写，导致：人工在 drafts/ 的修改被吃、
LLM 成本翻倍、同一 draft 每次 build 输出不同（不可复现）。

legacy draft（无 ai_stage 字段）按"未知"处理：告警但不阻断，保证存量可跑。
"""
from __future__ import annotations

import re
from pathlib import Path

STAGE_SKELETON = "skeleton"
STAGE_GENERATED = "generated"
STAGE_REVIEWED = "reviewed"
STAGE_FROZEN = "frozen"

ALL_STAGES: tuple[str, ...] = (
    STAGE_SKELETON,
    STAGE_GENERATED,
    STAGE_REVIEWED,
    STAGE_FROZEN,
)

# 人工已认领的 stage：build 不再告警
_HUMAN_APPROVED: frozenset[str] = frozenset({STAGE_REVIEWED, STAGE_FROZEN})

# frontmatter 块（前后 --- 包裹）。DOTALL 让 . 吃换行，非贪婪停在第一个闭合 ---。
_FM_RE = re.compile(r"^(---[ \t]*\n)(.*?)(\n---[ \t]*\n)", re.DOTALL)
_STAGE_LINE_RE = re.compile(r"^ai_stage:[ \t]*(\S+)[ \t]*$", re.M)

# 只有 ep-XX.md 是 draft；README/笔记不参与 stage 流转（与 build.py 收集规则一致）
_EP_FILE_RE = re.compile(r"^ep-\d+\.md$")


def stage_of(meta: dict) -> str:
    """从 draft frontmatter 读 ai_stage。缺字段或非法值返回 ""（legacy/未知）。"""
    raw = str(meta.get("ai_stage", "") or "").strip().lower()
    return raw if raw in ALL_STAGES else ""


def is_human_approved(stage: str) -> bool:
    """人工是否已认领这份稿子。"""
    return stage in _HUMAN_APPROVED


def stage_warning(stage: str) -> str:
    """build 消费 draft 时的告警文案。返回 "" 表示无需告警。

    这里刻意只告警不阻断：存量 26 个 draft 全无 ai_stage，硬拦会直接堵死现有工作流。
    """
    if is_human_approved(stage):
        return ""
    if stage == STAGE_SKELETON:
        return (
            "draft 是 skeleton 骨架稿（prepare 时无 LLM key），未口语化。"
            " build 只读不改写 —— 配好 key 重跑 prepare 才能拿到口播稿。"
        )
    if stage == STAGE_GENERATED:
        return (
            "draft 未经人工审阅（ai_stage: generated）。"
            " 审完跑 `python -m src.prepare --mark-reviewed <路径>` 消除此告警。"
        )
    return (
        "draft 无 ai_stage 标记（legacy）。"
        " 跑 `python -m src.prepare --mark-reviewed <路径>` 补标记。"
    )


def set_stage(path: Path, stage: str) -> str:
    """改写单个 draft 的 ai_stage，返回旧值（legacy 返回 ""）。

    只动 frontmatter 内的 ai_stage 一行，正文与其余字段逐字节保留。
    """
    if stage not in ALL_STAGES:
        raise ValueError(f"未知 stage: {stage!r}，合法值 {ALL_STAGES}")
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    if not m:
        raise ValueError(f"{path} 没有 frontmatter，不是合法 draft")

    head, fm_body, fm_tail = m.group(1), m.group(2), m.group(3)
    hit = _STAGE_LINE_RE.search(fm_body)
    if hit:
        old = hit.group(1).strip().lower()
        new_fm = _STAGE_LINE_RE.sub(f"ai_stage: {stage}", fm_body, count=1)
    else:
        old = ""
        new_fm = f"{fm_body}\nai_stage: {stage}"

    path.write_text(head + new_fm + fm_tail + text[m.end():], encoding="utf-8")
    return old


def iter_drafts(target: Path) -> list[Path]:
    """收集 target 下的 draft 文件。target 可以是单个 ep-XX.md 或含它们的目录。"""
    target = Path(target)
    if target.is_file():
        return [target]
    return sorted(p for p in target.glob("**/*.md") if _EP_FILE_RE.match(p.name))


def mark_reviewed(target: Path, stage: str = STAGE_REVIEWED) -> list[tuple[Path, str]]:
    """把 target 下所有 draft 标为 reviewed，返回 [(路径, 旧 stage)]。"""
    drafts = iter_drafts(target)
    if not drafts:
        raise ValueError(f"{target} 下没有 ep-XX.md draft")
    return [(p, set_stage(p, stage)) for p in drafts]
