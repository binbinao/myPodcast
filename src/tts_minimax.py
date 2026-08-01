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
                import time as _t
                _t.sleep(2 ** attempt)
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


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """段内按 max_chars 字符切片；按句末标点优先；避免词中切。"""
    if len(text) <= max_chars:
        return [text]
    import re
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
            # 单句超长，强制按 max_chars 硬切
            while len(s) > max_chars:
                chunks.append(s[:max_chars])
                s = s[max_chars:]
            cur = s
    if cur:
        chunks.append(cur)
    return chunks


async def generate_audio_minimax(
    segments: list[dict[str, Any]],
    voice_map: dict[str, str],
    cfg: dict[str, Any],
    out_path: Path,
) -> int:
    """segments: [{role, text}]；每段一次 API 调用，ffmpeg concat+静音拼接。

    段内自动按 chunk_chars 切（避免单段 > 2000 字符触发 API 限速或超时）。
    emotion 映射由 tts.py 统一传（已经在 prosody 阶段标注好）。
    """
    import subprocess

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

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files: list[Path] = []
        idx = 0
        for i, seg in enumerate(segments):
            voice_id = voice_map.get(seg["role"], default_voice)
            emotion = seg.get("emotion")
            chunks = _chunk_text(seg["text"], chunk_chars)
            chunk_files: list[Path] = []
            for c_idx, chunk in enumerate(chunks):
                mp3_bytes = await _speak(
                    chunk, voice_id,
                    emotion=emotion, speed=speed, pitch=pitch, vol=vol,
                    model=model, key=key, base_url=base_url,
                    timeout=timeout_sec,
                )
                p = tmp / f"{idx:03d}.mp3"
                p.write_bytes(mp3_bytes)
                chunk_files.append(p)
                idx += 1
            # 同段内 chunk 之间不加额外静音（句末静音已够用）
            files.extend(chunk_files)
            if i < len(segments) - 1:
                sil = tmp / f"s{i}.mp3"
                _silence(sil, pause_ms)
                files.append(sil)

        inputs: list[str] = []
        for f in files:
            inputs += ["-i", str(f)]
        n = len(files)
        # aformat 归一化每段（minimax mp3 mime 标签 mp4a → 段间采样率/codec 不一致）
        # 再 aresample + asetnsamples，确保 concat 输出的音频能被 libmp3lame 编码
        afmt = "aformat=sample_fmts=fltp:sample_rates=32000:channel_layouts=mono"
        chain_fmt = "".join(f"[{j}:a]{afmt}[a{j}];" for j in range(n))
        concat_part = "".join(f"[a{j}]" for j in range(n))
        filter_desc = (
            f"{chain_fmt}{concat_part}concat=n={n}:v=0:a=1[cat];"
            f"[cat]aresample=32000[out]"
        )
        # 末尾明确指定 mp3 编码参数（避免 libmp3lame 报 -22 Invalid argument）
        encode_args = [
            "-c:a", "libmp3lame", "-ar", "32000", "-ac", "1", "-b:a", "128k",
        ]
        r = subprocess.run(
            ["ffmpeg", "-y", *inputs, "-filter_complex", filter_desc,
             "-map", "[out]", *encode_args, str(out_path)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg concat 失败 (exit {r.returncode}): {r.stderr[-600:]}")
    return _dur(out_path)


def build_episode_audio_minimax(
    segments: list[dict[str, Any]],
    voice_map: dict[str, str],
    cfg: dict[str, Any],
    out_dir: Path,
    title: str,
    series_title: str = "",
    series_slug: str = "",
    ep_index: int = 1,
) -> tuple[Path, int]:
    from .naming import ep_output_dir as _ep_output_dir, chinese_to_ascii

    out_dir = Path(out_dir)
    if series_title and series_slug:
        ep_dir = Path(_ep_output_dir(str(out_dir), series_title, ep_index, series_slug))
    else:
        s_slug = chinese_to_ascii(series_title or title)
        ep_dir = Path(_ep_output_dir(str(out_dir), series_title or title, ep_index, s_slug))
    ep_dir.mkdir(parents=True, exist_ok=True)
    mp3 = ep_dir / "episode.mp3"
    duration = asyncio.run(generate_audio_minimax(segments, voice_map, cfg, mp3))
    return mp3, duration