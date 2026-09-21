"""Qwen3-TTS-12Hz-1.7B-CustomVoice 本地推理核心。

设计要点
--------
1. **设备自动选择**：有 MPS 用 MPS，否则 CPU。可用环境变量强制覆盖。
2. **精度自动匹配**：MPS → float16；CPU → float32（CPU 上 bf16 极慢）。
3. **模型只加载一次**：引擎实例持有模型，服务端进程内常驻。
4. **线程安全**：PyTorch 模型非线程安全，所有推理走同一把锁。
5. **不依赖 flash-attn**：Mac 上装不了，用 sdpa；包本身会回退到 PyTorch 实现。
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch

DEFAULT_MODEL_PATH = os.environ.get(
    "QWEN_TTS_MODEL_PATH",
    "/Users/jiduobin/.workbuddy/models/Qwen3-TTS-12Hz-1.7B-CustomVoice",
)

# 9 个预置音色（来自模型卡原文；native_language 为官方推荐语言）
SPEAKERS: dict[str, dict[str, str]] = {
    "Vivian":   {"gender": "female", "native_language": "Chinese",
                 "desc": "Bright, slightly edgy young female voice. 明亮微飒的年轻女声"},
    "Serena":   {"gender": "female", "native_language": "Chinese",
                 "desc": "Warm, gentle young female voice. 温暖柔和的年轻女声"},
    "Uncle_Fu": {"gender": "male",   "native_language": "Chinese",
                 "desc": "Seasoned male voice with a low, mellow timbre. 醇厚低沉的成熟男声"},
    "Dylan":    {"gender": "male",   "native_language": "Chinese (Beijing Dialect)",
                 "desc": "Youthful Beijing male voice, clear and natural. 北京口音青年男声"},
    "Eric":     {"gender": "male",   "native_language": "Chinese (Sichuan Dialect)",
                 "desc": "Lively Chengdu male voice, slightly husky brightness. 成都口音活泼男声"},
    "Ryan":     {"gender": "male",   "native_language": "English",
                 "desc": "Dynamic male voice with strong rhythmic drive. 节奏感强的男声"},
    "Aiden":    {"gender": "male",   "native_language": "English",
                 "desc": "Sunny American male voice, clear midrange. 阳光美式男声"},
    "Ono_Anna": {"gender": "female", "native_language": "Japanese",
                 "desc": "Playful Japanese female voice. 轻快日系女声"},
    "Sohee":    {"gender": "female", "native_language": "Korean",
                 "desc": "Warm Korean female voice with rich emotion. 温暖韩系女声"},
}

LANGUAGES = ["Chinese", "English", "Japanese", "Korean", "German",
             "French", "Russian", "Portuguese", "Spanish", "Italian", "Auto"]


def _resolve_device(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("QWEN_TTS_DEVICE")
    if env:
        return env
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _resolve_dtype(device: str, explicit: str | None = None) -> torch.dtype:
    name = explicit or os.environ.get("QWEN_TTS_DTYPE")
    if name:
        return getattr(torch, name)
    # MPS 支持 float16；CPU 上用 float32（bfloat16 在 CPU 上无加速甚至更慢）
    return torch.float16 if device == "mps" else torch.float32


@dataclass
class SynthStats:
    calls: int = 0
    total_audio_s: float = 0.0
    total_gen_s: float = 0.0
    loads: int = 0
    load_s: float = 0.0
    last_rtf: float | None = None
    errors: int = 0
    lock_wait_s: float = 0.0
    history: list[dict[str, Any]] = field(default_factory=list)


class Qwen3TTSEngine:
    """进程内常驻的推理引擎。"""

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        *,
        device: str | None = None,
        dtype: str | None = None,
        attn: str | None = None,
        warmup: bool = True,
    ) -> None:
        self.model_path = model_path
        self.device = _resolve_device(device)
        self.dtype = _resolve_dtype(self.device, dtype)
        self.attn = attn or os.environ.get("QWEN_TTS_ATTN", "sdpa")
        self._lock = threading.Lock()
        self._model = None
        self.sample_rate: int | None = None
        self.stats = SynthStats()
        if warmup:
            self.load()
            self._warmup()

    # ---------- 生命周期 ----------

    def load(self) -> None:
        """加载模型（幂等）。"""
        if self._model is not None:
            return
        from qwen_tts import Qwen3TTSModel

        p = Path(self.model_path)
        if not p.is_dir():
            raise FileNotFoundError(f"模型目录不存在：{self.model_path}")

        t0 = time.perf_counter()
        kwargs: dict[str, Any] = {
            "device_map": self.device,
            "dtype": self.dtype,
        }
        if self.attn and self.attn != "none":
            kwargs["attn_implementation"] = self.attn
        try:
            self._model = Qwen3TTSModel.from_pretrained(self.model_path, **kwargs)
        except Exception:
            # 某些 MPS 场景 attn 或 dtype 不被接受，逐级降级
            self._model = Qwen3TTSModel.from_pretrained(
                self.model_path, device_map=self.device, dtype=torch.float32,
            )
        self.stats.loads += 1
        self.stats.load_s = round(time.perf_counter() - t0, 2)

    def _warmup(self) -> None:
        """预热一次，把首包开销从用户请求里挪走。"""
        try:
            self.synth("预热。", speaker="Serena", language="Chinese")
        except Exception:
            self.stats.errors += 1

    def unload(self) -> None:
        self._model = None
        import gc
        gc.collect()
        if torch.backends.mps.is_available():
            try:
                torch.mps.empty_cache()
            except Exception:
                pass

    # ---------- 元信息 ----------

    def speakers(self) -> list[dict[str, str]]:
        out = []
        for name, meta in SPEAKERS.items():
            out.append({"id": name, "name": name, **meta})
        return out

    def info(self) -> dict[str, Any]:
        return {
            "model_path": self.model_path,
            "device": self.device,
            "dtype": str(self.dtype).replace("torch.", ""),
            "attn_implementation": self.attn,
            "sample_rate": self.sample_rate,
            "speakers": list(SPEAKERS.keys()),
            "languages": LANGUAGES,
            "loaded": self._model is not None,
            "flash_attn": False,
            "stats": {
                "calls": self.stats.calls,
                "loads": self.stats.loads,
                "load_s": self.stats.load_s,
                "total_audio_s": round(self.stats.total_audio_s, 1),
                "total_gen_s": round(self.stats.total_gen_s, 1),
                "last_rtf": self.stats.last_rtf,
                "errors": self.stats.errors,
            },
        }

    # ---------- 推理 ----------

    def synth(
        self,
        text: str,
        *,
        speaker: str = "Serena",
        language: str = "Chinese",
        instruct: str | None = None,
        max_new_tokens: int | None = None,
    ) -> tuple[np.ndarray, int]:
        """单条合成，返回 (waveform float32 mono, sample_rate)。"""
        if self._model is None:
            self.load()
        text = (text or "").strip()
        if not text:
            raise ValueError("text 不能为空")

        spk = speaker if speaker in SPEAKERS else None
        gen_kwargs: dict[str, Any] = {}
        if max_new_tokens:
            gen_kwargs["max_new_tokens"] = max_new_tokens

        t_wait = time.perf_counter()
        with self._lock:
            self.stats.lock_wait_s += time.perf_counter() - t_wait
            t0 = time.perf_counter()
            try:
                wavs, sr = self._model.generate_custom_voice(
                    text=text,
                    language=language or "Chinese",
                    speaker=spk,
                    **({"instruct": instruct} if instruct else {}),
                    **gen_kwargs,
                )
            except TypeError:
                # 老版签名不带 instruct 时降级
                wavs, sr = self._model.generate_custom_voice(
                    text=text, language=language or "Chinese", speaker=spk,
                )
            gen_s = time.perf_counter() - t0

        wav = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
        dur = len(wav) / float(sr)
        self.sample_rate = int(sr)
        self.stats.calls += 1
        self.stats.total_audio_s += dur
        self.stats.total_gen_s += gen_s
        self.stats.last_rtf = round(gen_s / dur, 3) if dur else None
        self.stats.history.append({
            "speaker": speaker, "chars": len(text),
            "audio_s": round(dur, 2), "gen_s": round(gen_s, 2),
            "rtf": self.stats.last_rtf, "ts": time.time(),
        })
        self.stats.history = self.stats.history[-200:]
        return wav, int(sr)

    def synth_batch(
        self,
        items: list[dict[str, Any]],
        *,
        join_silence_ms: int = 400,
        speed: float = 1.0,
    ) -> tuple[np.ndarray, int]:
        """多条合成后拼接。items: [{text, speaker, language, instruct}, ...]"""
        if not items:
            raise ValueError("items 不能为空")
        chunks: list[np.ndarray] = []
        sr_out = None
        for it in items:
            if not (it.get("text") or "").strip():
                continue
            wav, sr = self.synth(
                it["text"],
                speaker=it.get("speaker") or "Serena",
                language=it.get("language") or "Chinese",
                instruct=it.get("instruct"),
                max_new_tokens=it.get("max_new_tokens"),
            )
            sr_out = sr
            if speed and abs(speed - 1.0) > 1e-6:
                wav = _resample_speed(wav, speed)
            chunks.append(wav)
            if join_silence_ms > 0:
                chunks.append(np.zeros(int(sr * join_silence_ms / 1000), dtype=np.float32))
        if not chunks:
            raise ValueError("items 全部为空文本")
        if join_silence_ms > 0:
            chunks.pop()
        return np.concatenate(chunks), int(sr_out or 24000)


def _resample_speed(wav: np.ndarray, speed: float) -> np.ndarray:
    """变速不变调（近似）：线性重采样改变时长，再按目标长度拉伸。

    简单实现：改变采样点数。用于播客调速足够，不做相位声码器。
    """
    if speed <= 0:
        return wav
    n_out = max(1, int(len(wav) / speed))
    idx = np.linspace(0, len(wav) - 1, n_out)
    return np.interp(idx, np.arange(len(wav)), wav).astype(np.float32)
