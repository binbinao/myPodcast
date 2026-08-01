"""脚本生成：全自动(LLM) 或 半自动(骨架)。

- 全自动：调 OpenAI 兼容接口，按 solo/duo 把书面正文改写成口播脚本。
- 半自动：只包成 [host] 骨架，留给人工润色（无需 API key）。
输出带 frontmatter 的脚本 markdown，落到 drafts/ 待审。

命名：所有 draft 目录与文件名通过 src.naming 生成。
"""
from __future__ import annotations

from typing import Any

from .naming import draft_filename as _draft_filename, drafts_dir_for as _drafts_dir_for
from .polish import llm_complete
from .split import EpisodePlan, _strip_md


def _wrap(plan: EpisodePlan, body_text: str, source: str | None = None) -> str:
    src_line = f'source: "{source}"\n' if source else ""
    series_slug_line = (
        f'series_slug: "{plan.series_slug}"\n' if getattr(plan, "series_slug", "") else ""
    )
    return (
        f"---\n"
        f'title: "{plan.title}"\n'
        f'description: "《{plan.series}》{plan.chapter}（第 {plan.index}/{plan.total} 集）"\n'
        f"format: {plan.format}\n"
        f'series: "{plan.series}"\n'
        f"{series_slug_line}"
        f"episode: {plan.index}\n"
        f"total: {plan.total}\n"
        f'chapter: "{plan.chapter}"\n'
        f"{src_line}"
        f"---\n\n"
        f"{body_text.strip()}\n"
    )


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
    text = _strip_md(llm_complete(sys_prompt, plan.body, cfg))
    return _wrap(plan, text, source)


def _skeleton(plan: EpisodePlan, source: str | None = None) -> str:
    lines = []
    for para in plan.body.split("\n\n"):
        p = _strip_md(para).strip()
        if p:
            lines.append(f"[host] {p}")
    return _wrap(plan, "\n".join(lines), source)


def generate_script(plan: EpisodePlan, cfg: dict[str, Any], source: str | None = None) -> str:
    llm = cfg.get("llm", {})
    if llm.get("enable") and llm.get("api_key"):
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
