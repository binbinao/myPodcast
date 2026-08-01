"""脚本润色：可选 LLM（OpenAI 兼容），默认启发式清洗。"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

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


def _llm_polish(body: str, cfg: dict[str, Any]) -> str:
    llm = cfg.get("llm", {})
    prompt = llm.get("prompt", "把下面内容改写成口语化播客脚本，用 [host] 和 [guest] 交替。")
    payload = {
        "model": llm.get("model", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": body},
        ],
        "temperature": 0.7,
    }
    req = urllib.request.Request(
        llm["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {llm['api_key']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"].strip()


def polish(text: str, cfg: dict[str, Any]) -> str:
    """润色整篇脚本（保留 frontmatter）。"""
    fm, body = _split_frontmatter(text)
    llm = cfg.get("llm", {})
    if llm.get("enable") and llm.get("api_key"):
        new_body = _llm_polish(body, cfg)
    else:
        new_body = _heuristic(body)
    return fm + new_body
