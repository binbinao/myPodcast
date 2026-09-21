#!/usr/bin/env python3
"""Qwen3-TTS 本地命令行。

三种用法
--------
1. 单句合成
   python cli.py say "大家好，欢迎收听。" --voice Serena -o out.wav

2. 多角色脚本合成（播客对谈）——从 txt/md 里读 `角色: 台词` 逐行
   python cli.py script dialogue.txt -o episode.mp3 \\
       --voice-map "小搭=Serena,斌哥=Uncle_Fu" --pause-ms 500

3. 试听全部音色，每个音色一段，拼成一个文件
   python cli.py audition -o voices-demo.mp3

4. 列出音色
   python cli.py voices
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

from synth import SPEAKERS, Qwen3TTSEngine


def _write(wav: np.ndarray, sr: int, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".mp3":
        import shutil
        import subprocess
        import tempfile
        if not shutil.which("ffmpeg"):
            sys.exit("导出 mp3 需要 ffmpeg，未找到。可改 -o 为 .wav")
        with tempfile.TemporaryDirectory() as td:
            w = Path(td) / "a.wav"
            import soundfile as sf
            sf.write(w, wav, sr)
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(w), "-codec:a", "libmp3lame",
                 "-b:a", "128k", "-ar", str(sr), "-ac", "1", str(out)],
                capture_output=True,
            )
            if r.returncode != 0:
                sys.exit(f"ffmpeg 失败: {r.stderr[-300:]}")
    else:
        import soundfile as sf
        sf.write(out, wav, sr, subtype="PCM_16")
    dur = len(wav) / sr
    print(f"✓ {out}  ({dur:.1f}s @ {sr}Hz, {out.stat().st_size / 1024:.0f}KB)")


def _parse_script(path: Path) -> list[dict]:
    """解析 `角色: 台词` 或 `【角色】台词` 格式的脚本。"""
    segs: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([^:：【】]{1,12})\s*[:：]\s*(.+)$", line)
        if not m:
            m = re.match(r"^【([^】]{1,12})】\s*(.+)$", line)
        if m:
            segs.append({"role": m.group(1).strip(), "text": m.group(2).strip()})
        elif segs:
            segs[-1]["text"] += line
        else:
            segs.append({"role": "default", "text": line})
    return segs


def _parse_voice_map(spec: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not spec:
        return out
    for pair in spec.split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def cmd_voices(_a) -> int:
    print(f"{'音色':<10} {'性别':<7} {'母语':<26} 描述")
    print("-" * 100)
    for k, v in SPEAKERS.items():
        print(f"{k:<10} {v['gender']:<7} {v['native_language']:<26} {v['desc']}")
    return 0


def cmd_say(a) -> int:
    e = Qwen3TTSEngine(device=a.device, dtype=a.dtype, attn=a.attn, warmup=False)
    t0 = time.perf_counter()
    wav, sr = e.synth(a.text, speaker=a.voice, language=a.language,
                      instruct=a.instruct, max_new_tokens=a.max_new_tokens)
    print(f"加载 {e.stats.load_s}s | 生成 {time.perf_counter() - t0:.1f}s | RTF {e.stats.last_rtf}")
    _write(wav, sr, Path(a.out))
    return 0


def cmd_script(a) -> int:
    segs = _parse_script(Path(a.script))
    if not segs:
        sys.exit(f"脚本 {a.script} 未解析出任何台词（格式：角色: 台词）")
    vmap = _parse_voice_map(a.voice_map)
    default_voice = a.voice
    items = []
    for s in segs:
        spk = vmap.get(s["role"]) or vmap.get("default") or default_voice
        if spk not in SPEAKERS:
            sys.exit(f"角色 {s['role']!r} 映射到未知音色 {spk!r}。可用：{', '.join(SPEAKERS)}")
        items.append({"text": s["text"], "speaker": spk, "language": a.language})
    print(f"共 {len(items)} 段；角色映射：")
    for role in sorted({s["role"] for s in segs}):
        print(f"  {role} -> {vmap.get(role) or default_voice}")
    e = Qwen3TTSEngine(device=a.device, dtype=a.dtype, attn=a.attn, warmup=False)
    t0 = time.perf_counter()
    wav, sr = e.synth_batch(items, join_silence_ms=a.pause_ms, speed=a.speed)
    print(f"加载 {e.stats.load_s}s | 总生成 {time.perf_counter() - t0:.1f}s | "
          f"音频 {len(wav) / sr:.1f}s | 整体 RTF "
          f"{(time.perf_counter() - t0) / (len(wav) / sr):.2f}")
    _write(wav, sr, Path(a.out))
    return 0


def cmd_audition(a) -> int:
    lines = {
        "Vivian": "我是 Vivian，明亮微飒的年轻女声，适合活泼一点的段落。",
        "Serena": "我是 Serena，温暖柔和的年轻女声，适合讲述和陪伴感的内容。",
        "Uncle_Fu": "我是 Uncle_Fu，醇厚低沉的成熟男声，适合沉稳的叙述。",
        "Dylan": "我是 Dylan，北京口音的青年男声，语气清亮自然。",
        "Eric": "我是 Eric，成都口音的活泼男声，带一点沙哑的亮度。",
        "Ryan": "Hi, I'm Ryan, a dynamic male voice with strong rhythmic drive.",
        "Aiden": "Hi, I'm Aiden, a sunny American male voice with a clear midrange.",
        "Ono_Anna": "こんにちは、Ono Anna です。軽やかで遊び心のある声です。",
        "Sohee": "안녕하세요, Sohee입니다. 따뜻하고 감정이 풍부한 목소리입니다.",
    }
    e = Qwen3TTSEngine(device=a.device, dtype=a.dtype, attn=a.attn, warmup=False)
    chunks: list[np.ndarray] = []
    sr_out = 24000
    for i, (spk, text) in enumerate(lines.items(), 1):
        lang = SPEAKERS[spk]["native_language"].split(" ")[0]
        t0 = time.perf_counter()
        wav, sr = e.synth(text, speaker=spk, language=lang)
        sr_out = sr
        chunks.append(wav)
        chunks.append(np.zeros(int(sr * 0.5), dtype=np.float32))
        print(f"  [{i}/9] {spk:<9} {time.perf_counter() - t0:5.1f}s  {len(wav) / sr:4.1f}s")
    _write(np.concatenate(chunks), sr_out, Path(a.out))
    print(json.dumps(e.info()["stats"], ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Qwen3-TTS 本地合成")
    ap.add_argument("--device", default=None, help="mps | cpu")
    ap.add_argument("--dtype", default=None, help="float16 | float32")
    ap.add_argument("--attn", default=None, help="sdpa | eager | none")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("voices", help="列出 9 个预置音色")
    p.set_defaults(func=cmd_voices)

    p = sub.add_parser("say", help="单句合成")
    p.add_argument("text")
    p.add_argument("-o", "--out", default="out.wav")
    p.add_argument("--voice", default="Serena")
    p.add_argument("--language", default="Chinese")
    p.add_argument("--instruct", default=None)
    p.add_argument("--max-new-tokens", type=int, default=None)
    p.set_defaults(func=cmd_say)

    p = sub.add_parser("script", help="多角色脚本合成")
    p.add_argument("script")
    p.add_argument("-o", "--out", default="episode.mp3")
    p.add_argument("--voice-map", default=None, help="角色=音色,角色=音色")
    p.add_argument("--voice", default="Serena", help="未映射角色的兜底音色")
    p.add_argument("--language", default="Chinese")
    p.add_argument("--pause-ms", type=int, default=500)
    p.add_argument("--speed", type=float, default=1.0)
    p.set_defaults(func=cmd_script)

    p = sub.add_parser("audition", help="9 个音色各合成一段，试听对比")
    p.add_argument("-o", "--out", default="voices-demo.mp3")
    p.set_defaults(func=cmd_audition)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
