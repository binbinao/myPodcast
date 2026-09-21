#!/usr/bin/env python3
"""Qwen3-TTS 本地服务：OpenAI 兼容的 /v1/audio/speech。

为什么做成 HTTP 服务
--------------------
播客流水线跑在 Python 3.x 的仓库 venv 里，而这个模型需要独立环境（torch 2.14 + transformers 4.57）。
用 HTTP 解耦，仓库侧零重依赖，也避免每次合成重载模型（M1 Pro 上冷加载约 10-30s）。

端点
----
GET  /health                 存活 + 运行状态（device / rtf / 已合成时长）
GET  /v1/models              兼容 OpenAI 的模型列表
GET  /v1/audio/voices        9 个预置音色的元信息（含性别/母语/描述）
POST /v1/audio/speech        OpenAI 兼容合成：{model,input,voice,response_format,speed,instruct}
POST /v1/audio/segments      多角色批量：播客对谈一次成型，段间自动插入停顿
GET  /docs                   FastAPI 自带交互文档

启动
----
    ./run.sh              # 前台
    ./run.sh --daemon     # 后台（写日志 + pid）
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from synth import LANGUAGES, SPEAKERS, Qwen3TTSEngine

MODEL_ID = "qwen3-tts-12hz-1.7b-customvoice"

app = FastAPI(title="Qwen3-TTS Local", version="1.0.0")
_engine: Qwen3TTSEngine | None = None
_started_at = time.time()


def get_engine() -> Qwen3TTSEngine:
    global _engine
    if _engine is None:
        _engine = Qwen3TTSEngine()
    return _engine


# --------------------------- 请求模型 ---------------------------

class SpeechRequest(BaseModel):
    input: str = Field(..., description="要合成的文本")
    voice: str = Field("Serena", description="音色名，见 /v1/audio/voices")
    model: str = Field(MODEL_ID)
    language: str = Field("Chinese", description="Chinese/English/... 或 Auto")
    instruct: str | None = Field(None, description="自然语言语气指令，如「用特别愤怒的语气说」")
    response_format: str = Field("wav", description="wav | mp3")
    speed: float = Field(1.0, gt=0.1, le=3.0)
    max_new_tokens: int | None = None


class Segment(BaseModel):
    text: str
    speaker: str = "Serena"
    language: str = "Chinese"
    instruct: str | None = None


class SegmentsRequest(BaseModel):
    segments: list[Segment]
    response_format: str = "mp3"
    join_silence_ms: int = Field(400, ge=0, le=5000)
    speed: float = Field(1.0, gt=0.1, le=3.0)


# --------------------------- 音频编码 ---------------------------

def encode_audio(wav: np.ndarray, sr: int, fmt: str) -> tuple[bytes, str]:
    """numpy → wav/mp3 bytes。"""
    fmt = (fmt or "wav").lower()
    if fmt not in ("wav", "mp3"):
        raise HTTPException(400, f"不支持的 response_format: {fmt}（仅 wav/mp3）")

    if fmt == "wav":
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, wav, sr, format="WAV", subtype="PCM_16")
        return buf.getvalue(), "audio/wav"

    # mp3 走 ffmpeg（系统已装）；未装则回退 wav
    if not shutil.which("ffmpeg"):
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, wav, sr, format="WAV", subtype="PCM_16")
        return buf.getvalue(), "audio/wav"

    with tempfile.TemporaryDirectory() as td:
        wpath = os.path.join(td, "in.wav")
        mpath = os.path.join(td, "out.mp3")
        import soundfile as sf
        sf.write(wpath, wav, sr)
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", wpath, "-codec:a", "libmp3lame",
             "-b:a", "128k", "-ar", str(sr), "-ac", "1", mpath],
            capture_output=True,
        )
        if r.returncode != 0:
            raise HTTPException(500, f"ffmpeg 转码失败: {r.stderr[-300:].decode('utf-8', 'replace')}")
        with open(mpath, "rb") as f:
            return f.read(), "audio/mpeg"


# --------------------------- 端点 ---------------------------

@app.get("/health")
def health() -> dict[str, Any]:
    e = _engine
    return {
        "status": "ok",
        "uptime_s": round(time.time() - _started_at, 1),
        "engine": e.info() if e else {"loaded": False, "note": "首次请求时懒加载"},
    }


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{
            "id": MODEL_ID,
            "object": "model",
            "owned_by": "qwen-local",
            "permission": [],
        }],
    }


@app.get("/v1/audio/voices")
def voices() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {"id": k, "object": "voice", **v} for k, v in SPEAKERS.items()
        ],
        "languages": LANGUAGES,
    }


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest) -> Response:
    if not req.input.strip():
        raise HTTPException(400, "input 不能为空")
    if req.voice not in SPEAKERS:
        raise HTTPException(
            400, f"未知音色 {req.voice!r}。可用：{', '.join(SPEAKERS)}"
        )
    try:
        wav, sr = get_engine().synth(
            req.input, speaker=req.voice, language=req.language,
            instruct=req.instruct, max_new_tokens=req.max_new_tokens,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"合成失败: {type(e).__name__}: {e}") from e

    if abs(req.speed - 1.0) > 1e-6:
        from synth import _resample_speed
        wav = _resample_speed(wav, req.speed)

    data, mime = encode_audio(wav, sr, req.response_format)
    dur = len(wav) / sr
    return Response(
        content=data, media_type=mime,
        headers={
            "X-Audio-Duration": f"{dur:.2f}",
            "X-Sample-Rate": str(sr),
            "X-RTF": str(get_engine().stats.last_rtf or ""),
            "Content-Disposition": f'inline; filename="speech.{req.response_format}"',
        },
    )


@app.post("/v1/audio/segments")
def segments(req: SegmentsRequest) -> Response:
    if not req.segments:
        raise HTTPException(400, "segments 不能为空")
    for s in req.segments:
        if s.speaker not in SPEAKERS:
            raise HTTPException(400, f"未知音色 {s.speaker!r}。可用：{', '.join(SPEAKERS)}")
    items = [s.model_dump() for s in req.segments]
    try:
        wav, sr = get_engine().synth_batch(
            items, join_silence_ms=req.join_silence_ms, speed=req.speed,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"批量合成失败: {type(e).__name__}: {e}") from e

    data, mime = encode_audio(wav, sr, req.response_format)
    return Response(
        content=data, media_type=mime,
        headers={
            "X-Audio-Duration": f"{len(wav) / sr:.2f}",
            "X-Segment-Count": str(len(req.segments)),
            "X-Sample-Rate": str(sr),
        },
    )


@app.post("/admin/unload")
def unload() -> dict[str, str]:
    if _engine:
        _engine.unload()
    return {"status": "unloaded"}


@app.exception_handler(HTTPException)
def _http_err(_req, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"message": exc.detail, "type": "invalid_request_error"}},
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Qwen3-TTS 本地 OpenAI 兼容服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("QWEN_TTS_PORT", 8100)))
    ap.add_argument("--device", default=None, help="mps | cpu | cuda:0")
    ap.add_argument("--dtype", default=None, help="float16 | float32 | bfloat16")
    ap.add_argument("--attn", default=None, help="sdpa | eager | flash_attention_2 | none")
    ap.add_argument("--model-path", default=None)
    ap.add_argument("--no-warmup", action="store_true", help="跳过启动预热，加快启动")
    args = ap.parse_args()

    global _engine
    kwargs: dict[str, Any] = {"warmup": not args.no_warmup}
    if args.device:
        kwargs["device"] = args.device
    if args.dtype:
        kwargs["dtype"] = args.dtype
    if args.attn:
        kwargs["attn"] = args.attn
    if args.model_path:
        kwargs["model_path"] = args.model_path

    print(f"[qwen-tts] 加载模型 ... {kwargs}", flush=True)
    _engine = Qwen3TTSEngine(**kwargs)
    print(f"[qwen-tts] 就绪 {_engine.info()}", flush=True)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
