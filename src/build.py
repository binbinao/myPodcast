"""myPodcast 流水线编排 CLI。

用法:
    python -m src.build episodes/demo.md
    python -m src.build episodes/demo.md --out output --config config.yaml
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .core import EXIT_GATE_VIOLATION, EXIT_PIPELINE_FAIL, GateViolation, PipelineError
from typing import Any

import yaml

from .feed import build_feed, build_index, register_episode, write_shownotes
from .log import logger as log
from .ingest import parse_script, slugify
from .stages import stage_of, stage_warning
from .tts import build_episode_audio
from .voicecaster import cast as vc_cast


def run_one(episode_path: Path, out_dir: Path, cfg: dict[str, Any]) -> None:
    raw = Path(episode_path).read_text(encoding="utf-8")

    # draft 只读契约：build 不再跑 polish() 二次 LLM 改写。
    # 重构前 `polished = polish(raw, cfg)` 会把 drafts/ 里的人工修改喂给 LLM 重写一遍
    # → 人工改动被吃、LLM 成本翻倍、同一 draft 每次 build 输出不同（不可复现）。
    # 现在正文逐字节来自 draft；stage 只决定告警等级（src/stages.py）。
    log.info(f"[1/5] 读取 draft: {episode_path.name}")

    log.info("[2/5] 解析分段")
    meta, segments = parse_script(raw)
    warn = stage_warning(stage_of(meta))
    if warn:
        log.warning(f"      ⚠ {warn}")
    if not segments:
        raise PipelineError(
            "没有可朗读的内容，检查脚本格式或 frontmatter。",
            hint="脚本是否只有 frontmatter 没有 [host]/[guest] 段？",
        )
    title = meta.get("title") or Path(episode_path).stem
    log.info(f"      共 {len(segments)} 段，标题《{title}》")

    # 脚本质量校验：BLOCK 硬门 + WARN 软告警（Phase 3 落地重构路线图 P0-B）
    # 重构前只 report_and_warn，emoji/井号直接进 TTS 烧钱；
    # 现在 has_blocking → raise PipelineError，让 run() 计入 failed 列表并 sys.exit(1)。
    from .validate import has_blocking, report_and_warn, validate_script
    # 把 frontmatter 与正文分离
    import re as _re
    fm_match = _re.match(r"^---\n.*?\n---\n(.*)$", raw, flags=_re.S)
    body_text = fm_match.group(1) if fm_match else raw
    warnings = validate_script(meta, body_text)
    report_and_warn(episode_path.name, warnings)
    if has_blocking(warnings):
        from .validate import blocking_summary
        raise PipelineError(
            f"脚本质量 BLOCK（{episode_path.name}）",
            hint=blocking_summary(warnings),
        )

    backend = cfg.get("tts", {}).get("backend", "edge-tts").lower()
    log.info(f"[3/5] 生成音频 (backend={backend})")
    voice_key = "voices_minimax" if backend == "minimax" else "voices"
    voice_map = dict(cfg.get(voice_key, {}))  # 拷贝，避免改全局配置

    # 音色选型：仅 minimax backend 用 voicecaster；duo 节目保留 host/guest 映射
    fmt = str(meta.get("format", "")).lower()
    if backend == "minimax" and fmt != "duo":
        explicit = meta.get("voice")  # frontmatter 显式 voice 字段
        source_rel = meta.get("source")
        article_text = raw
        if source_rel:
            src_path = Path(source_rel)
            if src_path.exists():
                article_text = src_path.read_text(encoding="utf-8")
        chosen = vc_cast(article_text, cfg, explicit=explicit)
        voice_map["default"] = chosen
        log.info(f"      voicecaster → {chosen}")

    series_slug = meta.get("series_slug", "")
    series_title_v = meta.get("series", "")
    ep_index = int(meta.get("episode", 1) or 1)

    if SKIP_AUDIO:
        # 跳过 TTS 生成：用现有 mp3 元数据（用于纯重渲 index/feed/shownotes）
        from .naming import ep_output_dir as _ep_out_dir
        ep_dir = Path(_ep_out_dir(str(out_dir), series_title_v, ep_index, series_slug))
        mp3 = ep_dir / "episode.mp3"
        if not mp3.exists():
            # --skip-audio 但没有现成 mp3：常见于 CI 拿到一批新 draft 但还没 build 过音频。
            # 不再 raise（之前会直接 SystemExit 让 CI 红），改成 warning + 跳过本集。
            log.warning(f"      ⊘ {mp3} 不存在，跳过本集（先跑一次非 skip-audio build 生音频）")
            return "skipped"  # 信号给 run() 区分「正常跳过（TTS 跳）」和「无产物跳过」
        duration = _ffprobe_duration(mp3)
        size = mp3.stat().st_size
        log.info(f"      → (skip) {mp3}  ({duration // 60}分{duration % 60}秒, {size // 1024}KB)")
    else:
        mp3, duration = build_episode_audio(
            segments, voice_map, cfg, out_dir, title,
            series_title=series_title_v,
            series_slug=series_slug,
            ep_index=ep_index,
        )
        ep_dir = mp3.parent
        size = mp3.stat().st_size
        log.info(f"      → {mp3}  ({duration // 60}分{duration % 60}秒, {size // 1024}KB)")

    log.info("[4/5] 写 shownotes")
    write_shownotes(ep_dir, meta, segments, duration)

    log.info("[5/5] 更新 RSS / 节目站")
    slug = meta.get("series_slug") or slugify(meta.get("series") or title)
    register_episode(out_dir, meta, slug, duration, size)


SKIP_AUDIO = False


def _ffprobe_duration(mp3: Path) -> int:
    import subprocess
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(mp3)],
        capture_output=True, text=True,
    )
    try:
        return int(float(r.stdout.strip()))
    except ValueError:
        return 0


def run(
    target: Path, out_dir: Path, config_path: Path,
    *,
    only: str | None = None,
    from_ep: str | None = None,
    retry_failed: bool = False,
    force: bool = False,
) -> None:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    out_dir = Path(out_dir)

    if target.is_dir():
        # 递归收集 drafts 下所有 ep-XX.md（命名重构后：drafts/<series>/ep-XX.md 嵌套结构）
        # 只匹配 ep-XX.md 形式，过滤潜在的 README/笔记文件
        scripts = sorted(
            p for p in target.glob("**/*.md") if re.match(r"^ep-\d+\.md$", p.name)
        )
        if not scripts:
            raise PipelineError(
                f"目录 {target} 下没有 ep-XX.md 脚本",
                hint="确认 drafts/<series>/ep-XX.md 嵌套结构存在；README/笔记不被识别。",
            )
    else:
        scripts = [target]  # 单文件路径（local 调试用）

    # 过滤脚本列表（断点续传）
    if only:
        scripts = [s for s in scripts if s.stem == only]
        if not scripts:
            raise PipelineError(
                f"--only {only} 找不到对应 draft",
                hint="ep 文件名应为 ep-01.md / ep-02.md 形式。",
            )
    if from_ep:
        idx = next((i for i, s in enumerate(scripts) if s.stem == from_ep), None)
        if idx is None:
            raise PipelineError(f"--from {from_ep} 找不到")
        scripts = scripts[idx:]

    # 读 manifest（断点续传参考）
    from .feed import load_manifest
    manifest = load_manifest(out_dir)
    existing_keys = {e.get("_key"): e for e in manifest.get("episodes", [])}

    n_total = len(scripts)
    skipped: list[str] = []
    failed: list[str] = []
    n_run = 0
    for i, s in enumerate(scripts, 1):
        # 预解析 frontmatter 拿 series_slug + ep_index 算 _key
        from .ingest import parse_script
        meta_pre, _ = parse_script(s.read_text(encoding="utf-8"))
        series_slug = meta_pre.get("series_slug", "")
        ep_idx = int(meta_pre.get("episode", 1) or 1)
        key = f"{series_slug}::ep-{ep_idx:02d}"

        # 断点续传：已成功且 source_hash 未变 → 跳过
        if not force and not retry_failed and key in existing_keys:
            old = existing_keys[key]
            from .feed import _hash_source
            src_h = _hash_source(meta_pre.get("source", ""))
            if src_h and old.get("source_hash") == src_h:
                # 检查 mp3 是否真存在
                mp3 = out_dir / "series" / series_slug / f"ep-{ep_idx:02d}" / "episode.mp3"
                if mp3.exists():
                    skipped.append(s.name)
                    log.info(f"  [{i}/{n_total}] ⊝ 跳过 {s.name} (manifest 已注册)")
                    continue

        log.info(f"===== [{i}/{n_total}] {s.name} =====")
        try:
            result = run_one(s, out_dir, cfg)
            if result == "skipped":
                skipped.append(s.name)
            else:
                n_run += 1
        except Exception as e:  # noqa: BLE001
            failed.append(s.name)
            log.error(f"  ✗ {s.name} 失败: {e}")
            if force or from_ep:
                raise  # --only/--from 模式下任何失败立即停

    log.info(
        f"\n完成 · 运行 {n_run} / 跳过 {len(skipped)} / 失败 {len(failed)}"
    )
    if skipped:
        log.info(f"  跳过: {', '.join(skipped)}")
    if failed:
        log.error(f"  失败: {', '.join(failed)}")

    # 退出码契约：失败非空 → sys.exit(1)，不重建 RSS/index（避免发布残缺站点）。
    if failed:
        sys.exit(EXIT_PIPELINE_FAIL)

    feed = build_feed(out_dir, cfg.get("podcast", {}))
    index = build_index(out_dir, cfg.get("podcast", {}))
    log.info(f"  RSS : {feed}")
    log.info(f"  站点: {index}")


def main() -> None:
    global SKIP_AUDIO
    from .log import configure
    ap = argparse.ArgumentParser(description="myPodcast 文字转语音流水线")
    ap.add_argument("episode", help="播客脚本 markdown 路径，或含多个脚本的目录（如 drafts/xxx）")
    ap.add_argument("--out", default="output", help="输出目录 (默认 output)")
    ap.add_argument("--config", default="config.yaml", help="配置文件 (默认 config.yaml)")
    ap.add_argument("--skip-audio", action="store_true",
                    help="跳过 TTS 生成，仅用现有 mp3 重渲 shownotes/RSS/index（命名重构后修复 manifest 用）")
    ap.add_argument("--only", default=None, metavar="ep-XX",
                    help="只处理单集（如 ep-01），常配合 --force 调试")
    ap.add_argument("--from", dest="from_ep", default=None, metavar="ep-XX",
                    help="从指定集开始（断点续传）。失败时立即停")
    ap.add_argument("--retry-failed", action="store_true",
                    help="只跑上次失败的集（manifest 没 source_hash 的视为失败）")
    ap.add_argument("--force", action="store_true",
                    help="强制重生成已有 mp3，忽略 source_hash")
    ap.add_argument("--log-file", default=None, help="追加日志到此文件（默认仅 stdout）")
    ap.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR（默认 INFO）")
    args = ap.parse_args()
    configure(level=args.log_level, log_file=args.log_file)
    SKIP_AUDIO = args.skip_audio
    try:
        run(
            Path(args.episode), Path(args.out), Path(args.config),
            only=args.only,
            from_ep=args.from_ep,
            retry_failed=args.retry_failed,
            force=args.force,
        )
    except PipelineError as e:
        log.error(f"\n✗ 流水线失败: {e}")
        if e.hint:
            log.error(f"  提示: {e.hint}")
        sys.exit(e.code)


if __name__ == "__main__":
    main()
