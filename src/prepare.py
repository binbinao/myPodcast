"""prepare：原始文章 → 分集 → 脚本 → drafts/（评审门）。

用法:
    python -m src.prepare                 # 处理 raw/ 下所有文章
    python -m src.prepare --article raw/foo.md

命名规则（src/naming.py）：
  raw:      YYYY-MM-DD-slug.md
  drafts:   drafts/<YYYY-MM-DD-slug>/ep-XX.md
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from .episodes import write_episodes
from .generate import draft_dir_for
from .ingest import article_meta, duo_voices_from_meta, parse_script
from .log import logger as log
from .naming import chinese_to_ascii
from .outline import ensure_outline, program_brief
from .split import plan_episodes

def prepare_file(
    path: Path,
    cfg: dict[str, Any],
    drafts_dir: Path,
    auto_accept: bool = False,
    *,
    force: bool = False,
    regenerate_outline: bool = False,
    outline_only: bool = False,
) -> list[Path]:
    article = path.read_text(encoding="utf-8")
    fmt_default = str(cfg.get("format", "duo")).lower()
    series_title, fmt, episodes, art_date, explicit_slug = article_meta(
        article, path, fmt_default
    )
    # series_slug：frontmatter series_slug 优先 → 否则用 explicit_slug（来自
    # frontmatter slug 或 raw 文件名）→ 兜底用 ascii(title)。兜底路径只在
    # 极端异常（既无 frontmatter 又无 YYYY-MM-DD 前缀的文件名）时触发。
    meta, _ = parse_script(article)
    series_slug = (
        str(meta.get("series_slug") or "").strip()
        or explicit_slug
        or chinese_to_ascii(series_title)
    )

    # ===== 三决策门 =====
    # AI 给推荐，用户拍板；auto_accept=True 全自动（CI / 批处理用）。
    # frontmatter 显式 format / voice 字段：尊重用户既定决策，仅跑缺失的门。
    from .decisions import collect_decisions, save_decisions
    fm_format = str(meta.get("format", "")).lower()
    fm_voice = str(meta.get("voice", "")).strip()
    fm_split = str(meta.get("split_strategy", "")).strip()
    fm_host, fm_guest = duo_voices_from_meta(meta)

    if fm_format in ("solo", "duo") and fm_voice and fm_split:
        # frontmatter 三件套都齐：尊重用户，不打扰
        log.info(f"  frontmatter 三件套齐全（format={fm_format}/voice={fm_voice}/split={fm_split}），跳过决策门")
        if fm_format == "duo" and not (fm_host and fm_guest):
            # 别让它静默丢掉：duo 却没解析出音色时，把可接受的两种写法直接写进日志。
            log.warning(
                "  duo 稿的 frontmatter 未解析出 host/guest 音色 → draft 将不写这两项，"
                "build 只能回退到 voices_<backend> 的默认值。"
                '修法：写 host_voice/guest_voice 两个键，或让 voice 采用 "host=X / guest=Y" 格式。'
            )
        from .decisions import Decisions
        decisions = Decisions(
            format=fm_format, voice=fm_voice, voice_type="(frontmatter)",
            host_voice=fm_host, guest_voice=fm_guest,
            split_strategy=fm_split,
            split_params={"max_episode_chars": cfg.get("split", {}).get("max_episode_chars", 3000)},
            split_count=0,
        )
    else:
        # 至少有一项没定 → 跑三门
        log.info(f"📄 准备处理: {path.name}  标题: 《{series_title}》")
        decisions = collect_decisions(
            article, cfg, auto_accept=auto_accept,
            series_title=series_title, fmt_default=fmt_default,
            series_slug=series_slug,
        )
        # frontmatter 已有但本次重决策 → 决策结果覆盖
        decisions.format = decisions.format or fm_format or "duo"
        decisions.voice = decisions.voice or fm_voice
        # 音色：决策门结果优先（与 format/voice/split 同一语义），空则用 frontmatter 显式值兜底
        decisions.host_voice = decisions.host_voice or fm_host
        decisions.guest_voice = decisions.guest_voice or fm_guest
        decisions.split_strategy = decisions.split_strategy or fm_split or "auto"

    out_dir = Path(draft_dir_for(art_date, series_title, explicit_slug, str(drafts_dir)))

    fmt = decisions.format
    # plan_episodes 接受 strategy + 透传参数
    strategy = decisions.split_strategy or "auto"
    sp = decisions.split_params or {}
    plans = plan_episodes(
        article, cfg, series_title, fmt, episodes,
        series_slug=series_slug, article_date=art_date,
        strategy=strategy,
        max_chars_override=sp.get("max_episode_chars"),
        max_duration_min=sp.get("max_duration_min"),
        chars_per_minute=sp.get("chars_per_minute", 250),
    )
    # ===== 系列上下文（REQ-01）=====
    # 多集系列：读/建 outline.md，逐集注入节目身份 + 总纲 + 上一集结尾 + 下一集主题。
    # 单集不走这条路径：不产大纲，prompt 与改造前逐字节一致。
    outline = ensure_outline(
        out_dir, plans, cfg, regenerate=regenerate_outline or outline_only
    )
    brief = program_brief(cfg) if outline is not None else ""
    # --outline-only 是"只重建大纲"的独立动作：放在多集分支之外，单集也必须早退，
    # 否则单集场景仍会生成 ep-01（票面验收：单集行为不变）。
    if outline_only:
        # save_decisions 也留到返回之后，让"未改动任何文件"字面为真。
        if len(plans) <= 1:
            log.info("  --outline-only：单集不产大纲，未改动任何文件。")
        elif outline is None:
            log.warning(
                "  --outline-only：没有可写的大纲（无 LLM key 或调用失败），未改动任何文件。"
            )
        else:
            log.info(f"  --outline-only：只更新大纲，{len(plans)} 集正文未动。")
        return []
    if len(plans) > 1 and outline is None:
        log.warning("  ⚠ 本系列没有可用大纲：按逐集独立生成，跨集承接无保障。")

    # 写决策日志（_decisions.json），与 draft 同目录，方便审计
    save_decisions(out_dir, decisions)

    try:
        source_rel = str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        source_rel = str(path)
    # 把 voice / split_strategy / host_voice / guest_voice 落到 EpisodePlan
    # （_wrap 会写进 frontmatter，build 会按 format 透传到 voice_map）。
    for plan in plans:
        if decisions.voice and not getattr(plan, "voice", ""):
            plan.voice = decisions.voice
        if decisions.host_voice:
            plan.host_voice = decisions.host_voice
        if decisions.guest_voice:
            plan.guest_voice = decisions.guest_voice
        if decisions.split_strategy:
            plan.split_strategy = decisions.split_strategy

    made = write_episodes(
        plans, out_dir, cfg, source_rel, outline=outline, brief=brief, force=force
    )
    count = f"{len(plans)} 集" if len(made) == len(plans) else f"{len(plans)} 集（写入 {len(made)}）"
    log.info(f"  {path.name} → 《{series_title}》{count} → {out_dir}")
    return made


def run(
    raw_dir: Path,
    drafts_dir: Path,
    config_path: Path,
    article: Path | None = None,
    auto_accept: bool = False,
    *,
    force: bool = False,
    regenerate_outline: bool = False,
    outline_only: bool = False,
) -> None:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    drafts_dir = Path(drafts_dir)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    # 不再 hard gate 静默 rename：raw 文件名由作者自主决定（frontmatter slug
    # 是 preferred，但 prepare 不再越权改用户命名）。2026-08-02 与斌哥拍板取消
    # silent rename——个人内容资产，英文/拼音/中文都应该是用户说了算。
    opts = dict(
        force=force, regenerate_outline=regenerate_outline, outline_only=outline_only
    )
    if article:
        prepare_file(Path(article), cfg, drafts_dir, auto_accept=auto_accept, **opts)
        return
    raw_dir = Path(raw_dir)
    files = sorted(raw_dir.glob("*.md"))
    if not files:
        log.info(f"⚠ raw/ 下没有 markdown 文章（{raw_dir}）")
        return
    total = 0
    for f in files:
        total += len(prepare_file(f, cfg, drafts_dir, auto_accept=auto_accept, **opts))
    log.info(f"\n✓ 生成 {total} 个草稿脚本到 {drafts_dir}/（审完用 build 生成音频）")


def main() -> None:
    from .log import configure
    ap = argparse.ArgumentParser(description="myPodcast prepare: 文章→分集脚本")
    ap.add_argument("--article", help="只处理单个文章")
    ap.add_argument("--raw", default="raw", help="原始文章目录 (默认 raw)")
    ap.add_argument("--drafts", default="drafts", help="草稿输出目录 (默认 drafts)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument(
        "--yes", "--auto", dest="auto_accept", action="store_true",
        help="三决策门全自动：AI 推荐直接采用，无 stdin 交互（CI / 批处理用）",
    )
    ap.add_argument("--mark-reviewed", metavar="路径",
                    help="把指定 draft 目录/文件标为 ai_stage: reviewed（审阅完成，消除 build 告警）")
    ap.add_argument("--freeze", metavar="路径",
                    help="把指定 draft 标为 ai_stage: frozen（锁稿，语义同 reviewed 且声明不再重生成）")
    ap.add_argument("--force", action="store_true",
                    help="覆盖 reviewed 稿（默认跳过；frozen 始终跳过，需先 --mark-reviewed）")
    ap.add_argument("--regenerate-outline", action="store_true",
                    help="重新调用模型生成系列大纲（默认已有 outline.md 则沿用；手改大纲直接生效）")
    ap.add_argument("--outline-only", action="store_true",
                    help="只重建系列大纲，不生成/覆盖任何一集（改完大纲再正常跑一次）")
    ap.add_argument("--log-file", default=None, help="追加日志到此文件")
    ap.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    args = ap.parse_args()
    configure(level=args.log_level, log_file=args.log_file)

    # --mark-reviewed / --freeze 是独立动作：只改 ai_stage，不跑生成流水线。
    if args.mark_reviewed or args.freeze:
        from .core import EXIT_GATE_VIOLATION
        from .stages import STAGE_FROZEN, STAGE_REVIEWED, mark_reviewed
        target, stage = (
            (args.freeze, STAGE_FROZEN) if args.freeze
            else (args.mark_reviewed, STAGE_REVIEWED)
        )
        try:
            changed = mark_reviewed(Path(target), stage)
        except ValueError as e:
            log.error(f"✗ {e}")
            raise SystemExit(EXIT_GATE_VIOLATION) from None
        for path, old in changed:
            log.info(f"  {path}  {old or '(无标记)'} → {stage}")
        log.info(f"\n✓ {len(changed)} 个 draft 标为 {stage}")
        return

    art = Path(args.article) if args.article else None
    run(Path(args.raw), Path(args.drafts), Path(args.config), art,
        auto_accept=args.auto_accept,
        force=args.force,
        regenerate_outline=args.regenerate_outline,
        outline_only=args.outline_only)


if __name__ == "__main__":
    main()