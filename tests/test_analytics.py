"""站点访问统计：从 GoatCounter API 拉取 UV/PV。

所有测试走 unittest.mock,无真实 HTTP。
"""
from __future__ import annotations

import json
import sys
import tempfile
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

    @patch("urllib.request.urlopen")
    def test_401_returns_none(self, mock_urlopen: MagicMock) -> None:
        """API key 错/缺 → GC 401 → 返回 None。"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, None,
        )
        self.assertIsNone(fetch_stats("code12345", "wrong_key"))

    @patch("urllib.request.urlopen")
    def test_timeout_returns_none(self, mock_urlopen: MagicMock) -> None:
        """网络超时(国内 CI 拉 GC) → 返回 None。"""
        mock_urlopen.side_effect = TimeoutError("timed out")
        self.assertIsNone(fetch_stats("code12345", "tk_xxx"))

    @patch("urllib.request.urlopen")
    def test_malformed_json_returns_none(self, mock_urlopen: MagicMock) -> None:
        """200 OK 但 body 非 JSON → 返回 None。"""
        mock_urlopen.return_value = _mock_urlopen_response(b"<html>500 error</html>")
        self.assertIsNone(fetch_stats("code12345", "tk_xxx"))

    @patch("urllib.request.urlopen")
    def test_missing_keys_returns_none(self, mock_urlopen: MagicMock) -> None:
        """200 OK + JSON,但缺 total_accepted → 返回 None。"""
        body = json.dumps({"total_visits": 100}).encode("utf-8")
        mock_urlopen.return_value = _mock_urlopen_response(body)
        self.assertIsNone(fetch_stats("code12345", "tk_xxx"))


class TestBuildIndexAnalytics(unittest.TestCase):
    """build_index 集成:验证 analytics script tag 渲染。"""

    def _setup_out_dir(self) -> tuple[Path, Path]:
        """返回 (tmp_out_dir, project_root)。"""
        tmp = Path(tempfile.mkdtemp(prefix="analytics-test-"))
        # build_index 读 manifest.json(空数组就行)+ 渲染 index.html
        (tmp / "manifest.json").write_text(
            json.dumps({"episodes": []}), encoding="utf-8",
        )
        return tmp, ROOT

    def _podcast_cfg(self, analytics: dict | None) -> dict:
        cfg = {
            "title": "Test",
            "description": "Test",
            "tagline": "T",
            "website": "https://example.com",
            "language": "zh-CN",
            "author": "T",
            "cover": "",
            "subscribe": {"enabled": False},
        }
        if analytics is not None:
            cfg["analytics"] = analytics
        return cfg

    @patch("src.analytics.fetch_stats", return_value={"pv": 100, "uv": 50})
    def test_emits_script_tag_when_enabled(self, mock_fetch: MagicMock) -> None:
        """enabled=true + code 填了 → output/index.html <head> 含 GC script。"""
        tmp, root = self._setup_out_dir()
        try:
            cfg = self._podcast_cfg({"enabled": True, "code": "abc12345", "api_key": "tk_x"})
            from src.feed import build_index
            build_index(tmp, cfg)
            html = (tmp / "index.html").read_text(encoding="utf-8")
            self.assertIn(
                'data-goatcounter="https://abc12345.goatcounter.com/count"',
                html,
            )
            self.assertIn('src="//gc.zgo.at/count.js"', html)
            mock_fetch.assert_called_once_with("abc12345", "tk_x")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("src.analytics.fetch_stats", return_value={"pv": 100, "uv": 50})
    def test_no_script_when_disabled(self, mock_fetch: MagicMock) -> None:
        """enabled=false → 无 GC script,fetch_stats 不被调用。"""
        tmp, root = self._setup_out_dir()
        try:
            cfg = self._podcast_cfg({"enabled": False, "code": "abc12345", "api_key": "tk_x"})
            from src.feed import build_index
            build_index(tmp, cfg)
            html = (tmp / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("data-goatcounter", html)
            mock_fetch.assert_not_called()
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("src.analytics.fetch_stats", return_value={"pv": 1234, "uv": 567})
    def test_emits_footer_widget_when_stats(self, mock_fetch: MagicMock) -> None:
        """stats 有值 → footer 含 .footer-stats span,数字带千位分隔符。"""
        tmp, root = self._setup_out_dir()
        try:
            cfg = self._podcast_cfg({"enabled": True, "code": "abc12345", "api_key": "tk_x"})
            from src.feed import build_index
            build_index(tmp, cfg)
            html = (tmp / "index.html").read_text(encoding="utf-8")
            self.assertIn("footer-stats", html)
            self.assertIn("1,234 次访问", html)
            self.assertIn("567 位独立访客", html)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("src.analytics.fetch_stats", return_value=None)
    def test_widget_hidden_when_stats_none(self, mock_fetch: MagicMock) -> None:
        """fetch_stats 返回 None(API 失败) → footer 无 .footer-stats。"""
        tmp, root = self._setup_out_dir()
        try:
            cfg = self._podcast_cfg({"enabled": True, "code": "abc12345", "api_key": "tk_x"})
            from src.feed import build_index
            build_index(tmp, cfg)
            html = (tmp / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("footer-stats", html)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
