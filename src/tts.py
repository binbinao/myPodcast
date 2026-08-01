"""TTS 编排：根据 cfg['tts']['backend'] 选 edge-tts / minimax backend。

edge-tts：逐句 rate/pitch + 句间 ffmpeg 静音，免费；SSML 已被实测禁用（会超长）。
minimax ：按段 HTTP POST，emotion 控制、22 种语气词透传，需 MINIMAX_API_KEY。
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from .ingest import slugify


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {r.stderr[-500:]}")


def _make_silence(path: Path, ms: int, sample_rate: int = 24000) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=mono:sample_rate={sample_rate}",
        "-t", f"{ms / 1000:.3f}", "-acodec", "libmp3lame", "-q:a", "9",
        str(path),
    ])


def _duration(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return int(float(out.stdout.strip()))
    except ValueError:
        return 0


async def _edge_speak(
    text: str, voice: str, out_path: Path, rate: str, pitch: str, volume: str,
) -> None:
    import edge_tts
    last: Exception | None = None
    for _ in range(3):
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
            await comm.save(str(out_path))
            return
        except Exception as e:  # noqa: BLE001
            last = e
    raise last or RuntimeError("edge-tts TTS 失败")


async def _generate_edge(segments, voice_map, cfg, out_path):
    import tempfile
    from .prosody import plan_sentences
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tts_cfg = cfg.get("tts", {})
    pause = tts_cfg.get("pause_ms", 600)
    volume = tts_cfg.get("volume", "+0%")
    default_voice = voice_map.get("default", "zh-CN-XiaoxiaoNeural")
    use_prosody = bool(cfg.get("prosody", {}).get("enable", True))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files: list[Path] = []
        for i, seg in enumerate(segments):
            voice = voice_map.get(seg["role"], default_voice)
            if use_prosody:
                sents = plan_sentences(seg["text"], cfg)
            else:
                sents = [{"text": seg["text"], "rate": tts_cfg.get("rate", "+0%"),
                          "pitch": tts_cfg.get("pitch", "+0Hz"), "break_ms": 0}]
            for j, s in enumerate(sents):
                seg_path = tmp / f"{i:03d}_{j:03d}.mp3"
                await _edge_speak(s["text"], voice, seg_path, s["rate"], s["pitch"], volume)
                files.append(seg_path)
                if j < len(sents) - 1 and int(s["break_ms"]) > 0:
                    sil = tmp / f"b{i}_{j}.mp3"
                    _make_silence(sil, int(s["break_ms"]))
                    files.append(sil)
            if i < len(segments) - 1:
                sil = tmp / f"s{i}.mp3"
                _make_silence(sil, pause)
                files.append(sil)
        inputs: list[str] = []
        for f in files:
            inputs += ["-i", str(f)]
        n = len(files)
        chain = "".join(f"[{j}:a]" for j in range(n))
        _run(["ffmpeg", "-y", *inputs, "-filter_complex",
              f"{chain}concat=n={n}:v=0:a=1[out]", "-map", "[out]", str(out_path)])
    return _duration(out_path)


async def _generate_minimax(segments, voice_map, cfg, out_path):
    from .tts_minimax import generate_audio_minimax
    return await generate_audio_minimax(segments, voice_map, cfg, out_path)


def _enrich_with_emotion(segments, cfg):
    """给每个 segment 注入 emotion 字段（按 prosody 启发式 / LLM）。minimax 用。"""
    from .prosody import plan_sentences
    out = []
    for seg in segments:
        sents = plan_sentences(seg["text"], cfg)
        # 整段 emotion 取该段第一句 / 整体模式
        emo = sents[0]["emotion"] if sents else "calm"
        out.append({**seg, "emotion": emo})
    return out


async def generate_audio(
    segments: list[dict[str, str]],
    voice_map: dict[str, str],
    cfg: dict[str, Any],
    out_path: Path,
) -> int:
    backend = cfg.get("tts", {}).get("backend", "edge-tts").lower()
    if backend == "minimax":
        segments = _enrich_with_emotion(segments, cfg)
        return await _generate_minimax(segments, voice_map, cfg, out_path)
    return await _generate_edge(segments, voice_map, cfg, out_path)


def build_episode_audio(
    segments: list[dict[str, str]],
    voice_map: dict[str, str],
    cfg: dict[str, Any],
    out_dir: Path,
    title: str,
) -> tuple[Path, int]:
    out_dir = Path(out_dir)
    ep_dir = out_dir / slugify(title)
    ep_dir.mkdir(parents=True, exist_ok=True)
    mp3 = ep_dir / "episode.mp3"
    duration = asyncio.run(generate_audio(segments, voice_map, cfg, mp3))
    return mp3, duration
