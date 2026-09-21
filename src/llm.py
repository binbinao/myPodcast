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
    """公开 API：解析 LLM api_key。优先级 cfg.api_key > cfg.api_key_env 列出的环境变量 > 默认 env 列表。

    其他 LLM 调用方（generate / prosody / voicecaster）应 import 此函数。

    `api_key_env` 存在的理由：多个 provider 的 key 同时躺在 shell 里时（例如
    MINIMAX_API_KEY 已欠费、SCNET_API_KEY 才是要用的那把），默认列表的顺序会
    取错 key —— 拿到的 key 能通过鉴权但配额已尽，报错很难定位。显式声明变量名
    顺序把这个隐式依赖变成配置项。
    """
    raw = str(cfg.get("api_key", "")).strip()
    if raw and raw != "${...}":
        return raw
    names = cfg.get("api_key_env")
    if names:
        # 显式声明了就只认这些 —— 不回落到默认列表，避免"静默用了别的 provider 的 key"
        if isinstance(names, str):
            names = [names]
        for name in names:
            v = os.environ.get(str(name), "").strip()
            if v:
                return v
        return ""
    for name in env_names:
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return ""


# 私有 alias，模块内保持 _resolve_api_key 调用一致
_resolve_api_key = resolve_api_key


def _is_local_endpoint(base_url: str) -> bool:
    """本机端点判定：127.0.0.1 / localhost / ::1。本机端点不需要 api_key。"""
    try:
        host = base_url.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0].split("]", 1)[0]
    except IndexError:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


# 模型清单缓存：{base_url: [model_id, ...]}。一次进程内复用，避免每集都多打一次网络。
_MODEL_LIST_CACHE: dict[str, list[str]] = {}


def _check_model_available(base_url: str, api_key: str, model: str, timeout: int = 8) -> None:
    """通用模型白名单预检：GET {base_url}/models，校验 model 在清单内。

    端点的 /models 不通（自建网关、本机服务未起等）就跳过预检，让正式调用
    自己报错 —— 预检是"把话说清楚"的辅助，不是新的失败点。

    配错模型名时上游往往只回一句干巴巴的 404/400，这里提前拦下并列出可用模型，
    把「写稿模型只能从可用模型中选」变成显式约束。
    """
    if base_url in _MODEL_LIST_CACHE:
        names = _MODEL_LIST_CACHE[base_url]
    else:
        if not base_url.startswith(("http://", "https://")):
            return  # 未配置 / 非法 base_url：预检无意义，交给正式调用报错
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            req = urllib.request.Request(base_url.rstrip("/") + "/models", headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            _MODEL_LIST_CACHE[base_url] = []
            return
        names = [str(m.get("id") or m.get("name") or "") for m in data.get("data") or data.get("models") or []]
        _MODEL_LIST_CACHE[base_url] = names
    if not names:
        return  # 端点没提供清单：不预检
    # 宽松匹配：大小写不敏感，允许 :tag / 前缀省略
    low = model.lower()
    for n in names:
        nl = n.lower()
        if nl == low or nl.split(":")[0] == low.split(":")[0]:
            return
    raise RuntimeError(
        f"写稿模型 {model!r} 不在该端点可用清单中（{base_url}）。只能从以下模型选择：\n  "
        + "\n  ".join(names)
        + "\n（改 config.yaml 的 llm.model）"
    )

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
    base_url = llm.get("base_url", "")
    model = llm.get("model", "")
    is_local = _is_local_endpoint(base_url)
    if not base_url.startswith(("http://", "https://")):
        raise RuntimeError(
            f"llm.base_url 未配置或非法（当前值 {base_url!r}）：应为 http(s)://... 的 OpenAI 兼容端点，"
            "例如 https://api.scnet.cn/api/llm/v1"
        )
    if not api_key and not is_local:
        hint_env = llm.get("api_key_env")
        want = ("export " + hint_env[0]) if isinstance(hint_env, list) and hint_env else (
            "export " + hint_env) if isinstance(hint_env, str) and hint_env else (
            "export LLM_API_KEY")
        raise RuntimeError(
            f"写稿 LLM 启用但拿不到 api_key（{base_url}）：\n"
            f"  1) {want}=<key> 写进 ~/.zshrc\n"
            f"  2) 或在 config.yaml 的 llm.api_key 直接填（该文件会进 git，别提交）\n"
            f"  3) 或把 llm.base_url 换成本机端点（如 http://127.0.0.1:11434/v1，无需 key）"
        )
    # 模型白名单预检：配错名时给出可用清单，而不是让上游回一句裸 404
    _check_model_available(base_url, api_key, model)
    # 是否为 MiniMax 端点（base_url 含 minimaxi.com/api.minimax）
    is_minimax = "minimax" in base_url.lower()
    payload: dict[str, Any] = {
        "model": model or "gpt-4o-mini",
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
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # 本机 27B 模型 decode ~9 tok/s，一次出稿几分钟：超时必须可配且默认放宽
    timeout = int(llm.get("timeout", 600))
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except Exception:
            pass
        raise RuntimeError(f"LLM 调用失败 HTTP {e.code}（{base_url}）：{body}") from e
    # 优先 content；reasoning_content 不应泄漏到脚本正文
    msg = data["choices"][0]["message"]
    return (msg.get("content") or "").strip()


# 注：原来的 polish() / _llm_polish() 已删除 —— build 改为「draft 只读」后它
# 没有任何调用者（generate / prosody / voicecaster 只调 llm_complete）。
# 若将来确实需要"整篇改写"，请在调用方显式组合 llm_complete，
# 而不是在这里复活一个隐式入口 —— 那正是 draft 只读契约要防的东西。
