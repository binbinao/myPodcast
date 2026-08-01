"""TTS 编排门面：根据 cfg['tts']['backend'] 路由到对应 backend。

具体 backend 在 src/backends/ 注册：新加 backend 只需新建文件用 @register，
config.yaml 的 tts.backend 即生效。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _enrich_with_emotion(segments: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """给每个 segment 注入 emotion 字段（按 prosody 启发式 / LLM）。
    当前实现：整段 emotion 取该段第一句 prosody 的标签。"""
    from .prosody import plan_sentences
    out = []
    for seg in segments:
        sents = plan_sentences(seg["text"], cfg)
        emo = sents[0]["emotion"] if sents else "calm"
        out.append({**seg, "emotion": emo})
    return out


def generate_audio(
    segments: list[dict[str, Any]],
    voice_map: dict[str, str],
    cfg: dict[str, Any],
    out_path: Path,
) -> int:
    """同步入口：选 backend → 调 generate，返回时长秒。"""
    import asyncio
    backend_name = cfg.get("tts", {}).get("backend", "edge-tts").lower()
    # 触发 backend 注册（如果上层未触发）
    from . import backends  # noqa: F401
    backend = backends.get_backend(backend_name)
    # 给 minimax 类 backend 注入 emotion（edge-tts 忽略 emotion 字段）
    if backend_name == "minimax":
        segments = _enrich_with_emotion(segments, cfg)
    return asyncio.run(backend.generate(segments, voice_map, cfg, out_path))


def build_episode_audio(
    segments: list[dict[str, Any]],
    voice_map: dict[str, str],
    cfg: dict[str, Any],
    out_dir: Path,
    title: str,
    series_title: str = "",
    series_slug: str = "",
    ep_index: int = 1,
) -> tuple[Path, int]:
    """生成一集音频到 output/series/<slug>/ep-XX/episode.mp3。"""
    out_dir = Path(out_dir)
    if not (series_title and series_slug):
        from .naming import chinese_to_ascii
        series_title = series_title or title
        series_slug = series_slug or chinese_to_ascii(series_title)
    from . import backends  # noqa: F401
    backend_name = cfg.get("tts", {}).get("backend", "edge-tts").lower()
    backend = backends.get_backend(backend_name)
    if backend_name == "minimax":
        from .prosody import plan_sentences
        enriched = []
        for seg in segments:
            sents = plan_sentences(seg["text"], cfg)
            emo = sents[0]["emotion"] if sents else "calm"
            enriched.append({**seg, "emotion": emo})
        segments = enriched
    return backend.build_episode(
        segments, voice_map, cfg, out_dir,
        series_title=series_title, series_slug=series_slug, ep_index=ep_index,
    )