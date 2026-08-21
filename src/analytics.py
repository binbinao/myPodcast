"""站点访问统计：从 GoatCounter API 拉取 UV/PV。

- 单一职责: 只懂 GC API,不知道模板/配置
- 任何错误返回 None,绝不 raise
- 5s 超时 + 1 重试,国内 CI 拉 GC 受限时 warn 不 fail
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

GOATCOUNTER_API = "https://{code}.goatcounter.com/api/v0/stats/total"
TIMEOUT_SEC = 5
RETRY = 1


def fetch_stats(code: str, api_key: str) -> dict[str, int] | None:
    """拉取 GC total stats,返回 {"pv": int, "uv": int} 或 None。

    Args:
        code: 8 字符 GoatCounter site code
        api_key: GC "Allow API access" 生成的 token

    Returns:
        {"pv": visits, "uv": visitors} 或 None(任意错误)
    """
    url = GOATCOUNTER_API.format(code=code)
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    for attempt in range(RETRY + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                return _parse(data)
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, TimeoutError, OSError) as e:
            if attempt < RETRY:
                continue
            from .log import logger as log
            log.warning(f"[analytics] fetch_stats 失败: {e}")
            return None
    return None  # unreachable,for type checker


def _parse(data: dict[str, Any]) -> dict[str, int] | None:
    """宽容解析 GC 返回结构。

    GC 字段命名约定:
    - total_visits: PV
    - total_accepted: UV(去 bot 后)
    """
    pv = data.get("total_visits")
    uv = data.get("total_accepted")
    if not isinstance(pv, int) or not isinstance(uv, int):
        return None
    return {"pv": pv, "uv": uv}
