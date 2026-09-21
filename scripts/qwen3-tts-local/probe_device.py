#!/usr/bin/env python3
"""Qwen3-TTS 本机适配性探测：实测哪组 device/dtype/attn 在 Apple Silicon 上能跑、跑多快。

只用一条短文本，纯计时，不做主观评价。
"""
from __future__ import annotations

import os
import sys
import time
import traceback

import torch

MODEL_DIR = os.environ.get(
    "QWEN_TTS_MODEL_PATH",
    "/Users/jiduobin/.workbuddy/models/Qwen3-TTS-12Hz-1.7B-CustomVoice",
)

TEXT = "大家好，这里是本地语音合成测试，用于确认设备与精度组合是否可用。"

# 候选组合：(device_map, dtype, attn_implementation)
CANDIDATES = [
    ("mps", torch.float16, "sdpa"),
    ("mps", torch.float32, "sdpa"),
    ("cpu", torch.float32, "sdpa"),
    ("mps", torch.bfloat16, "sdpa"),
]


def _mem_mb() -> float:
    """进程 RSS（MB）。"""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1048576
    except Exception:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576


def probe(device_map, dtype, attn) -> dict:
    from qwen_tts import Qwen3TTSModel

    tag = f"{device_map}/{str(dtype).replace('torch.', '')}/{attn}"
    res = {"tag": tag, "ok": False, "load_s": None, "gen_s": None,
           "audio_s": None, "sr": None, "rtf": None, "err": None}
    t0 = time.perf_counter()
    try:
        model = Qwen3TTSModel.from_pretrained(
            MODEL_DIR,
            device_map=device_map,
            dtype=dtype,
            attn_implementation=attn,
        )
        res["load_s"] = round(time.perf_counter() - t0, 1)

        # 预置音色 / 语言自检
        try:
            spk = model.get_supported_speakers()
            res["speakers"] = sorted(spk) if spk else None
        except Exception:
            res["speakers"] = None

        t1 = time.perf_counter()
        wavs, sr = model.generate_custom_voice(
            text=TEXT, language="Chinese", speaker="Vivian",
        )
        res["gen_s"] = round(time.perf_counter() - t1, 1)
        res["sr"] = int(sr)
        dur = len(wavs[0]) / sr
        res["audio_s"] = round(dur, 2)
        res["rtf"] = round(res["gen_s"] / dur, 2) if dur else None
        res["rss_mb"] = round(_mem_mb())
        res["ok"] = True
        return res
    except Exception as e:  # noqa: BLE001
        res["err"] = f"{type(e).__name__}: {str(e)[:220]}"
        res["trace"] = traceback.format_exc()[-800:]
        return res
    finally:
        # 释放显存/内存，避免组合间互相污染
        try:
            del model  # noqa: F821
        except Exception:
            pass
        import gc
        gc.collect()
        if torch.backends.mps.is_available():
            try:
                torch.mps.empty_cache()
            except Exception:
                pass


def main() -> int:
    print("=" * 74)
    print("Qwen3-TTS 本机适配性探测")
    print(f"模型路径 : {MODEL_DIR}")
    print(f"存在     : {os.path.isdir(MODEL_DIR)}")
    print(f"torch    : {torch.__version__}")
    print(f"MPS 可用 : {torch.backends.mps.is_available()} (built={torch.backends.mps.is_built()})")
    print(f"CPU 核心 : {os.cpu_count()}")
    print("=" * 74)

    results = []
    for device_map, dtype, attn in CANDIDATES:
        print(f"\n>>> 尝试 {device_map} / {str(dtype).replace('torch.', '')} / {attn} ...", flush=True)
        r = probe(device_map, dtype, attn)
        results.append(r)
        if r["ok"]:
            print(f"    OK  加载 {r['load_s']}s | 生成 {r['gen_s']}s | "
                  f"音频 {r['audio_s']}s @ {r['sr']}Hz | RTF {r['rtf']} | RSS {r['rss_mb']}MB")
            print(f"    音色表: {r.get('speakers')}")
            break  # 第一个可用即停，省时间
        else:
            print(f"    FAIL {r['err']}")

    print("\n" + "=" * 74)
    print("汇总")
    for r in results:
        status = "OK  " if r["ok"] else "FAIL"
        print(f"  [{status}] {r['tag']:34s} load={r['load_s']} gen={r['gen_s']} rtf={r['rtf']} err={r['err']}")

    winner = next((r for r in results if r["ok"]), None)
    if winner:
        print(f"\n结论：可用组合 = {winner['tag']}")
        print(f"      RTF {winner['rtf']}（<1 表示快于实时）")
        return 0
    print("\n结论：四组组合全部失败，需要换路线（GGUF/CPU 量化 或 云端）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
