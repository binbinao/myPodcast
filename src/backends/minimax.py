"""MiniMax Speech backend：按段 HTTP POST，emotion 控制，22 种语气词。

- 端点：POST /v1/t2a_v2 同步；hex 编码 mp3 返回
- 单次 < 10K 字符；段内按 chunk_chars 自动切
- 鉴权：Authorization: Bearer MINIMAX_API_KEY
- 重试 + 指数退避
"""
from __future__ import annotations

import asyncio
import binascii
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

from .base import Backend, register


DEFAULT_BASE_URL = "https://api.minimaxi.com/v1/t2a_v2"
VALID_MODELS = {
    "speech-2.8-hd", "speech-2.8-turbo",
    "speech-2.6-hd", "speech-2.6-turbo",
    "speech-02-hd", "speech-02-turbo",
    "speech-01-hd", "speech-01-turbo",
}

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

ALL_EMOTIONS = ["happy", "sad", "angry", "fearful", "disgusted",
                "surprised", "calm", "fluent", "whisper"]


def _resolve_key(cfg: dict[str, Any]) -> str:
    return (
        os.environ.get("MINIMAX_API_KEY")
        or os.environ.get("MINIMAX_API_KEY")
        or cfg.get("api_key", "")
    )


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """段内按 max_chars 字符切片；按句末标点优先；避免词中切。"""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[。！？；\n])", text)
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        if not s:
            continue
        if len(cur) + len(s) <= max_chars:
            cur += s
        else:
            if cur:
                chunks.append(cur)
            while len(s) > max_chars:
                chunks.append(s[:max_chars])
                s = s[max_chars:]
            cur = s
    if cur:
        chunks.append(cur)
    return chunks


def _speak_sync(
    text: str, voice_id: str, *, emotion: str | None,
    speed: float, pitch: int, vol: float, model: str, key: str, base_url: str,
    timeout: int = 60,
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
    for attempt in range(3):
        try:
            r = requests.post(
                base_url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body, timeout=timeout,
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
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise last or RuntimeError("MiniMax TTS 失败")


async def _speak(
    text: str, voice_id: str, *, emotion: str | None,
    speed: float, pitch: int, vol: float, model: str, key: str, base_url: str,
    timeout: int = 60,
) -> bytes:
    return await asyncio.to_thread(
        _speak_sync, text, voice_id,
        emotion=emotion, speed=speed, pitch=pitch, vol=vol,
        model=model, key=key, base_url=base_url,
        timeout=timeout,
    )


@register
class MiniMaxBackend(Backend):
    name = "minimax"

    async def generate(self, segments, voice_map, cfg, out_path):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tts_cfg = cfg.get("tts", {}).get("minimax", {})
        pause_ms = int(cfg.get("tts", {}).get("pause_ms", 600))
        chunk_chars = int(tts_cfg.get("chunk_chars", 1800))
        timeout_sec = int(tts_cfg.get("timeout_sec", 60))
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

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            files: list[Path] = []
            idx = 0
            for i, seg in enumerate(segments):
                voice_id = voice_map.get(seg["role"], default_voice)
                emotion = seg.get("emotion")
                chunks = _chunk_text(seg["text"], chunk_chars)
                for _c_idx, chunk in enumerate(chunks):
                    mp3_bytes = await _speak(
                        chunk, voice_id,
                        emotion=emotion, speed=speed, pitch=pitch, vol=vol,
                        model=model, key=key, base_url=base_url,
                        timeout=timeout_sec,
                    )
                    p = tmp / f"{idx:03d}.mp3"
                    p.write_bytes(mp3_bytes)
                    files.append(p)
                    idx += 1
                if i < len(segments) - 1:
                    sil = tmp / f"s{i}.mp3"
                    _silence(sil, pause_ms)
                    files.append(sil)

            inputs: list[str] = []
            for f in files:
                inputs += ["-i", str(f)]
            n = len(files)
            afmt = "aformat=sample_fmts=fltp:sample_rates=32000:channel_layouts=mono"
            chain_fmt = "".join(f"[{j}:a]{afmt}[a{j}];" for j in range(n))
            concat_part = "".join(f"[a{j}]" for j in range(n))
            filter_desc = (
                f"{chain_fmt}{concat_part}concat=n={n}:v=0:a=1[cat];"
                f"[cat]aresample=32000[out]"
            )
            r = subprocess.run(
                ["ffmpeg", "-y", *inputs, "-filter_complex", filter_desc,
                 "-map", "[out]", "-c:a", "libmp3lame", "-ar", "32000",
                 "-ac", "1", "-b:a", "128k", str(out_path)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg concat 失败 (exit {r.returncode}): {r.stderr[-600:]}")
        return _dur(out_path)