"""Fish Audio (OpenAudio S2) backend：HTTP POST /v1/tts，按段调用。

- 端点：POST {base_url}/v1/tts
- 鉴权：Authorization: Bearer <FISH_AUDIO_API_KEY>
- model 通过 header 传（默认 s2.1-pro；可用 s2.1-pro-free 试跑）
- 响应：原始音频 bytes（mp3/wav/pcm/opus）
- 重试 + 指数退避（与 minimax backend 同构）

v1 限制（最小可用版本）：
- 每个 segment 走一次独立请求，单 voice（per-role reference_id）
- emotion 字段暂不转换（Fish 用 `(parenthesis)` 内联文本标签，跟 minimax 的 emotion 字段不对齐）
- 不支持 zero-shot references（要求先在 Fish Audio 控制台建好 voice model 拿到 reference_id）
- 不使用 chunk_length 多段切分；一次性 POST 整段文本（Fish 推荐 chunk_length ≤ 300，但整段传更简单；如超长再按句切）
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from .base import Backend, register


# 国内 ISP 偶发把 api.fish.audio 的 AAAA 记录污染成 Facebook IPv6 段
# （2a03:2880:f1xx:xx:face:b00c:0:25de），让 Python 默认走 IPv6 撞墙到
# Facebook 的 400 错误页。Patch urllib3.util.connection.create_connection
# 强制 IPv4：只影响 urllib3 连接层，不影响 socket.getaddrinfo 全局行为。
# CI 在海外无此问题；只是进程级 patch，无持久副作用。
import urllib3.util.connection as _urllib3_conn
_orig_create_connection = _urllib3_conn.create_connection
def _ipv4_create_connection(address, timeout=None, **kw):
    host, port = address
    err: OSError | None = None
    for res in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        af, socktype, proto, canonname, sa = res
        sock = socket.socket(af, socktype, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(sa)
            return sock
        except OSError as e:
            err = e
            sock.close()
    if err:
        raise err
    raise OSError(f"could not connect to {host}:{port} via IPv4")
_urllib3_conn.create_connection = _ipv4_create_connection


DEFAULT_BASE_URL = "https://api.fish.audio/v1/tts"
VALID_MODELS = {"s2.1-pro", "s2.1-pro-free", "s2-pro", "s1"}


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """超长段按句切；按句末标点优先，避免词中切。

    与 minimax._chunk_text 同构（按中文句末标点。！？；切）。
    """
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
            cur = s
    if cur:
        chunks.append(cur)
    return chunks


def _resolve_key(cfg: dict[str, Any]) -> str:
    """API key 优先级：cfg.api_key > env FISH_AUDIO_API_KEY。"""
    return cfg.get("api_key", "") or os.environ.get("FISH_AUDIO_API_KEY", "")


def _build_proxy_url(socks5_url: str | None) -> str | None:
    """构造 httpx 的 proxy URL（httpx 的 proxy 是单数字符串）。

    socks5_url: 形如 "socks5://127.0.0.1:1086"，空字符串/None 表示直连。
    """
    return socks5_url or None


class _ClientError(RuntimeError):
    """4xx 客户端错误标记：不重试，立即抛。继承 RuntimeError 兼容现有 assertRaises。"""


def _speak_sync(
    text: str, reference_id: str, *,
    model: str, base_url: str, key: str,
    format_: str, sample_rate: int, mp3_bitrate: int,
    temperature: float, top_p: float,
    timeout: int,
    proxy_url: str | None = None,
    verify_ssl: bool = True,
) -> bytes:
    """同步阻塞调 Fish Audio /v1/tts。Cloudflare 按 HTTP version 路由，必须 HTTP/2。"""
    body: dict[str, Any] = {
        "text": text,
        "format": format_,
        "sample_rate": sample_rate,
        "temperature": temperature,
        "top_p": top_p,
        "chunk_length": 300,   # Fish 推荐范围 100-300，默认 300
        "normalize": True,
    }
    if mp3_bitrate and format_ == "mp3":
        body["mp3_bitrate"] = mp3_bitrate
    # 多说话人需要 reference_id 是数组；单说话人传字符串更简洁
    if reference_id:
        body["reference_id"] = reference_id

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "model": model,
    }

    # Cloudflare edge 路由依赖 HTTP version：HTTP/1.1 被错误路由到非 Fish 后端返 400
    # 必须强制 HTTP/2。httpx 默认不开启，需 http2=True。
    last: Exception | None = None
    for attempt in range(3):
        try:
            with httpx.Client(
                proxy=proxy_url,
                verify=verify_ssl,
                timeout=timeout,
                http2=True,           # ← 必须，否则走 HTTP/1.1 撞 Cloudflare 路由
                follow_redirects=True,
            ) as client:
                r = client.post(base_url, headers=headers, json=body)
            if r.status_code >= 500:
                raise RuntimeError(f"Fish Audio server error {r.status_code}: {r.text[:200]}")
            if r.status_code >= 400:
                # 4xx client error 重试无用，立即抛出不重试
                raise _ClientError(
                    f"Fish Audio {r.status_code}: {r.text[:300]} "
                    f"(content-type: {r.headers.get('content-type')})"
                )
            if not r.content:
                raise RuntimeError("Fish Audio 返回空 body")
            return r.content
        except _ClientError:
            # 4xx：立刻终止，不重试
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise last or RuntimeError("Fish Audio TTS 失败")


async def _speak(
    text: str, reference_id: str, *,
    model: str, base_url: str, key: str,
    format_: str, sample_rate: int, mp3_bitrate: int,
    temperature: float, top_p: float,
    timeout: int,
    proxy_url: str | None = None,
    verify_ssl: bool = True,
) -> bytes:
    return await asyncio.to_thread(
        _speak_sync, text, reference_id,
        model=model, base_url=base_url, key=key,
        format_=format_, sample_rate=sample_rate, mp3_bitrate=mp3_bitrate,
        temperature=temperature, top_p=top_p, timeout=timeout,
        proxy_url=proxy_url, verify_ssl=verify_ssl,
    )


@register
class FishSpeechBackend(Backend):
    name = "fish-speech"

    async def generate(self, segments, voice_map, cfg, out_path):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tts_cfg = cfg.get("tts", {}).get("fishspeech", {})
        pause_ms = int(cfg.get("tts", {}).get("pause_ms", 600))
        chunk_chars = int(tts_cfg.get("chunk_chars", 1000))
        timeout_sec = int(tts_cfg.get("timeout_sec", 60))

        key = _resolve_key(tts_cfg)
        if not key:
            raise RuntimeError(
                "FISH_AUDIO_API_KEY 未设置（export FISH_AUDIO_API_KEY=... "
                "或填 config.yaml 的 tts.fishspeech.api_key）"
            )
        base_url = tts_cfg.get("base_url", DEFAULT_BASE_URL).rstrip("/")
        model = tts_cfg.get("model", "s2.1-pro-free")
        if model not in VALID_MODELS:
            raise RuntimeError(
                f"不支持的 model: {model}。可选：{', '.join(sorted(VALID_MODELS))}"
            )
        format_ = tts_cfg.get("format", "mp3")
        sample_rate = int(tts_cfg.get("sample_rate", 44100 if format_ != "opus" else 48000))
        mp3_bitrate = int(tts_cfg.get("mp3_bitrate", 128))
        temperature = float(tts_cfg.get("temperature", 0.7))
        top_p = float(tts_cfg.get("top_p", 0.7))
        # 代理：socks5://host:port；空字符串/None 直连
        proxy_url = _build_proxy_url(tts_cfg.get("socks5_proxy"))
        # SSL 验证：CI/直连默认 True；走 MITM 代理（如公司 VPN）时设 False
        verify_ssl = bool(tts_cfg.get("verify_ssl", True))
        default_voice = voice_map.get("default", "")

        def _silence(p: Path, ms: int) -> None:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
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
                # voice_map role -> Fish Audio reference_id（空字符串=用 Fish 默认音色）
                reference_id = voice_map.get(seg["role"]) or default_voice
                chunks = _chunk_text(seg["text"], chunk_chars)
                for chunk in chunks:
                    audio_bytes = await _speak(
                        chunk, reference_id or "",  # 空字符串：让 Fish 用默认音色
                        model=model, base_url=base_url, key=key,
                        format_=format_, sample_rate=sample_rate, mp3_bitrate=mp3_bitrate,
                        temperature=temperature, top_p=top_p, timeout=timeout_sec,
                        proxy_url=proxy_url, verify_ssl=verify_ssl,
                    )
                    p = tmp / f"{idx:03d}.{format_}"
                    p.write_bytes(audio_bytes)
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
            afmt = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono"
            chain_fmt = "".join(f"[{j}:a]{afmt}[a{j}];" for j in range(n))
            concat_part = "".join(f"[a{j}]" for j in range(n))
            filter_desc = (
                f"{chain_fmt}{concat_part}concat=n={n}:v=0:a=1[cat];"
                f"[cat]aresample=44100[out]"
            )
            r = subprocess.run(
                ["ffmpeg", "-y", *inputs, "-filter_complex", filter_desc,
                 "-map", "[out]", "-c:a", "libmp3lame", "-ar", "44100",
                 "-ac", "1", "-b:a", "128k", str(out_path)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg concat 失败 (exit {r.returncode}): {r.stderr[-600:]}")
        return _dur(out_path)