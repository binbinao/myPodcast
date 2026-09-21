"""SCNet Qwen3-TTS backend：超算互联网「语音合成」API（Qwen3-TTS-Instruct-Flash）。

- 端点：POST https://api.scnet.cn/api/llm/v1/audios/generations（同步，Bearer 鉴权）
- 响应：JSON，output.results[0] 为音频 URL（24h 有效），立即下载转存
- 计费：按输入字符数（usage.input_chars_num）
- 特色：input.instructions 用自然语言控制语气/情感/语速（Instruct 版独有）
- 鉴权：Authorization: Bearer SCNET_API_KEY
- 重试：网络/5xx 重试 3 次 + 指数退避；4xx 业务错误不重试
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

from .base import Backend, register

DEFAULT_BASE_URL = "https://api.scnet.cn/api/llm/v1/audios/generations"
DEFAULT_MODEL = "Qwen3-TTS-Instruct-Flash"

# Qwen3-TTS Instruct 版常用音色（voice 参数直接传英文名）
COMMON_ZH_VOICES = {
    "Ethan": "晨煦·男·阳光温暖有活力（带北方口音）",
    "Elias": "墨讲师·男·学术严谨会讲故事",
    "Cherry": "芊悦·女·阳光积极亲切",
    "Serena": "苏瑶·女·温柔",
    "Ryan": "甜茶·男·有节奏感戏剧化",
    "Moon": "男·随性帅气",
}

# prosody emotion 标签 → 自然语言指令（注入 instructions）
_EMO_INSTRUCTIONS = {
    "happy": "用轻快愉悦的语气",
    "excited": "用兴奋昂扬的语气",
    "sad": "用低沉伤感的语气",
    "angry": "用愤怒的语气",
    "fearful": "用紧张不安的语气",
    "surprised": "用惊讶的语气",
    "calm": "用平静沉稳的语气",
    "fluent": "用流畅自然的语气",
    "whisper": "用轻声细语的语气",
    "neutral": "用自然平稳的语气",
    "question": "用带疑问上扬的语气",
    "thoughtful": "用沉思的语气",
    "serious": "用严肃认真的语气",
}


def _resolve_key(cfg: dict[str, Any]) -> str:
    return (
        os.environ.get("SCNET_API_KEY")
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


def _download(url: str, timeout: int = 120) -> bytes:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def _speak_sync(
    text: str, voice: str, *, instructions: str | None,
    model: str, key: str, base_url: str, timeout: int,
    max_retries: int = 3,
) -> bytes:
    body: dict[str, Any] = {
        "model": model,
        "input": {
            "text": text,
            "voice": voice,
            **({"instructions": instructions} if instructions else {}),
        },
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    last: Exception | None = None
    for attempt in range(max_retries):
        try:
            r = requests.post(base_url, headers=headers, json=body, timeout=timeout)
            # 4xx 业务错误不重试（key 无效/参数错，重试无意义）
            if 400 <= r.status_code < 500:
                raise _ClientError(f"SCNet {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
            d = r.json()
            out = d.get("output", {})
            status = out.get("task_status")
            if status != "succeeded":
                raise RuntimeError(
                    f"SCNet task_status={status}: {out.get('error_code')} {out.get('error_message')}"
                )
            results = out.get("results") or []
            if not results:
                raise RuntimeError(f"SCNet 返回空 results: {d}")
            audio_url = results[0]
            # 流式形态返回 data URI；同步形态返回 http URL
            if audio_url.startswith("data:"):
                import base64
                return base64.b64decode(audio_url.split(",", 1)[1])
            return _download(audio_url, timeout=timeout)
        except _ClientError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    raise last or RuntimeError("SCNet Qwen3-TTS 失败")


class _ClientError(Exception):
    """4xx 业务错误：不重试。"""


async def _speak(
    text: str, voice: str, *, instructions: str | None,
    model: str, key: str, base_url: str, timeout: int,
) -> bytes:
    return await asyncio.to_thread(
        _speak_sync, text, voice,
        instructions=instructions, model=model, key=key,
        base_url=base_url, timeout=timeout,
    )


def _silence(p: Path, ms: int, sample_rate: int = 24000) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=mono:sample_rate={sample_rate}",
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


@register
class QwenTTSBackend(Backend):
    name = "qwen-tts"

    async def generate(self, segments, voice_map, cfg, out_path):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tts_cfg = cfg.get("tts", {}).get("qwen", {})
        pause_ms = int(cfg.get("tts", {}).get("pause_ms", 600))
        chunk_chars = int(tts_cfg.get("chunk_chars", 1500))
        timeout_sec = int(tts_cfg.get("timeout_sec", 120))
        base_url = tts_cfg.get("base_url", DEFAULT_BASE_URL)
        model = tts_cfg.get("model", DEFAULT_MODEL)
        base_instruction = str(tts_cfg.get("instructions", "") or "")
        use_emotion = bool(tts_cfg.get("use_emotion", True))

        key = _resolve_key(tts_cfg)
        if not key:
            raise RuntimeError(
                "SCNET_API_KEY 未设置（export 或填 config.yaml 的 tts.qwen.api_key）"
            )

        default_voice = voice_map.get("default", "Ethan")

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            files: list[Path] = []
            idx = 0
            for i, seg in enumerate(segments):
                voice = voice_map.get(seg["role"], default_voice)
                chunks = _chunk_text(seg["text"], chunk_chars)
                for chunk in chunks:
                    instructions = base_instruction or None
                    if use_emotion and seg.get("emotion"):
                        emo = str(seg["emotion"])
                        if emo in _EMO_INSTRUCTIONS and emo != "calm":
                            instructions = (
                                f"{_EMO_INSTRUCTIONS[emo]}，{'，' if not instructions else instructions + '，'}"
                                f"自然流畅，适合播客朗读"
                            )
                    audio = await _speak(
                        chunk, voice,
                        instructions=instructions,
                        model=model, key=key, base_url=base_url,
                        timeout=timeout_sec,
                    )
                    p = tmp / f"{idx:03d}.mp3"
                    # API 返回 wav 或 mp3——统一落盘，ffmpeg concat 阶段 aformat 归一化
                    p.write_bytes(audio)
                    files.append(p)
                    idx += 1
                if i < len(segments) - 1:
                    sil = tmp / f"s{i}.mp3"
                    _silence(sil, pause_ms)
                    files.append(sil)

            if not files:
                raise RuntimeError("无音频片段可拼接")

            # 归一化拼接：采样率/声道/格式统一，规避容器不一致导致的 concat 失败
            inputs: list[str] = []
            for f in files:
                inputs += ["-i", str(f)]
            n = len(files)
            afmt = "aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono"
            chain_fmt = "".join(f"[{j}:a]{afmt}[a{j}];" for j in range(n))
            concat_part = "".join(f"[a{j}]" for j in range(n))
            filter_desc = (
                f"{chain_fmt}{concat_part}concat=n={n}:v=0:a=1[cat];"
                f"[cat]aresample=24000[out]"
            )
            r = subprocess.run(
                ["ffmpeg", "-y", *inputs, "-filter_complex", filter_desc,
                 "-map", "[out]", "-c:a", "libmp3lame", "-ar", "24000",
                 "-ac", "1", "-b:a", "96k", str(out_path)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg concat 失败 (exit {r.returncode}): {r.stderr[-600:]}")
        return _dur(out_path)
