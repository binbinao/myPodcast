"""把 plans 落成 drafts/ep-XX.md：分级覆盖 + 跳过汇报。

REQ-01 之前 prepare 逐集无条件覆盖，人手改过的稿子会被下一次 prepare 冲掉。
现在按 ai_stage 分级（判定唯一在 src/stages.overwrite_allowed）：

- frozen 永不覆盖；
- reviewed 需 --force；
- generated / skeleton / legacy 按旧行为重生成。

被跳过且基于旧版大纲的集要单独喊出来：否则「大纲换代了，但那几集还是旧稿」
只能靠人自己发现。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .generate import draft_filename, generate_script
from .ingest import parse_script
from .log import logger as log
from .outline import OUTLINE_SHA_KEY, Outline
from .series import context_for_episode
from .split import EpisodePlan
from .stages import overwrite_allowed, stage_of


def _draft_meta(path: Path) -> dict[str, Any]:
    """读 draft frontmatter。文件不存在 / 解析失败返回 {}（按 legacy 处理）。"""
    if not path.is_file():
        return {}
    try:
        meta, _ = parse_script(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return meta or {}


def write_episodes(
    plans: list[EpisodePlan],
    out_dir: Path | str,
    cfg: dict[str, Any],
    source_rel: str | None = None,
    *,
    outline: Outline | None = None,
    brief: str = "",
    force: bool = False,
) -> list[Path]:
    """写（或跳过）每一集，返回真正落盘的文件列表。"""
    out_dir = Path(out_dir)
    made: list[Path] = []
    skipped: list[tuple[str, str]] = []  # (文件名, ai_stage)
    stale: list[str] = []                # 被跳过但基于旧版大纲的集
    for plan in plans:
        f = out_dir / draft_filename(plan)
        meta = _draft_meta(f)
        stage = stage_of(meta)
        if not overwrite_allowed(stage, force):
            skipped.append((f.name, stage))
            if outline is not None and str(meta.get(OUTLINE_SHA_KEY) or "") != outline.sha:
                stale.append(f.name)
            continue
        if f.is_file() and not stage:
            log.info(f"  {f.name} 无 ai_stage（legacy）→ 按未审阅重生成")
        ctx = None
        if outline is not None:
            # 下一集的章节名只作兜底：by_chars 模式下「第N部分」没有语义，
            # Outline.topic() 会把它过滤掉，改用大纲段落的首句。
            next_chapter = plans[plan.index].chapter if plan.index < len(plans) else ""
            ctx = context_for_episode(
                plan, outline, brief, out_dir, next_chapter=next_chapter
            )
        script = generate_script(plan, cfg, source_rel, series=ctx)
        f.write_text(script, encoding="utf-8")
        made.append(f)

    if skipped:
        by_stage: dict[str, list[str]] = {}
        for name, st in skipped:
            by_stage.setdefault(st or "legacy", []).append(name)
        detail = "；".join(f"{st} {len(names)} 集" for st, names in by_stage.items())
        log.info(f"  跳过 {detail}（frozen 永不覆盖；reviewed 加 --force 才覆盖）")
    if stale:
        log.warning(
            f"  ⚠ {len(stale)} 集被跳过但基于旧版系列大纲（{', '.join(stale)}）："
            "reviewed 加 --force 重生成；frozen 需先 --mark-reviewed 再 --force。"
        )
    return made
