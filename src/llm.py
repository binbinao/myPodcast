"""LLM 调用工具（OpenAI 兼容）+ 不依赖 LLM 的文本清洗。

模块职责
--------
本模块是所有 LLM 调用方的公共底座，本身不含"润色"语义：
- ``resolve_api_key`` —— api_key 解析（cfg-first + env 兜底）
- ``llm_complete``    —— 通用 chat completions 调用（含 MiniMax thinking 兼容）
- ``heuristic_clean`` —— 纯字符串清洗，去 markdown 标记，保留 [角色] 标签

命名沿革：原名 ``polish.py``，因最初只服务于 ``polish()`` 整篇改写函数。
自 build 改为「draft 只读」契约后（守卫见
tests/test_stages.py::TestBuildReadOnlyContract），``polish()`` 已无任何调用者
——generate / prosody / voicecaster 只调 ``llm_complete``。模块名遂与职责脱节，
2026-09-21 改名为 ``llm.py``，并删掉三个只为 polish() 存在的私有函数
（FRONTMATTER_SPLIT / _split_frontmatter / _llm_polish / polish）。
"""
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
        # 曾是硬编码 0.7 + 完全不读 max_tokens：config.yaml 里两个键都是死配置。
        # max_tokens 尤其致命——默认上限截断长稿，是"产出集偏短"的一条成因。
        "temperature": float(llm.get("temperature", 0.7)),
        "max_tokens": int(llm.get("max_tokens", 4000)),
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


# 注：原来的 polish() / _llm_polish() 已删除 —— build 改为「draft 只读」后它
# 没有任何调用者（generate / prosody / voicecaster 只调 llm_complete）。
# 若将来确实需要"整篇改写"，请在调用方显式组合 llm_complete，
# 而不是在这里复活一个隐式入口 —— 那正是 draft 只读契约要防的东西。
