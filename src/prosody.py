"""韵律规划：把口播文本切成带 prosody 标记的句片段，缓解单人播客单调。

两种模式：
- heuristic（默认，零依赖）：按句末标点给每句 rate/pitch/break，并在连续句号句上
  叠加轻微正弦波形，避免"整段一个参数"的机械感。
- llm：调 LLM 给每句打情绪标签 (neutral/happy/excited/...)，映射到 prosody。
  需 config.yaml 里 llm.enable=true 且有 api_key；LLM 失败时自动回退 heuristic。
"""
from __future__ import annotations

import math
import re
from typing import Any

from .polish import llm_complete

# 以这些标点/换行切句（中英文句末 + 分号 + 省略号）
_SPLIT_RE = re.compile(r"(?<=[。！？!?；;…\.\n])")

# 移除 emoji / 零宽字符 / 变体选择符 / 组合符（避免被 TTS 念出或乱读）
_EMOJI_RE = re.compile(
    "[\u2600-\u27BF\u2B00-\u2BFF\u1F000-\u1FAFF\u2190-\u21FF"
    "\uFE00-\uFE0F\u200B-\u200D\u20E3]"
)

# LLM 情绪标签 -> (rate, pitch, minimax_emotion)
_EMO_MAP: dict[str, tuple[str, str, str]] = {
    "neutral": ("+0%", "+0Hz", "calm"),
    "happy": ("+8%", "+6Hz", "happy"),
    "excited": ("+12%", "+8Hz", "happy"),
    "sad": ("-8%", "-4Hz", "sad"),
    "angry": ("-4%", "+4Hz", "angry"),
    "calm": ("-6%", "+0Hz", "calm"),
    "thoughtful": ("-6%", "+2Hz", "calm"),
    "question": ("-6%", "+6Hz", "surprised"),
    "serious": ("+0%", "+0Hz", "calm"),
    "whisper": ("-10%", "-2Hz", "whisper"),
}


def _clean(text: str) -> str:
    return _EMOJI_RE.sub("", text)


def _escape(s: str) -> str:
    """SSML 文本转义，避免 < > & 破坏 XML。"""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _heuristic(sentence: str, idx: int) -> dict[str, str]:
    """按句末标点给韵律参数；连续句号句叠加轻微正弦波形避免全平。

    emotion 字段映射到 MiniMax 9 种之一：happy/sad/angry/fearful/disgusted/
    surprised/calm/fluent/whisper。edge-tts backend 不消费此字段。
    """
    s = sentence.strip()
    if not s:
        return {"rate": "+0%", "pitch": "+0Hz", "break_ms": "300", "emotion": "calm"}
    last = s[-1]
    if last in "？?":                      # 问句：升调、略慢
        return {"rate": "-6%", "pitch": "+6Hz", "break_ms": "520", "emotion": "surprised"}
    if last in "！!":                      # 感叹/强调：加重、略慢
        return {"rate": "-4%", "pitch": "+4Hz", "break_ms": "520", "emotion": "happy"}
    if last in "…":                        # 省略/留白：明显放慢
        return {"rate": "-10%", "pitch": "+0Hz", "break_ms": "720", "emotion": "sad"}
    if last in "；;":                      # 分号：紧凑
        return {"rate": "+6%", "pitch": "+0Hz", "break_ms": "340", "emotion": "fluent"}
    if last in "。.":                      # 句号：基础值 + 轻微波形起伏
        wave = math.sin(idx * 0.9) * 4     # rate 约 -4%~+4%
        ph = math.cos(idx * 0.9) * 3       # pitch 约 -3Hz~+3Hz
        # 句号主调 calm，偶发轻微 surprised 增加层次
        emo = "surprised" if math.sin(idx * 1.3) > 0.6 else "calm"
        return {
            "rate": f"{round(wave):+d}%",
            "pitch": f"{round(ph):+d}Hz",
            "break_ms": "460",
            "emotion": emo,
        }
    return {"rate": "+2%", "pitch": "+0Hz", "break_ms": "240", "emotion": "calm"}


def _split(text: str) -> list[str]:
    text = _clean(text)
    return [p.strip() for p in _SPLIT_RE.split(text) if p.strip()]


def _plan_llm(text: str, cfg: dict[str, Any]) -> list[dict[str, str]]:
    sys_prompt = (
        "你是播客口播韵律规划器。把给定中文口播文本逐句拆开，每行一句，"
        "句首用(情绪)标注该句语气，情绪只能从以下选一个："
        "neutral / happy / excited / sad / angry / calm / thoughtful / question / serious / whisper。"
        "只输出标注后的文本，不要解释，不要增删字词，保留原标点。"
    )
    labeled = llm_complete(sys_prompt, text, cfg)
    out: list[dict[str, str]] = []
    for line in labeled.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"\((\w+)\)\s*(.*)", line)
        if m:
            emo = m.group(1).lower()
            sent = _clean(m.group(2).strip())
        else:
            emo, sent = "neutral", _clean(line)
        if not sent:
            continue
        rate, pitch, m_emo = _EMO_MAP.get(emo, ("+0%", "+0Hz", "calm"))
        out.append({"text": sent, "rate": rate, "pitch": pitch, "break_ms": "460", "emotion": m_emo})
    return out


def plan_sentences(text: str, cfg: dict[str, Any]) -> list[dict[str, str]]:
    """返回句片段列表：[{text, rate, pitch, break_ms}]。"""
    prosody_cfg = cfg.get("prosody", {})
    mode = str(prosody_cfg.get("mode", "heuristic")).lower()
    if mode == "llm" and cfg.get("llm", {}).get("enable") and cfg["llm"].get("api_key"):
        try:
            return _plan_llm(text, cfg)
        except Exception:
            pass  # LLM 失败回退启发式
    out = []
    for i, s in enumerate(_split(text)):
        p = _heuristic(s, i)
        out.append(
            {"text": s, "rate": p["rate"], "pitch": p["pitch"],
             "break_ms": p["break_ms"], "emotion": p["emotion"]}
        )
    return out
