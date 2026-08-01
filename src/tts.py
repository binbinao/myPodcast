"""TTS：edge-tts 逐段生成 + ffmpeg 拼接，支持多角色音色与停顿。"""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import edge_tts

from .ingest import slugify


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {r.stderr[-500:]}")


async def _speak(text: str, voice: str, out_path: Path, tts_cfg: dict[str, Any]) -> None:
    comm = edge_tts.Communicate(
        text,
        voice,
        rate=tts_cfg.get("rate", "+0%"),
        volume=tts_cfg.get("volume", "+0%"),
        pitch=tts_cfg.get("pitch", "+0Hz"),
    )
    # 端点偶发抖动(NoAudioReceived)，重试 3 次
    last: Exception | None = None
    for _ in range(3):
        try:
            await comm.save(str(out_path))
            return
        except Exception as e:  # noqa: BLE001
            last = e
    raise last or RuntimeError("TTS 失败")


def _make_silence(path: Path, ms: int) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
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


async def generate_audio(
    segments: list[dict[str, str]],
    voice_map: dict[str, str],
    tts_cfg: dict[str, Any],
    out_path: Path,
) -> int:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pause = tts_cfg.get("pause_ms", 600)
    default_voice = voice_map.get("default", "zh-CN-XiaoxiaoNeural")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files: list[Path] = []
        for i, seg in enumerate(segments):
            voice = voice_map.get(seg["role"], default_voice)
            seg_path = tmp / f"{i:03d}.mp3"
            await _speak(seg["text"], voice, seg_path, tts_cfg)
            files.append(seg_path)
            if i < len(segments) - 1:
                sil = tmp / f"sil{i}.mp3"
                _make_silence(sil, pause)
                files.append(sil)

        inputs: list[str] = []
        for f in files:
            inputs += ["-i", str(f)]
        n = len(files)
        chain = "".join(f"[{j}:a]" for j in range(n))
        filter_desc = f"{chain}concat=n={n}:v=0:a=1[out]"
        _run(["ffmpeg", "-y", *inputs, "-filter_complex", filter_desc,
              "-map", "[out]", str(out_path)])
    return _duration(out_path)


def build_episode_audio(
    segments: list[dict[str, str]],
    voice_map: dict[str, str],
    tts_cfg: dict[str, Any],
    out_dir: Path,
    title: str,
) -> tuple[Path, int]:
    out_dir = Path(out_dir)
    slug = slugify(title)
    ep_dir = out_dir / slug
    ep_dir.mkdir(parents=True, exist_ok=True)
    mp3 = ep_dir / "episode.mp3"
    duration = asyncio.run(generate_audio(segments, voice_map, tts_cfg, mp3))
    return mp3, duration
