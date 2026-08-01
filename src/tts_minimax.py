"""MiniMax Speech TTS backend。

- 同步 HTTP POST /v1/t2a_v2，单次 < 10K 字符
- 输出 hex 编码 mp3
- 9 种 emotion：happy/sad/angry/fearful/disgusted/surprised/calm/fluent/whisper
- 文本内 <#x#> 控制停顿（秒）；22 种语气词标签透传 (laughs)/(sighs)/(breath)…
- 仅支持中文常用 8 个 voice_id（system voice）
"""
from __future__ import annotations

import asyncio
import binascii
import os
from pathlib import Path
from typing import Any

import requests

# 兼容 MINIMAX 与 MINIMAX 环境变量
DEFAULT_BASE_URL = "https://api.minimaxi.com/v1/t2a_v2"
VALID_MODELS = {"speech-2.8-hd", "speech-2.8-turbo", "speech-2.6-hd", "speech-2.6-turbo",
                "speech-02-hd", "speech-02-turbo", "speech-01-hd", "speech-01-turbo"}

# 常用 8 个中文系统音色（其它 300+ 通过 voice_id 传）
COMMON_ZH_VOICES = {
    "female-yujie": "御姐",
    "female-shaonv": "少女",
    "female-chengshu": "成熟女性",
    "female-tianmei": "甜美女性",
    "male-qn-qingse": "青涩青年",
    "male-qn-jingying": "精英青年",
    "male-qn-badao": "霸道青年",
    "male-qn-daxuesheng": "青年大学生",
}

# 9 种 emotion（speech-2.8 不支持 whisper）
ALL_EMOTIONS = ["happy", "sad", "angry", "fearful", "disgusted",
                "surprised", "calm", "fluent", "whisper"]


def _resolve_key(cfg: dict[str, Any]) -> str:
    return (
        os.environ.get("MINIMAX_API_KEY")
        or os.environ.get("MINIMAX_API_KEY")
        or cfg.get("api_key", "")
    )


def _speak_sync(
    text: str, voice_id: str, *, emotion: str | None,
    speed: float, pitch: int, vol: float, model: str, key: str, base_url: str,
) -> bytes:
    body = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed, "vol": vol, "pitch": pitch,
            **({"emotion": emotion} if emotion and emotion != "auto" else {}),
        },
        "audio_setting": {
            "sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1,
        },
        "language_boost": "Chinese",
        "output_format": "hex",
    }
    last: Exception | None = None
    for _ in range(3):
        try:
            r = requests.post(
                base_url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body, timeout=60,
            )
            r.raise_for_status()
            d = r.json()
            base = d.get("base_resp", {})
            if base.get("status_code") != 0:
                raise RuntimeError(f"MiniMax 业务错误: {base}")
            audio_hex = d.get("data", {}).get("audio")
            if not audio_hex:
                raise RuntimeError(f"MiniMax 返回空 audio: {d}")
            return binascii.unhexlify(audio_hex)
        except Exception as e:  # noqa: BLE001
            last = e
    raise last or RuntimeError("MiniMax TTS 失败")


async def _speak(
    text: str, voice_id: str, *, emotion: str | None,
    speed: float, pitch: int, vol: float, model: str, key: str, base_url: str,
) -> bytes:
    return await asyncio.to_thread(
        _speak_sync, text, voice_id,
        emotion=emotion, speed=speed, pitch=pitch, vol=vol,
        model=model, key=key, base_url=base_url,
    )


async def generate_audio_minimax(
    segments: list[dict[str, Any]],
    voice_map: dict[str, str],
    cfg: dict[str, Any],
    out_path: Path,
) -> int:
    """segments: [{role, text}]；每段一次 API 调用，ffmpeg concat+静音拼接。

    emotion 映射由 tts.py 统一传（已经在 prosody 阶段标注好）。
    """
    import subprocess

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tts_cfg = cfg.get("tts", {}).get("minimax", {})
    pause_ms = int(cfg.get("tts", {}).get("pause_ms", 600))
    key = _resolve_key(tts_cfg)
    if not key:
        raise RuntimeError("MINIMAX_API_KEY 未设置（export 或填 config.yaml 的 tts.minimax.api_key）")
    base_url = tts_cfg.get("base_url", DEFAULT_BASE_URL)
    model = tts_cfg.get("model", "speech-2.8-hd")
    if model not in VALID_MODELS:
        raise RuntimeError(f"不支持的 model: {model}")
    default_voice = voice_map.get("default", "female-yujie")
    speed = float(tts_cfg.get("speed", 1.0))
    vol = float(tts_cfg.get("vol", 1.0))
    pitch = int(tts_cfg.get("pitch", 0))

    def _silence(p: Path, ms: int) -> None:
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=32000",
            "-t", f"{ms / 1000:.3f}", "-acodec", "libmp3lame", "-q:a", "9", str(p),
        ], capture_output=True, check=True)

    def _dur(p: Path) -> int:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(p)],
            capture_output=True, text=True,
        )
        try:
            return int(float(r.stdout.strip()))
        except ValueError:
            return 0

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files: list[Path] = []
        for i, seg in enumerate(segments):
            voice_id = voice_map.get(seg["role"], default_voice)
            emotion = seg.get("emotion")  # 由 caller 注入
            mp3_bytes = await _speak(
                seg["text"], voice_id,
                emotion=emotion, speed=speed, pitch=pitch, vol=vol,
                model=model, key=key, base_url=base_url,
            )
            seg_path = tmp / f"{i:03d}.mp3"
            seg_path.write_bytes(mp3_bytes)
            files.append(seg_path)
            if i < len(segments) - 1:
                sil = tmp / f"s{i}.mp3"
                _silence(sil, pause_ms)
                files.append(sil)

        inputs: list[str] = []
        for f in files:
            inputs += ["-i", str(f)]
        n = len(files)
        chain = "".join(f"[{j}:a]" for j in range(n))
        subprocess.run(
            ["ffmpeg", "-y", *inputs, "-filter_complex", f"{chain}concat=n={n}:v=0:a=1[out]",
             "-map", "[out]", str(out_path)],
            capture_output=True, check=True,
        )
    return _dur(out_path)


def build_episode_audio_minimax(
    segments: list[dict[str, Any]],
    voice_map: dict[str, str],
    cfg: dict[str, Any],
    out_dir: Path,
    title: str,
) -> tuple[Path, int]:
    from .ingest import slugify

    out_dir = Path(out_dir)
    ep_dir = out_dir / slugify(title)
    ep_dir.mkdir(parents=True, exist_ok=True)
    mp3 = ep_dir / "episode.mp3"
    duration = asyncio.run(generate_audio_minimax(segments, voice_map, cfg, mp3))
    return mp3, duration