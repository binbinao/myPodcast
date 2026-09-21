"""Qwen3-TTS 本地后端：走 qwen3-tts-local 服务（OpenAI 兼容 /v1/audio/speech）。

与 qwen_tts.py（SCNet 云 API）的区别
------------------------------------
| | qwen-tts（云） | qwen3-local（本机） |
|---|---|---|
| 端点 | api.scnet.cn | 127.0.0.1:8100 |
| 模型 | Qwen3-TTS-Instruct-Flash | Qwen3-TTS-12Hz-1.7B-CustomVoice |
| 计费 | 按字符 | 零边际成本 |
| 音色 | Ethan/Cherry/Serena... | Vivian/Serena/Uncle_Fu/Dylan/Eric/Ryan/Aiden/Ono_Anna/Sohee |
| 断网 | 不可用 | 可用 |

服务需先起（本仓库根目录）：
    ./scripts/start-qwen-tts-local.sh

设计取舍
--------
- **逐块请求 + 本地 ffmpeg 拼接**（而非服务的批量端点）：单块请求能按块打进度日志。
  M1 Pro 上 RTF 约 2-4，一集 15 分钟音频要跑 30-60 分钟，没有进度条是无法忍受的。
- **chunk_chars 默认 200**（约 45 秒音频/块）：块小 → 进度细 → 单块失败重试代价小。
- **健康检查前置**：服务没起时立刻报错并给出一行启动命令，而不是重试到超时。
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

from .base import Backend, register
from ..log import logger as log

DEFAULT_BASE_URL = "http://127.0.0.1:8100"

# 9 个预置音色（Qwen3-TTS-12Hz-1.7B-CustomVoice 官方音色表）
SPEAKERS = {
    "Vivian": "明亮微飒·年轻女声",
    "Serena": "温暖柔和·年轻女声",
    "Uncle_Fu": "醇厚低沉·成熟男声",
    "Dylan": "北京口音·青年男声",
    "Eric": "成都口音·活泼男声",
    "Ryan": "节奏感强·男声（英文母语）",
    "Aiden": "阳光美式·男声（英文母语）",
    "Ono_Anna": "轻快日系·女声",
    "Sohee": "温暖韩系·女声",
}

# prosody emotion 标签 → 自然语言指令（instruct）
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


def chunk_text(text: str, max_chars: int) -> list[str]:
    """按句末标点切块，避免词中切断。"""
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


def build_instruct(seg: dict[str, Any], base: str, use_emotion: bool) -> str | None:
    """段 emotion → instruct 自然语言指令。"""
    instructions = base or ""
    if use_emotion and seg.get("emotion"):
        emo = str(seg["emotion"])
        if emo in _EMO_INSTRUCTIONS and emo != "calm":
            prefix = _EMO_INSTRUCTIONS[emo]
            instructions = f"{prefix}，{instructions}" if instructions else f"{prefix}，自然流畅，适合播客朗读"
    return instructions or None


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


def _health(base_url: str, timeout: int = 5) -> dict[str, Any]:
    try:
        r = requests.get(f"{base_url}/health", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"本地 Qwen3-TTS 服务未就绪（{base_url}）：{type(e).__name__}: {e}\n"
            f"  启动：cd <myPodcast> && ./scripts/start-qwen-tts-local.sh"
        ) from e


def _speak_sync(
    text: str, voice: str, *, instruct: str | None,
    base_url: str, language: str, response_format: str,
    speed: float, timeout: int, max_retries: int = 3,
) -> bytes:
    body: dict[str, Any] = {
        "input": text,
        "voice": voice,
        "language": language,
        "response_format": response_format,
        "speed": speed,
    }
    if instruct:
        body["instruct"] = instruct

    last: Exception | None = None
    for attempt in range(max_retries):
        try:
            r = requests.post(f"{base_url}/v1/audio/speech", json=body, timeout=timeout)
            if 400 <= r.status_code < 500:
                # 参数/音色错误：重试无意义
                raise _ClientError(f"本地服务 {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("本地服务返回空音频")
            return r.content
        except _ClientError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < max_retries - 1:
                import time as _t
                _t.sleep(2 ** attempt)
    raise last or RuntimeError("本地 Qwen3-TTS 合成失败")


class _ClientError(Exception):
    """4xx：不重试。"""


async def _speak(text: str, voice: str, **kw: Any) -> bytes:
    return await asyncio.to_thread(_speak_sync, text, voice, **kw)


@register
class Qwen3LocalBackend(Backend):
    name = "qwen3-local"

    async def generate(self, segments, voice_map, cfg, out_path):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        tts_cfg = cfg.get("tts", {}).get("qwen3_local", {})
        base_url = str(tts_cfg.get("base_url", DEFAULT_BASE_URL)).rstrip("/")
        language = tts_cfg.get("language", "Chinese")
        chunk_chars = int(tts_cfg.get("chunk_chars", 200))
        timeout_sec = int(tts_cfg.get("timeout_sec", 900))
        speed = float(tts_cfg.get("speed", 1.0))
        use_emotion = bool(tts_cfg.get("use_emotion", True))
        base_instruct = str(tts_cfg.get("instructions", "") or "")
        pause_ms = int(cfg.get("tts", {}).get("pause_ms", 600))
        fmt = str(tts_cfg.get("format", "mp3")).lower()

        info = _health(base_url)
        eng = info.get("engine", {})
        log.info(f"      本地服务就绪 device={eng.get('device')} dtype={eng.get('dtype')} "
                 f"attn={eng.get('attn_implementation')}")

        default_voice = voice_map.get("default", "Serena")

        # 展开：段 → 块
        jobs: list[tuple[str, str, str | None]] = []
        for i, seg in enumerate(segments):
            voice = voice_map.get(seg["role"], default_voice)
            if voice not in SPEAKERS:
                raise RuntimeError(
                    f"未知音色 {voice!r}（角色 {seg['role']!r}）。可用：{', '.join(SPEAKERS)}"
                )
            instr = build_instruct(seg, base_instruct, use_emotion)
            for c in chunk_text(seg["text"], chunk_chars):
                jobs.append((c, voice, instr))

        total_chars = sum(len(j[0]) for j in jobs)
        log.info(f"      {len(segments)} 段 → {len(jobs)} 块 / {total_chars} 字；"
                 f"预计音频 {total_chars / 4.5 / 60:.1f} 分钟")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            files: list[Path] = []
            t_start = time.perf_counter()
            done_chars = 0
            for idx, (text, voice, instr) in enumerate(jobs):
                audio = await _speak(
                    text, voice, instruct=instr, base_url=base_url,
                    language=language, response_format=fmt,
                    speed=speed, timeout=timeout_sec,
                )
                p = tmp_p / f"{idx:04d}.{fmt}"
                p.write_bytes(audio)
                files.append(p)
                done_chars += len(text)
                el = time.perf_counter() - t_start
                rate = done_chars / el if el else 0
                eta = (total_chars - done_chars) / rate if rate else 0
                log.info(f"      [{idx + 1}/{len(jobs)}] {voice:<9} "
                         f"{done_chars}/{total_chars} 字  已用 {el / 60:.1f}min  "
                         f"预计剩 {eta / 60:.1f}min")

            # 段间停顿：以「段边界」为准，而不是块边界
            # 逐段合成后按段拼接，段间插入 pause_ms
            # （上面按块平铺了，这里回填：定位每段的最后一块后插入静音）
            if pause_ms > 0:
                silence = tmp_p / "sil.mp3"
                _silence(silence, pause_ms)
                # 计算每段结束块索引
                seg_end: set[int] = set()
                acc = 0
                for i, seg in enumerate(segments):
                    acc += len(chunk_text(seg["text"], chunk_chars))
                    seg_end.add(acc - 1)
                merged: list[Path] = []
                for i, f in enumerate(files):
                    merged.append(f)
                    if i in seg_end and i != len(files) - 1:
                        merged.append(silence)
                files = merged

            if not files:
                raise RuntimeError("无音频片段可拼接")

            inputs: list[str] = []
            for f in files:
                inputs += ["-i", str(f)]
            n = len(files)
            afmt = "aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono"
            chain = "".join(f"[{j}:a]{afmt}[a{j}];" for j in range(n))
            concat_part = "".join(f"[a{j}]" for j in range(n))
            filter_desc = f"{chain}{concat_part}concat=n={n}:v=0:a=1[cat];[cat]aresample=24000[out]"

            if not shutil.which("ffmpeg"):
                raise RuntimeError("拼接需要 ffmpeg，未找到")
            r = subprocess.run(
                ["ffmpeg", "-y", *inputs, "-filter_complex", filter_desc,
                 "-map", "[out]", "-c:a", "libmp3lame", "-ar", "24000",
                 "-ac", "1", "-b:a", "96k", str(out_path)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg concat 失败 (exit {r.returncode}): {r.stderr[-600:]}")

            log.info(f"      合成总耗时 {(time.perf_counter() - t_start) / 60:.1f}min")
        return _dur(out_path)
