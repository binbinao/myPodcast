"""脚本润色：可选 LLM（OpenAI 兼容），默认启发式清洗。"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any


def resolve_api_key(cfg: dict[str, Any], env_names: tuple[str, ...] = ("LLM_API_KEY", "MINIMAX_API_KEY", "OPENAI_API_KEY")) -> str:
    """公开 API：解析 LLM api_key。优先级 cfg.api_key > 环境变量。

    其他 LLM 调用方（generate / prosody / voicecaster）应 import 此函数。
    """
    raw = str(cfg.get("api_key", "")).strip()
    if raw and raw != "${...}":
        return raw
    for name in env_names:
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return ""


# 私有 alias，模块内保持 _resolve_api_key 调用一致
_resolve_api_key = resolve_api_key

FRONTMATTER_SPLIT = re.compile(r"^(---\s*\n.*?\n---\s*\n)", re.DOTALL)


def _split_frontmatter(text: str) -> tuple[str, str]:
    m = FRONTMATTER_SPLIT.match(text)
    if not m:
        return "", text
    return m.group(1), text[m.end():]


def _heuristic(body: str) -> str:
    """轻量清洗：去 markdown 标记，保留 [角色] 标签。"""
    out = []
    for line in body.splitlines():
        if not line.strip():
            continue
        line = re.sub(r"[#*`]", "", line)            # 去标题/粗体/代码标记
        line = re.sub(r"^\s*[-*]\s+", "", line)       # 去无序列表符
        line = re.sub(r"^\s*\d+\.\s+", "", line)      # 去有序列表符
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            out.append(line)
    return "\n".join(out)


# 公开别名：generate.py 在 LLM 出口处做二次清洗时调用。
heuristic_clean = _heuristic


def llm_complete(system_prompt: str, user_content: str, cfg: dict[str, Any]) -> str:
    """通用 LLM 调用（OpenAI 兼容）。用于润色与脚本生成。

    兼容注：MiniMax 系列模型默认开启 thinking（reasoning_tokens 把
    completion_tokens 烧光，message.content 为空）。通过本函数的
    `reasoning_split=true` + `thinking.type=disabled` 让 reasoning 走
    独立字段、content 字段拿到正文。OpenAI 等其他 provider 会忽略
    未知字段，无副作用。
    """
    llm = cfg.get("llm", {})
    api_key = _resolve_api_key(llm)
    if not api_key:
        raise RuntimeError(
            "LLM 启用但拿不到 api_key：填 config.yaml 的 llm.api_key "
            "或 export LLM_API_KEY / MINIMAX_API_KEY / OPENAI_API_KEY"
        )
    # 是否为 MiniMax 端点（base_url 含 minimaxi.com/api.minimax）
    is_minimax = "minimax" in llm.get("base_url", "").lower()
    payload: dict[str, Any] = {
        "model": llm.get("model", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.7,
    }
    if is_minimax:
        payload["thinking"] = {"type": "disabled"}
        payload["reasoning_split"] = True
    req = urllib.request.Request(
        llm["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    # 优先 content；reasoning_content 不应泄漏到脚本正文
    msg = data["choices"][0]["message"]
    return (msg.get("content") or "").strip()


def _llm_polish(body: str, cfg: dict[str, Any]) -> str:
    llm = cfg.get("llm", {})
    prompt = llm.get("prompt", "把下面内容改写成口语化播客脚本，用 [host] 和 [guest] 交替。")
    return llm_complete(prompt, body, cfg)


def polish(text: str, cfg: dict[str, Any]) -> str:
    """润色整篇脚本（保留 frontmatter）。"""
    fm, body = _split_frontmatter(text)
    llm = cfg.get("llm", {})
    use_llm = bool(llm.get("enable")) and bool(_resolve_api_key(llm))
    if use_llm:
        new_body = _llm_polish(body, cfg)
    else:
        new_body = _heuristic(body)
    return fm + new_body
