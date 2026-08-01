"""myPodcast 流水线编排 CLI。

用法:
    python -m src.build episodes/demo.md
    python -m src.build episodes/demo.md --out output --config config.yaml
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .feed import build_feed, build_index, register_episode, write_shownotes
from .ingest import parse_script, slugify
from .polish import polish
from .tts import build_episode_audio


def run_one(episode_path: Path, out_dir: Path, cfg: dict[str, Any]) -> None:
    raw = Path(episode_path).read_text(encoding="utf-8")

    print(f"[1/5] 润色脚本: {episode_path.name}")
    polished = polish(raw, cfg)

    print("[2/5] 解析分段")
    meta, segments = parse_script(polished)
    if not segments:
        raise SystemExit("✗ 没有可朗读的内容，检查脚本格式或 frontmatter。")
    title = meta.get("title") or Path(episode_path).stem
    print(f"      共 {len(segments)} 段，标题《{title}》")

    print("[3/5] 生成音频 (edge-tts)")
    voice_map = cfg.get("voices", {})
    mp3, duration = build_episode_audio(segments, voice_map, cfg, out_dir, title)
    ep_dir = mp3.parent
    size = mp3.stat().st_size
    print(f"      → {mp3}  ({duration // 60}分{duration % 60}秒, {size // 1024}KB)")

    print("[4/5] 写 shownotes")
    write_shownotes(ep_dir, meta, segments, duration)

    print("[5/5] 更新 RSS / 节目站")
    slug = slugify(title)
    register_episode(out_dir, meta, slug, duration, size)


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
    print(f"处理 {n} 个脚本…\n")
    for i, s in enumerate(scripts, 1):
        print(f"===== [{i}/{n}] {s.name} =====")
        run_one(s, out_dir, cfg)

    feed = build_feed(out_dir, cfg.get("podcast", {}))
    index = build_index(out_dir, cfg.get("podcast", {}))
    print("\n✓ 全部完成")
    print(f"  RSS : {feed}")
    print(f"  站点: {index}")


def main() -> None:
    ap = argparse.ArgumentParser(description="myPodcast 文字转语音流水线")
    ap.add_argument("episode", help="播客脚本 markdown 路径，或含多个脚本的目录（如 drafts/xxx）")
    ap.add_argument("--out", default="output", help="输出目录 (默认 output)")
    ap.add_argument("--config", default="config.yaml", help="配置文件 (默认 config.yaml)")
    args = ap.parse_args()
    run(Path(args.episode), Path(args.out), Path(args.config))


if __name__ == "__main__":
    main()
