"""edge-tts backend：免费中文音色，逐句 rate/pitch，句间 ffmpeg 静音。

限制：
- 实测 Communicate(text=...) 传完整 <speak> SSML 会被错误合成成超长音频 → 禁用 SSML。
- 逐句用各自 rate/pitch 构造参数 + ffmpeg 拼接 + 静音。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .base import Backend, register


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {r.stderr[-500:]}")


def _silence(path: Path, ms: int, sample_rate: int = 24000) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=mono:sample_rate={sample_rate}",
        "-t", f"{ms / 1000:.3f}", "-acodec", "libmp3lame", "-q:a", "9",
        str(path),
    ])


def _duration(path: Path) -> int:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return int(float(r.stdout.strip()))
    except ValueError:
        return 0


async def _speak(text: str, voice: str, out_path: Path,
                 rate: str, pitch: str, volume: str) -> None:
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


@register
class EdgeTTSBackend(Backend):
    name = "edge-tts"

    async def generate(self, segments, voice_map, cfg, out_path):
        from ..prosody import plan_sentences

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
                    p = tmp / f"{i:03d}_{j:03d}.mp3"
                    await _speak(s["text"], voice, p, s["rate"], s["pitch"], volume)
                    files.append(p)
                    if j < len(sents) - 1 and int(s["break_ms"]) > 0:
                        sil = tmp / f"b{i}_{j}.mp3"
                        _silence(sil, int(s["break_ms"]))
                        files.append(sil)
                if i < len(segments) - 1:
                    sil = tmp / f"s{i}.mp3"
                    _silence(sil, pause)
                    files.append(sil)

            inputs: list[str] = []
            for f in files:
                inputs += ["-i", str(f)]
            n = len(files)
            chain = "".join(f"[{j}:a]" for j in range(n))
            _run(["ffmpeg", "-y", *inputs, "-filter_complex",
                  f"{chain}concat=n={n}:v=0:a=1[out]", "-map", "[out]", str(out_path)])
        return _duration(out_path)