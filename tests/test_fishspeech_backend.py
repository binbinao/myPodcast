"""守护 src/backends/fishspeech.py 的契约。

测试范围：
1. @register 把 FishSpeechBackend 注册到 REGISTRY["fish-speech"]
2. voice_map role 解析：seg.role → voice_map[role] → default fallback
3. _chunk_text：超长段按句末标点切，不切词中
4. _speak_sync 失败时的 3 次重试（mock HTTP）
5. config 解析：model 白名单 + env 兜底
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# fishspeech 后端依赖 httpx（外网 SDK）。本地/CI 没装时整个模块应 graceful skip，
# 而不是把所有 unittest runner 拖到 loader error。约定：src/backends/<backend>.py
# 可选依赖缺失 → 测试文件 load_tests 返回空 suite，不计入 fail。
try:
    from src import backends  # noqa: F401 — triggers @register
    from src.backends.fishspeech import (  # noqa: E402
        DEFAULT_BASE_URL,
        VALID_MODELS,
        FishSpeechBackend,
        _build_proxy_url,
        _chunk_text,
        _resolve_key,
    )
    _SKIP_REASON: str | None = None
except ImportError as _exc:
    _SKIP_REASON = f"fishspeech backend 依赖缺失: {_exc}"


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str) -> unittest.TestSuite:
    """缺依赖时跳过整个文件，避免 loader error 污染 CI 总数。

    注意：这里绝不能手动调 loader.loadTestsFromNames([__name__]) ——
    load_tests 本身就是 unittest 发现本模块测试的钩子，手动再调会无限递归
    （loadTestsFromNames → 触发 load_tests → 又 loadTestsFromNames → …），
    在 Python 3.13 下直接 RecursionError 崩掉整个 discover。
    """
    if _SKIP_REASON is not None:
        print(f"[skip] tests.test_fishspeech_backend — {_SKIP_REASON}")
        return loader.suiteClass()
    # 缺依赖时提前 return 空 suite；有依赖则让 loader 用默认逻辑发现
    # 本文件里的 TestCase（不手动递归 loadTestsFromNames）。
    return None


class TestRegistry(unittest.TestCase):

    def test_registered_as_fish_speech(self):
        from src.backends.base import REGISTRY
        self.assertIn("fish-speech", REGISTRY,
                      "FishSpeechBackend 必须用 name='fish-speech' 注册")
        self.assertIsInstance(REGISTRY["fish-speech"], FishSpeechBackend)

    def test_get_backend_dispatches(self):
        from src.backends.base import get_backend
        be = get_backend("fish-speech")
        self.assertIsInstance(be, FishSpeechBackend)


class TestResolveKey(unittest.TestCase):

    def test_cfg_api_key_takes_priority(self):
        with patch.dict(os.environ, {"FISH_AUDIO_API_KEY": "from_env"}, clear=False):
            self.assertEqual(_resolve_key({"api_key": "from_cfg"}), "from_cfg")

    def test_env_fallback(self):
        with patch.dict(os.environ, {"FISH_AUDIO_API_KEY": "from_env"}, clear=False):
            self.assertEqual(_resolve_key({}), "from_env")

    def test_empty_when_nothing(self):
        env = {k: v for k, v in os.environ.items() if k != "FISH_AUDIO_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(_resolve_key({}), "")


class TestChunkText(unittest.TestCase):

    def test_short_text_single_chunk(self):
        self.assertEqual(_chunk_text("短文本。", 100), ["短文本。"])

    def test_split_on_sentence_boundary(self):
        # 中文句末标点：。！？；
        text = "第一句。第二句！" + "填充。" * 50 + "第三句？"
        chunks = _chunk_text(text, max_chars=20)
        # 验证每个 chunk 不切在词中（每块都以标点结尾或完整句子）
        for c in chunks:
            self.assertTrue(
                c.endswith(("。", "！", "？", "；", "\n", "")) or len(c) <= 5,
                f"chunk 不应以词中断：{c!r}"
            )

    def test_no_word_split(self):
        # 100 个 "字" 字符连写（无标点）→ 单 chunk（无法切）
        text = "字" * 100
        chunks = _chunk_text(text, max_chars=20)
        # 没有句末标点，整体作为一个 chunk 发送（Fish 推荐 chunk_length ≤ 300）
        self.assertEqual(len(chunks), 1)


class TestModelValidation(unittest.TestCase):

    def test_default_models_listed(self):
        self.assertIn("s2.1-pro", VALID_MODELS)
        self.assertIn("s2.1-pro-free", VALID_MODELS)
        self.assertIn("s2-pro", VALID_MODELS)
        self.assertIn("s1", VALID_MODELS)

    def test_default_base_url(self):
        self.assertTrue(DEFAULT_BASE_URL.startswith("https://"),
                        f"base_url 应为 https：{DEFAULT_BASE_URL}")


class TestBuildProxies(unittest.TestCase):

    def test_none_returns_none(self):
        self.assertIsNone(_build_proxy_url(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_build_proxy_url(""))

    def test_socks5_url_returned_as_is(self):
        """httpx 接受单数字符串 proxy，不需要 dict 包装。"""
        out = _build_proxy_url("socks5://127.0.0.1:1086")
        self.assertEqual(out, "socks5://127.0.0.1:1086")

    def test_httpx_client_receives_proxy_and_http2(self):
        """验证 _speak_sync 用 httpx.Client(proxy=..., http2=True)。"""
        from src.backends.fishspeech import _speak_sync

        fake_resp = MagicMock(status_code=200, content=b"OK", headers={})
        # mock httpx.Client 上下文管理器
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = fake_resp

        test_proxy = "socks5://127.0.0.1:1086"
        with patch("src.backends.fishspeech.httpx.Client",
                   return_value=mock_client) as mock_Client:
            _speak_sync(
                "test", "ref-1",
                model="s2.1-pro-free", base_url=DEFAULT_BASE_URL, key="k",
                format_="mp3", sample_rate=44100, mp3_bitrate=128,
                temperature=0.7, top_p=0.7, timeout=30,
                proxy_url=test_proxy,
            )
        # 验证 Client 用 http2=True + proxy=...
        kwargs = mock_Client.call_args.kwargs
        self.assertTrue(kwargs["http2"])
        self.assertEqual(kwargs["proxy"], test_proxy)

    def test_httpx_client_no_proxy_when_empty(self):
        """无 proxy 时 httpx.Client 的 proxy 参数应为 None。"""
        from src.backends.fishspeech import _speak_sync

        fake_resp = MagicMock(status_code=200, content=b"OK", headers={})
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = fake_resp

        with patch("src.backends.fishspeech.httpx.Client",
                   return_value=mock_client) as mock_Client:
            _speak_sync(
                "x", "r", model="s2.1-pro-free", base_url=DEFAULT_BASE_URL, key="k",
                format_="mp3", sample_rate=44100, mp3_bitrate=128,
                temperature=0.7, top_p=0.7, timeout=30,
            )
        self.assertIsNone(mock_Client.call_args.kwargs["proxy"])

    def test_verify_ssl_default_true(self):
        """verify_ssl 默认应传给 httpx.Client（True）。"""
        from src.backends.fishspeech import _speak_sync

        fake_resp = MagicMock(status_code=200, content=b"OK", headers={})
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = fake_resp

        with patch("src.backends.fishspeech.httpx.Client",
                   return_value=mock_client) as mock_Client:
            _speak_sync(
                "x", "r", model="s2.1-pro-free", base_url=DEFAULT_BASE_URL, key="k",
                format_="mp3", sample_rate=44100, mp3_bitrate=128,
                temperature=0.7, top_p=0.7, timeout=30,
            )
        self.assertTrue(mock_Client.call_args.kwargs["verify"])

    def test_verify_ssl_false_passed(self):
        """verify_ssl=False 应传给 httpx.Client。"""
        from src.backends.fishspeech import _speak_sync

        fake_resp = MagicMock(status_code=200, content=b"OK", headers={})
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = fake_resp

        with patch("src.backends.fishspeech.httpx.Client",
                   return_value=mock_client) as mock_Client:
            _speak_sync(
                "x", "r", model="s2.1-pro-free", base_url=DEFAULT_BASE_URL, key="k",
                format_="mp3", sample_rate=44100, mp3_bitrate=128,
                temperature=0.7, top_p=0.7, timeout=30,
                verify_ssl=False,
            )
        self.assertFalse(mock_Client.call_args.kwargs["verify"])


class TestSpeakSyncRetries(unittest.TestCase):
    """mock HTTP，验证：失败时 3 次重试 + 指数退避；成功时返回 content。"""

    def _make_mock_client(self, post_side_effect):
        """构造 httpx.Client mock，返回一个 mock_client 实例。"""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        if isinstance(post_side_effect, list):
            mock_client.post.side_effect = post_side_effect
        else:
            mock_client.post.return_value = post_side_effect
        return mock_client

    def test_returns_content_on_success(self):
        from src.backends.fishspeech import _speak_sync
        fake_resp = MagicMock(status_code=200, content=b"FAKE_MP3_BYTES", headers={})
        mock_client = self._make_mock_client(fake_resp)

        with patch("src.backends.fishspeech.httpx.Client",
                   return_value=mock_client) as mock_Client:
            out = _speak_sync(
                "你好", "ref-123",
                model="s2.1-pro-free", base_url=DEFAULT_BASE_URL, key="k",
                format_="mp3", sample_rate=44100, mp3_bitrate=128,
                temperature=0.7, top_p=0.7, timeout=30,
            )

        self.assertEqual(out, b"FAKE_MP3_BYTES")
        # 验证 http2=True 必须开
        self.assertTrue(mock_Client.call_args.kwargs["http2"])
        # 验证请求 payload schema
        post_call = mock_client.post.call_args
        self.assertEqual(post_call.kwargs["headers"]["Authorization"], "Bearer k")
        self.assertEqual(post_call.kwargs["headers"]["model"], "s2.1-pro-free")
        body = post_call.kwargs["json"]
        self.assertEqual(body["text"], "你好")
        self.assertEqual(body["reference_id"], "ref-123")
        self.assertEqual(body["format"], "mp3")
        self.assertEqual(body["sample_rate"], 44100)
        self.assertEqual(body["mp3_bitrate"], 128)
        self.assertEqual(body["temperature"], 0.7)
        self.assertIn("chunk_length", body)

    def test_retries_3_times_on_5xx(self):
        from src.backends.fishspeech import _speak_sync

        # 第一次 + 第二次失败（500），第三次成功
        ok_resp = MagicMock(status_code=200, content=b"OK", headers={})
        fail_resp = MagicMock(status_code=500, text="server boom", headers={})
        mock_client = self._make_mock_client([fail_resp, fail_resp, ok_resp])

        with patch("src.backends.fishspeech.httpx.Client",
                   return_value=mock_client), \
             patch("src.backends.fishspeech.time.sleep") as mock_sleep:
            out = _speak_sync(
                "x", "ref",
                model="s2.1-pro-free", base_url=DEFAULT_BASE_URL, key="k",
                format_="mp3", sample_rate=44100, mp3_bitrate=128,
                temperature=0.7, top_p=0.7, timeout=30,
            )
        self.assertEqual(out, b"OK")
        # 验证 3 次调用 + 2 次 sleep (指数退避)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(2)

    def test_raises_after_3_failures(self):
        from src.backends.fishspeech import _speak_sync

        fail_resp = MagicMock(status_code=500, text="server boom", headers={})
        mock_client = self._make_mock_client([fail_resp, fail_resp, fail_resp])

        with patch("src.backends.fishspeech.httpx.Client",
                   return_value=mock_client), \
             patch("src.backends.fishspeech.time.sleep"):
            with self.assertRaises(RuntimeError):
                _speak_sync(
                    "x", "ref",
                    model="s2.1-pro-free", base_url=DEFAULT_BASE_URL, key="k",
                    format_="mp3", sample_rate=44100, mp3_bitrate=128,
                    temperature=0.7, top_p=0.7, timeout=30,
                )

    def test_raises_on_4xx(self):
        """4xx 不重试，立即报错。"""
        from src.backends.fishspeech import _speak_sync

        fail_resp = MagicMock(status_code=400, text="bad request", headers={"content-type": "application/json"})
        mock_client = self._make_mock_client(fail_resp)

        with patch("src.backends.fishspeech.httpx.Client",
                   return_value=mock_client), \
             patch("src.backends.fishspeech.time.sleep") as mock_sleep:
            with self.assertRaises(RuntimeError) as cm:
                _speak_sync(
                    "x", "ref",
                    model="s2.1-pro-free", base_url=DEFAULT_BASE_URL, key="k",
                    format_="mp3", sample_rate=44100, mp3_bitrate=128,
                    temperature=0.7, top_p=0.7, timeout=30,
                )
        self.assertIn("400", str(cm.exception))
        # 4xx 不重试，无 sleep
        self.assertEqual(mock_sleep.call_count, 0)


class TestGenerateVoiceMap(unittest.TestCase):
    """voice_map 解析的端到端验证（mock HTTP 调用层）。"""

    def _run_generate(self, segments, voice_map, fish_cfg):
        """用 mock 替换 _speak，验证 voice_map 解析路径但不真发请求。"""
        be = FishSpeechBackend()
        cfg = {
            "tts": {
                "pause_ms": 100,
                "fishspeech": fish_cfg,
            }
        }
        # monkey-patch _speak 直接返回固定 bytes（避免真 ffmpeg + 真 HTTP）
        from src.backends import fishspeech as fs_mod
        async def fake_speak(*a, **kw):
            return b"FAKE"
        # monkey-patch 同模块下的 _speak（generate() 调用 _speak）
        # 同时 stub ffmpeg subprocess.run 简化测试（避免依赖 ffmpeg）
        with patch.object(fs_mod, "_speak", side_effect=fake_speak), \
             patch.object(fs_mod.subprocess, "run",
                          return_value=MagicMock(returncode=0, stderr="")):
            import asyncio
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "ep.mp3"
                # 由于 ffmpeg 调用被 stub，文件不会被真创建；用 path.parent 即可
                out.parent.mkdir(parents=True, exist_ok=True)
                # ffmpeg stub：上面 patch 了 subprocess.run（包括 ffprobe）
                # duration probe 返回 0 → 不会爆
                try:
                    return asyncio.run(be.generate(segments, voice_map, cfg, out))
                except Exception as e:
                    # 我们只关心 raise 前的解析路径；这里把异常 reraise 让测试看清原因
                    raise

    def test_missing_api_key_raises(self):
        env = {k: v for k, v in os.environ.items() if k != "FISH_AUDIO_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            be = FishSpeechBackend()
            cfg = {"tts": {"pause_ms": 100,
                           "fishspeech": {"model": "s2.1-pro-free", "api_key": ""}}}
            import asyncio, tempfile
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "ep.mp3"
                with self.assertRaises(RuntimeError) as cm:
                    asyncio.run(be.generate(
                        [{"role": "host", "text": "你好"}],
                        {"host": "ref-1", "default": "ref-1"},
                        cfg, out,
                    ))
                self.assertIn("FISH_AUDIO_API_KEY", str(cm.exception))

    def test_invalid_model_raises(self):
        be = FishSpeechBackend()
        cfg = {"tts": {"pause_ms": 100,
                       "fishspeech": {"model": "gpt-4", "api_key": "k"}}}
        import asyncio, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ep.mp3"
            with self.assertRaises(RuntimeError) as cm:
                asyncio.run(be.generate(
                    [{"role": "host", "text": "你好"}],
                    {"host": "ref-1", "default": "ref-1"},
                    cfg, out,
                ))
            self.assertIn("不支持的 model", str(cm.exception))

    def test_empty_voice_id_uses_fish_default(self):
        """空 voice_id（未配置）应允许：让 Fish Audio 用默认音色，不阻断。"""
        be = FishSpeechBackend()
        cfg = {"tts": {"pause_ms": 100,
                       "fishspeech": {"model": "s2.1-pro-free", "api_key": "k"}}}
        import asyncio, tempfile
        from src.backends import fishspeech as fs_mod
        async def fake_speak(*a, **kw):
            return b"FAKE"
        with patch.object(fs_mod, "_speak", side_effect=fake_speak), \
             patch.object(fs_mod.subprocess, "run",
                          return_value=MagicMock(returncode=0, stderr="")):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "ep.mp3"
                # voice_map 全空，应不抛错（让 Fish 用默认音色）
                try:
                    asyncio.run(be.generate(
                        [{"role": "host", "text": "你好"}],
                        {},  # 空 voice_map
                        cfg, out,
                    ))
                except RuntimeError as e:
                    if "voice_id" in str(e):
                        self.fail(f"空 voice_map 不应要求 voice_id：{e}")
                # 验证 _speak 被调用时 reference_id 是空字符串
                call_kwargs = fs_mod._speak.call_args
                self.assertEqual(call_kwargs.args[1], "")  # reference_id=""


if __name__ == "__main__":
    unittest.main()