"""站点访问统计：从 GoatCounter API 拉取 UV/PV。

所有测试走 unittest.mock,无真实 HTTP。
"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analytics import fetch_stats  # noqa: E402


def _mock_urlopen_response(body: bytes) -> MagicMock:
    """构造 mock context manager + read() 返回 body。"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp
    return mock_cm


class TestFetchStats(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_success_returns_pv_uv(self, mock_urlopen: MagicMock) -> None:
        """GC 返回 total_visits + total_accepted → fetch_stats 返回 dict。"""
        body = json.dumps({
            "total_visits": 1234,
            "total_accepted": 567,
            "starts": 999,
        }).encode("utf-8")
        mock_urlopen.return_value = _mock_urlopen_response(body)
        result = fetch_stats("code12345", "tk_xxx")
        self.assertEqual(result, {"pv": 1234, "uv": 567})

    @patch("urllib.request.urlopen")
    def test_passes_bearer_auth_header(self, mock_urlopen: MagicMock) -> None:
        """Authorization header 必须带 Bearer token。"""
        body = json.dumps({"total_visits": 1, "total_accepted": 1}).encode("utf-8")
        mock_urlopen.return_value = _mock_urlopen_response(body)
        fetch_stats("code12345", "tk_xxx")
        # urlopen 收到 Request 对象,验证 header
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        self.assertEqual(req.headers["Authorization"], "Bearer tk_xxx")


if __name__ == "__main__":
    unittest.main()
