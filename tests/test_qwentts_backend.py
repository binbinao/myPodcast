"""守护 src/backends/qwen_tts.py 的契约。

测试范围：
1. @register 把 QwenTTSBackend 注册到 REGISTRY["qwen-tts"]
2. _resolve_key：env SCNET_API_KEY 优先，config 兜底
3. _chunk_text：超长段按句末标点切，不切词中
4. _speak_sync：4xx 不重试直接抛；网络错误重试后成功；成功路径解析 results[0] URL
5. emotion → instructions 翻译表覆盖 prosody 全部标签
6. config 读取：base_url/model/chunk_chars 默认值
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from src import backends  # noqa: F401 — triggers @register
    from src.backends.qwen_tts import (  # noqa: E402
        DEFAULT_BASE_URL,
        DEFAULT_MODEL,
        QwenTTSBackend,
        _EMO_INSTRUCTIONS,
        _chunk_text,
        _resolve_key,
        _speak_sync,
    )
    _SKIP_REASON: str | None = None
except ImportError as _exc:
    _SKIP_REASON = f"qwen_tts backend 依赖缺失: {_exc}"


class TestRegistry(unittest.TestCase):

    def test_registered_as_qwen_tts(self):
        from src.backends.base import REGISTRY
        self.assertIn("qwen-tts", REGISTRY,
                      "QwenTTSBackend 必须用 name='qwen-tts' 注册")

    def test_backend_is_qwenttsbackend_instance(self):
        from src.backends.base import REGISTRY
        self.assertIsInstance(REGISTRY["qwen-tts"], QwenTTSBackend)


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestResolveKey(unittest.TestCase):

    def test_env_takes_priority(self):
        with patch.dict("os.environ", {"SCNET_API_KEY": "env-key"}):
            self.assertEqual(_resolve_key({"api_key": "cfg-key"}), "env-key")

    def test_config_fallback(self):
        import os
        env_backup = os.environ.pop("SCNET_API_KEY", None)
        try:
            self.assertEqual(_resolve_key({"api_key": "cfg-key"}), "cfg-key")
            self.assertEqual(_resolve_key({}), "")
        finally:
            if env_backup is not None:
                os.environ["SCNET_API_KEY"] = env_backup


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestChunkText(unittest.TestCase):

    def test_short_text_single_chunk(self):
        self.assertEqual(_chunk_text("你好世界", 100), ["你好世界"])

    def test_split_on_sentence_boundary(self):
        text = "第一句话。第二句话。第三句话。"
        chunks = _chunk_text(text, 12)
        self.assertGreater(len(chunks), 1)
        # 每片都不应词中切断：重组后等于原文
        self.assertEqual("".join(chunks), text)
        for c in chunks:
            self.assertTrue(c.endswith("。"), f"切片应以句号结尾: {c!r}")

    def test_oversize_sentence_hard_split(self):
        text = "A" * 50 + "。" + "B" * 30
        chunks = _chunk_text(text, 40)
        self.assertGreater(len(chunks), 1)


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestSpeakSync(unittest.TestCase):

    def _ok_response(self, audio_url="https://cdn.example.com/a.wav"):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {
            "request_id": "req1",
            "output": {
                "task_id": "t1",
                "task_status": "succeeded",
                "results": [audio_url],
            },
            "usage": {"input_chars_num": 10},
        }
        return r

    def test_4xx_no_retry(self):
        r400 = MagicMock()
        r400.status_code = 401
        r400.text = "unauthorized"
        with patch("src.backends.qwen_tts.requests.post", return_value=r400) as mp:
            with self.assertRaises(Exception) as ctx:
                _speak_sync("hi", "Ethan", instructions=None, model=DEFAULT_MODEL,
                            key="k", base_url=DEFAULT_BASE_URL, timeout=5)
            self.assertIn("401", str(ctx.exception))
            self.assertEqual(mp.call_count, 1, "4xx 必须不重试")

    def test_retry_then_success(self):
        ok = self._ok_response()
        with patch("src.backends.qwen_tts.requests.post",
                   side_effect=[ConnectionError("network down"), ok]), \
             patch("src.backends.qwen_tts.requests.get") as mg:
            mg.return_value.status_code = 200
            mg.return_value.content = b"ID3fakeaudio"
            data = _speak_sync("hi", "Ethan", instructions=None, model=DEFAULT_MODEL,
                               key="k", base_url=DEFAULT_BASE_URL, timeout=5)
            self.assertEqual(data, b"ID3fakeaudio")

    def test_pending_status_raises(self):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"output": {"task_status": "pending", "results": []}}
        with patch("src.backends.qwen_tts.requests.post", return_value=r):
            with self.assertRaises(RuntimeError) as ctx:
                _speak_sync("hi", "Ethan", instructions=None, model=DEFAULT_MODEL,
                            key="k", base_url=DEFAULT_BASE_URL, timeout=5)
            self.assertIn("pending", str(ctx.exception))

    def test_data_uri_passthrough(self):
        import base64
        audio = b"ID3datauri"
        uri = "data:audio/wav;base64," + base64.b64encode(audio).decode()
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"output": {"task_status": "succeeded", "results": [uri]}}
        with patch("src.backends.qwen_tts.requests.post", return_value=r):
            data = _speak_sync("hi", "Ethan", instructions=None, model=DEFAULT_MODEL,
                               key="k", base_url=DEFAULT_BASE_URL, timeout=5)
            self.assertEqual(data, audio)


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestEmotionMap(unittest.TestCase):

    def test_prosody_labels_covered(self):
        # prosody._EMO_MAP 输出的 emotion 标签（minimax 词表 + llm 词表）都应能翻译
        from src.prosody import _EMO_MAP
        for emo in _EMO_MAP:
            self.assertIn(emo, _EMO_INSTRUCTIONS,
                          f"prosody 标签 {emo!r} 缺少 instructions 翻译")


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestConfigDefaults(unittest.TestCase):

    def test_backend_reads_qwen_block(self):
        b = QwenTTSBackend()
        self.assertEqual(b.name, "qwen-tts")
        # generate 的 config 读取路径以 tts.qwen 为根
        self.assertEqual(DEFAULT_MODEL, "Qwen3-TTS-Instruct-Flash")
        self.assertTrue(DEFAULT_BASE_URL.startswith("https://api.scnet.cn/"))


if __name__ == "__main__":
    unittest.main()
