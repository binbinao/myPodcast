"""守护 src/backends/qwen3_local.py 的契约（不依赖模型/服务，全 mock）。

测试范围
1. @register 把 Qwen3LocalBackend 注册到 REGISTRY["qwen3-local"]
2. chunk_text：按句末标点切，重组等于原文，不切词中
3. build_instruct：emotion → instruct 翻译，calm 不注入，base instructions 合并
4. _speak_sync：4xx 不重试直接抛；网络错误重试后成功；空音频视为失败
5. _health：服务不可达时抛 RuntimeError 且报文里带启动命令
6. prosody 全部 emotion 标签都有 instruct 映射
7. config 默认值（base_url 指向本机 8100）
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
    from src.backends.qwen3_local import (  # noqa: E402
        DEFAULT_BASE_URL,
        SPEAKERS,
        Qwen3LocalBackend,
        _EMO_INSTRUCTIONS,
        _health,
        _speak_sync,
        build_instruct,
        chunk_text,
    )
    _SKIP_REASON: str | None = None
except ImportError as _exc:
    _SKIP_REASON = f"qwen3_local backend 依赖缺失: {_exc}"


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestRegistry(unittest.TestCase):

    def test_registered_as_qwen3_local(self):
        from src.backends.base import REGISTRY
        self.assertIn("qwen3-local", REGISTRY,
                      "Qwen3LocalBackend 必须用 name='qwen3-local' 注册")

    def test_does_not_collide_with_cloud_qwen(self):
        from src.backends.base import REGISTRY
        self.assertIn("qwen-tts", REGISTRY, "云后端 qwen-tts 必须仍然在册")
        self.assertIsNot(REGISTRY["qwen-tts"], REGISTRY["qwen3-local"],
                         "本机后端不得覆盖 SCNet 云后端")

    def test_backend_is_instance(self):
        from src.backends.base import REGISTRY
        self.assertIsInstance(REGISTRY["qwen3-local"], Qwen3LocalBackend)


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestSpeakers(unittest.TestCase):

    def test_nine_premium_speakers(self):
        self.assertEqual(len(SPEAKERS), 9, "模型卡标明 9 个预置音色")

    def test_expected_speaker_names(self):
        for name in ("Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric",
                     "Ryan", "Aiden", "Ono_Anna", "Sohee"):
            self.assertIn(name, SPEAKERS)


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestChunkText(unittest.TestCase):

    def test_short_text_single_chunk(self):
        self.assertEqual(chunk_text("你好世界", 100), ["你好世界"])

    def test_split_on_sentence_boundary(self):
        text = "第一句话。第二句话。第三句话。"
        chunks = chunk_text(text, 12)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), text, "切片重组必须等于原文")
        for c in chunks:
            self.assertTrue(c.endswith("。"), f"切片应以句号结尾: {c!r}")

    def test_oversize_sentence_hard_split(self):
        text = "A" * 50 + "。" + "B" * 30
        chunks = chunk_text(text, 40)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), text)

    def test_exact_boundary_not_split(self):
        self.assertEqual(len(chunk_text("一二三。", 4)), 1)


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestBuildInstruct(unittest.TestCase):

    def test_calm_not_injected(self):
        self.assertIsNone(build_instruct({"emotion": "calm"}, "", True))

    def test_sad_translated(self):
        got = build_instruct({"emotion": "sad"}, "", True)
        self.assertIsNotNone(got)
        self.assertIn("低沉伤感", got)

    def test_use_emotion_false_ignores(self):
        self.assertIsNone(build_instruct({"emotion": "sad"}, "", False))

    def test_base_instructions_preserved(self):
        got = build_instruct({"emotion": "happy"}, "用电台主播腔", True)
        self.assertIn("用电台主播腔", got)
        self.assertIn("轻快愉悦", got)

    def test_no_emotion_returns_base(self):
        self.assertEqual(build_instruct({}, "用沉稳语气", True), "用沉稳语气")

    def test_unknown_emotion_falls_back_to_base(self):
        self.assertEqual(build_instruct({"emotion": "ecstatic"}, "基准", True), "基准")


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestSpeakSync(unittest.TestCase):

    def test_4xx_no_retry(self):
        r = MagicMock()
        r.status_code = 400
        r.text = "unknown voice"
        with patch("src.backends.qwen3_local.requests.post", return_value=r) as mp:
            with self.assertRaises(Exception) as ctx:
                _speak_sync("hi", "Serena", instruct=None, base_url=DEFAULT_BASE_URL,
                            language="Chinese", response_format="mp3",
                            speed=1.0, timeout=5)
            self.assertIn("400", str(ctx.exception))
            self.assertEqual(mp.call_count, 1, "4xx 必须不重试")

    def test_retry_then_success(self):
        ok = MagicMock()
        ok.status_code = 200
        ok.content = b"ID3fakeaudio"
        with patch("src.backends.qwen3_local.requests.post",
                   side_effect=[ConnectionError("down"), ok]):
            data = _speak_sync("hi", "Serena", instruct=None, base_url=DEFAULT_BASE_URL,
                               language="Chinese", response_format="mp3",
                               speed=1.0, timeout=5)
            self.assertEqual(data, b"ID3fakeaudio")

    def test_empty_audio_treated_as_failure(self):
        ok = MagicMock()
        ok.status_code = 200
        ok.content = b""
        with patch("src.backends.qwen3_local.requests.post", return_value=ok):
            with self.assertRaises(Exception):
                _speak_sync("hi", "Serena", instruct=None, base_url=DEFAULT_BASE_URL,
                            language="Chinese", response_format="mp3",
                            speed=1.0, timeout=5)

    def test_instruct_only_sent_when_present(self):
        ok = MagicMock()
        ok.status_code = 200
        ok.content = b"x"
        with patch("src.backends.qwen3_local.requests.post", return_value=ok) as mp:
            _speak_sync("hi", "Serena", instruct=None, base_url=DEFAULT_BASE_URL,
                        language="Chinese", response_format="mp3",
                        speed=1.0, timeout=5)
            self.assertNotIn("instruct", mp.call_args.kwargs["json"])


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestHealth(unittest.TestCase):

    def test_unreachable_gives_actionable_error(self):
        with patch("src.backends.qwen3_local.requests.get",
                   side_effect=ConnectionError("refused")):
            with self.assertRaises(RuntimeError) as ctx:
                _health(DEFAULT_BASE_URL)
            msg = str(ctx.exception)
            self.assertIn("start-qwen-tts-local.sh", msg,
                          "报错必须给出可执行的启动命令")

    def test_ok_returns_json(self):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"status": "ok", "engine": {"device": "mps"}}
        with patch("src.backends.qwen3_local.requests.get", return_value=r):
            self.assertEqual(_health(DEFAULT_BASE_URL)["engine"]["device"], "mps")


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestEmotionMap(unittest.TestCase):

    def test_prosody_labels_covered(self):
        from src.prosody import _EMO_MAP
        for emo, tup in _EMO_MAP.items():
            minimax_emo = tup[2] if len(tup) > 2 else tup[-1]
            self.assertIn(minimax_emo, _EMO_INSTRUCTIONS,
                          f"prosody 输出的 emotion {minimax_emo!r} 缺少 instruct 翻译")


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestConfigDefaults(unittest.TestCase):

    def test_default_base_url_is_localhost_8100(self):
        self.assertEqual(DEFAULT_BASE_URL, "http://127.0.0.1:8100")

    def test_config_has_qwen3local_block_and_voices(self):
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        self.assertIn("qwen3_local", cfg["tts"], "config.yaml 需有 tts.qwen3_local 段")
        self.assertIn("voices_qwen3local", cfg, "config.yaml 需有 voices_qwen3local 段")
        vm = cfg["voices_qwen3local"]
        for k in ("host", "guest", "default"):
            self.assertIn(k, vm)
        # 音色必须都在本机支持表里
        for k in ("host", "guest", "default"):
            self.assertIn(vm[k], SPEAKERS,
                          f"voices_qwen3local.{k}={vm[k]!r} 不是本机音色")


if __name__ == "__main__":
    unittest.main()
