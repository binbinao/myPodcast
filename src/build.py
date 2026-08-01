"""myPodcast 流水线编排 CLI。

用法:
    python -m src.build episodes/demo.md
    python -m src.build episodes/demo.md --out output --config config.yaml
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from .feed import build_feed, build_index, register_episode, write_shownotes
from .log import logger as log
from .ingest import parse_script, slugify
from .polish import polish
from .tts import build_episode_audio
from .voicecaster import cast as vc_cast


def run_one(episode_path: Path, out_dir: Path, cfg: dict[str, Any]) -> None:
    raw = Path(episode_path).read_text(encoding="utf-8")

    log.info(f"[1/5] 润色脚本: {episode_path.name}")
    polished = polish(raw, cfg)

    log.info("[2/5] 解析分段")
    meta, segments = parse_script(polished)
    if not segments:
        raise SystemExit("✗ 没有可朗读的内容，检查脚本格式或 frontmatter。")
    title = meta.get("title") or Path(episode_path).stem
    log.info(f"      共 {len(segments)} 段，标题《{title}》")

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
            raise SystemExit(f"✗ --skip-audio 但 {mp3} 不存在；先跑一次非 skip-audio build")
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


def run(target: Path, out_dir: Path, config_path: Path) -> None:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    out_dir = Path(out_dir)

    if target.is_dir():
        scripts = sorted(target.glob("*.md"))
        if not scripts:
            raise SystemExit(f"✗ 目录 {target} 下没有脚本 markdown")
    else:
        scripts = [target]

    n = len(scripts)
    log.info(f"处理 {n} 个脚本…\n")
    for i, s in enumerate(scripts, 1):
        log.info(f"===== [{i}/{n}] {s.name} =====")
        run_one(s, out_dir, cfg)

    feed = build_feed(out_dir, cfg.get("podcast", {}))
    index = build_index(out_dir, cfg.get("podcast", {}))
    log.info("\n✓ 全部完成")
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
    ap.add_argument("--log-file", default=None, help="追加日志到此文件（默认仅 stdout）")
    ap.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR（默认 INFO）")
    args = ap.parse_args()
    configure(level=args.log_level, log_file=args.log_file)
    SKIP_AUDIO = args.skip_audio
    run(Path(args.episode), Path(args.out), Path(args.config))


if __name__ == "__main__":
    main()
