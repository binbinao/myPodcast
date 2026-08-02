"""脚本生成：全自动(LLM) 或 半自动(骨架)。

- 全自动：调 OpenAI 兼容接口，按 solo/duo 把书面正文改写成口播脚本。
- 半自动：只包成 [host] 骨架，留给人工润色（无需 API key）。
输出带 frontmatter 的脚本 markdown，落到 drafts/ 待审。

LLM 出口拦截：调 validate_script() 检查 BLOCK 残留（emoji / 代码块 /
markdown 残留等），命中则 heuristic 二次清洗，仍命中才降级 _skeleton。

命名：所有 draft 目录与文件名通过 src.naming 生成。
"""
from __future__ import annotations

from typing import Any

from .log import logger as log
from .naming import draft_filename as _draft_filename, drafts_dir_for as _drafts_dir_for
from .polish import heuristic_clean, llm_complete, resolve_api_key
from .split import EpisodePlan, _strip_md
from .stages import STAGE_GENERATED, STAGE_SKELETON


def _wrap(
    plan: EpisodePlan,
    body_text: str,
    source: str | None = None,
    stage: str = STAGE_GENERATED,
) -> str:
    """把 draft 包成带 frontmatter 的 markdown。

    重要：用 yaml.safe_dump 序列化 frontmatter，而不是 f-string 拼接——
    LLM 生成的 chapter / description 里可能含双引号（`结语："开始"`），f-string
    会破坏 YAML 边界，导致 parse_script 静默失败、整集 meta 空、build 把
    output 写到 `series/<path.stem>/ep-01/` 的诡异路径。yaml.safe_dump 自动
    escape 引号和换行。
    """
    import yaml
    fm: dict[str, Any] = {
        "title": plan.title,
        "description": plan.description if hasattr(plan, "description") and plan.description else "",
        "format": plan.format,
        "series": plan.series,
    }
    if getattr(plan, "series_slug", ""):
        fm["series_slug"] = plan.series_slug
    fm["episode"] = plan.index
    fm["total"] = plan.total
    fm["chapter"] = plan.chapter
    if getattr(plan, "voice", ""):
        fm["voice"] = plan.voice
    if getattr(plan, "host_voice", ""):
        fm["host_voice"] = plan.host_voice
    if getattr(plan, "guest_voice", ""):
        fm["guest_voice"] = plan.guest_voice
    if getattr(plan, "split_strategy", ""):
        fm["split_strategy"] = plan.split_strategy
    if source:
        fm["source"] = source
    fm["ai_stage"] = stage

    # sort_keys=False 保留字段顺序；allow_unicode=True 支持中文；
    # default_flow_style=False 用 block style（更可读）。
    yaml_str = yaml.safe_dump(
        fm, allow_unicode=True, sort_keys=False, default_flow_style=False,
        width=4096,
    )
    return f"---\n{yaml_str}---\n\n{body_text.strip()}\n"


def _ensure_clean_body(body: str, episode_label: str) -> str:
    """对 LLM 输出的 body 做兜底：

    1. validate_script 检查 BLOCK 违规
    2. 命中则 heuristic_clean() 二次清洗
    3. 仍命中则降级 strip 后直接使用（不再回退 skeleton，因为 _skeleton 完全
       无 LLM 价值）

    返回清理后的 body。
    """
    from .validate import has_blocking, validate_script
    warnings = validate_script({}, body)
    if not has_blocking(warnings):
        return body
    log.warning(
        f"LLM 输出有 BLOCK 残留：{episode_label} hit "
        f"{[w for w in warnings if w.startswith('[block]')][:3]}，heuristic 二次清洗"
    )
    cleaned = heuristic_clean(body)
    warnings2 = validate_script({}, cleaned)
    if has_blocking(warnings2):
        log.warning(
            f"heuristic 清洗后仍 BLOCK：{episode_label} hit "
            f"{[w for w in warnings2 if w.startswith('[block]')][:3]}，使用脱敏版本"
        )
    return cleaned


def _auto(plan: EpisodePlan, cfg: dict[str, Any], source: str | None = None) -> str:
    if plan.format == "solo":
        sys_prompt = (
            "你是一名播客文案编辑。把下面的书面内容改写成自然、口语化、适合单人朗读的播客稿。"
            "全程用 [host] 标签，去掉书面冗余词，保留关键信息，适当加入过渡句。"
            "只输出脚本正文，不要解释。"
        )
    else:
        sys_prompt = (
            "你是一名播客文案编辑。把下面的书面内容改写成双人对话播客稿。"
            "用 [host] 和 [guest] 交替发言，像真实聊天，有来有回、有互动。"
            "保留关键信息，去掉书面冗余。只输出脚本正文，不要解释。"
        )
    raw = llm_complete(sys_prompt, plan.body, cfg)
    text = _ensure_clean_body(_strip_md(raw), f"ep-{plan.index:02d} {plan.chapter}")
    return _wrap(plan, text, source)


def _skeleton(plan: EpisodePlan, source: str | None = None) -> str:
    lines = []
    for para in plan.body.split("\n\n"):
        p = _strip_md(para).strip()
        if p:
            lines.append(f"[host] {p}")
    return _wrap(plan, "\n".join(lines), source, stage=STAGE_SKELETON)


def generate_script(plan: EpisodePlan, cfg: dict[str, Any], source: str | None = None) -> str:
    llm = cfg.get("llm", {})
    if llm.get("enable") and resolve_api_key(llm):
        return _auto(plan, cfg, source)
    return _skeleton(plan, source)


# ----- 命名代理（保持旧 import 兼容） -----

def draft_filename(plan: EpisodePlan) -> str:
    return _draft_filename(plan.index)


def draft_dir_for(
    article_date: str,
    title: str,
    explicit_slug: str | None,
    drafts_dir: str = "drafts",
) -> str:
    from pathlib import Path
    d = Path(_drafts_dir_for(article_date, title, explicit_slug, drafts_dir))
    d.mkdir(parents=True, exist_ok=True)
    return str(d)
