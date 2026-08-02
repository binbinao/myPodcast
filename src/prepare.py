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
import re
from datetime import date
from pathlib import Path

import yaml

from .generate import draft_dir_for, draft_filename, generate_script
from .ingest import parse_script
from .log import logger as log
from .naming import chinese_to_ascii
from .split import plan_episodes

H1_RE = re.compile(r"^#\s+(.+)$", re.M)


def _article_meta(article: str, path: Path, fmt_default: str) -> tuple[str, str, int | None, str, str]:
    """返回 (title, format, episodes_n, article_date, explicit_slug)。"""
    meta, _ = parse_script(article)
    title = meta.get("title") or (H1_RE.search(article) and H1_RE.search(article).group(1).strip())
    if not title:
        title = path.stem
    fmt = str(meta.get("format", fmt_default)).lower()
    if fmt not in ("solo", "duo"):
        fmt = fmt_default
    episodes = meta.get("episodes")
    if episodes is not None:
        try:
            episodes = int(episodes)
        except (TypeError, ValueError):
            episodes = None
    # 日期：优先 frontmatter date → 否则从 raw 文件名 YYYY-MM-DD- 抽 → 否则今日
    art_date = str(meta.get("date") or "")
    if not art_date:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-", path.stem)
        if m:
            art_date = m.group(1)
    if not art_date:
        art_date = date.today().isoformat()
    # slug 优先 frontmatter series_slug → 否则 slug → 否则从 raw 文件名（去掉日期前缀）
    # 兜底。**不再走 chinese_to_ascii(title)**——2026-08-02 拍板，pipeline 不再越权
    # 决定命名；raw 文件用什么名，drafts/ 目录就跟什么名。
    explicit_slug = (
        str(meta.get("series_slug") or "").strip()
        or str(meta.get("slug") or "").strip()
    )
    if not explicit_slug:
        m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", path.stem)
        if m:
            explicit_slug = m.group(1).strip()
    return title, fmt, episodes, art_date, explicit_slug


def prepare_file(
    path: Path,
    cfg: dict[str, Any],
    drafts_dir: Path,
    auto_accept: bool = False,
) -> list[Path]:
    article = path.read_text(encoding="utf-8")
    fmt_default = str(cfg.get("format", "duo")).lower()
    series_title, fmt, episodes, art_date, explicit_slug = _article_meta(
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

    if fm_format in ("solo", "duo") and fm_voice and fm_split:
        # frontmatter 三件套都齐：尊重用户，不打扰
        log.info(f"  frontmatter 三件套齐全（format={fm_format}/voice={fm_voice}/split={fm_split}），跳过决策门")
        from .decisions import Decisions
        decisions = Decisions(
            format=fm_format, voice=fm_voice, voice_type="(frontmatter)",
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
        decisions.split_strategy = decisions.split_strategy or fm_split or "auto"

    # 写决策日志（_decisions.json），与 draft 同目录，方便审计
    out_dir = Path(draft_dir_for(art_date, series_title, explicit_slug, str(drafts_dir)))
    save_decisions(out_dir, decisions)

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
    made: list[Path] = []
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
        script = generate_script(plan, cfg, source_rel)
        f = out_dir / draft_filename(plan)
        f.write_text(script, encoding="utf-8")
        made.append(f)
    log.info(f"  {path.name} → 《{series_title}》{len(plans)} 集 → {out_dir}")
    return made


def run(
    raw_dir: Path,
    drafts_dir: Path,
    config_path: Path,
    article: Path | None = None,
    auto_accept: bool = False,
) -> None:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    drafts_dir = Path(drafts_dir)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    # 不再 hard gate 静默 rename：raw 文件名由作者自主决定（frontmatter slug
    # 是 preferred，但 prepare 不再越权改用户命名）。2026-08-02 与斌哥拍板取消
    # silent rename——个人内容资产，英文/拼音/中文都应该是用户说了算。
    if article:
        prepare_file(Path(article), cfg, drafts_dir, auto_accept=auto_accept)
        return
    raw_dir = Path(raw_dir)
    files = sorted(raw_dir.glob("*.md"))
    if not files:
        log.info(f"⚠ raw/ 下没有 markdown 文章（{raw_dir}）")
        return
    total = 0
    for f in files:
        total += len(prepare_file(f, cfg, drafts_dir, auto_accept=auto_accept))
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
        auto_accept=args.auto_accept)


if __name__ == "__main__":
    main()
