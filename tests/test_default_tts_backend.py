"""守护「本机 Qwen3-TTS 是默认后端」这条契约（纯静态，不依赖模型/服务/网络）。

为什么要这个文件
----------------
`tts.backend` 是**全局默认**：改错一个字符，全量 build 会静默走到别的引擎
（edge-tts 音色单调 / minimax 烧钱）。这类回归不会让任何测试变红，
只会在出片时才发现。所以把「默认是谁」显式钉成断言。

覆盖
1. config.yaml `tts.backend == "qwen3-local"`
2. config.yaml `voices_qwen3local` 的 host/guest/default 都是本机合法音色
3. config.yaml `tts.qwen3_local.base_url` 指向本机服务
4. src/build.py 的 voice_key 路由：qwen3-local → voices_qwen3local
5. src/build.py 的 duo 音色回退：非本机音色（历史 minimax ID）回退而非报错
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import yaml
    from src.backends.qwen3_local import DEFAULT_BASE_URL, SPEAKERS
    _SKIP_REASON: str | None = None
except ImportError as _exc:  # pragma: no cover
    _SKIP_REASON = f"依赖缺失: {_exc}"

CONFIG_PATH = ROOT / "config.yaml"
BUILD_PATH = ROOT / "src" / "build.py"


def _cfg() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _build_tree() -> ast.Module:
    return ast.parse(BUILD_PATH.read_text(encoding="utf-8"))


def _find_run_one(tree: ast.Module) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_one":
            return node
    raise AssertionError("src/build.py 里找不到 run_one()")


def _string_constants(node: ast.AST) -> set[str]:
    return {
        n.value for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestDefaultBackendContract(unittest.TestCase):
    """config.yaml 层的默认契约。"""

    def test_config_default_backend_is_qwen3_local(self):
        backend = _cfg().get("tts", {}).get("backend")
        self.assertEqual(
            backend, "qwen3-local",
            f"默认 TTS 后端必须是 qwen3-local（本机），当前为 {backend!r}。"
            " 若这是有意切换，请同步更新本测试与 README 的后端表。",
        )

    def test_qwen3local_voices_are_valid_speakers(self):
        vm = _cfg().get("voices_qwen3local") or {}
        self.assertTrue(vm, "config.yaml 缺 voices_qwen3local 块")
        for role in ("host", "guest", "default"):
            v = vm.get(role)
            self.assertIn(v, SPEAKERS, f"voices_qwen3local.{role}={v!r} 不是本机音色")

    def test_local_service_base_url_points_to_loopback(self):
        url = (_cfg().get("tts", {}).get("qwen3_local", {}) or {}).get("base_url", "")
        self.assertEqual(
            url.rstrip("/"), DEFAULT_BASE_URL,
            "tts.qwen3_local.base_url 必须指向本机常驻服务",
        )

    def test_ci_env_hint_does_not_change_backend(self):
        """CI 里设的 TTS_BACKEND 环境变量代码并不消费——防止有人误以为它能覆盖。

        workflow 的 publish.yml 设了 `TTS_BACKEND: edge-tts`，但 src/ 下没有任何
        代码读它；CI 靠 `--skip-audio` 跳过 TTS 才没炸。这条断言把这个事实钉住：
        一旦有人真的实现了 env 覆盖，这里会红，提醒同步修 workflow。
        """
        src_text = "\n".join(
            p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py")
        )
        self.assertNotIn(
            "TTS_BACKEND", src_text,
            "src/ 开始消费 TTS_BACKEND 了：请同步更新 .github/workflows/publish.yml",
        )


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class TestVoiceRoutingInBuild(unittest.TestCase):
    """src/build.py 的音色路由（AST 级，静态）。"""

    def test_qwen3_local_maps_to_its_own_voice_table(self):
        tree = _build_tree()
        run_one = _find_run_one(tree)
        found = False
        for node in ast.walk(run_one):
            if not isinstance(node, ast.If):
                continue
            if "qwen3-local" not in _string_constants(node.test):
                continue
            for stmt in node.body:
                if "voices_qwen3local" in _string_constants(stmt):
                    found = True
        self.assertTrue(
            found,
            "run_one() 里缺 `backend == 'qwen3-local' → voice_key = 'voices_qwen3local'`",
        )

    def test_duo_voice_fallback_for_foreign_speakers(self):
        """历史稿件的 frontmatter 存的是 minimax ID（audiobook_male_1 等），
        本机音色表里没有；build 必须回退到 voices_qwen3local 而不是抛错。"""
        run_one = _find_run_one(_build_tree())
        src = ast.unparse(run_one)
        self.assertIn("SPEAKERS", src, "duo 分支缺本机音色合法性校验")
        self.assertRegex(
            src, r"host_voice|host_v",
            "duo 分支应基于 frontmatter host_voice 判断是否回退",
        )
        # 回退即重新赋值，而不是 raise
        self.assertNotIn(
            "raise", src.split("SPEAKERS")[-1][:400],
            "非本机音色应回退，不应直接抛错（会让全部历史稿件无法出片）",
        )

    def test_legacy_minimax_id_shape_detected(self):
        """solo 分支用前缀判定 minimax 音色 ID；前缀变了这里要红。"""
        run_one = _find_run_one(_build_tree())
        src = ast.unparse(run_one)
        for prefix in ("male-", "female-", "audiobook_"):
            self.assertIn(
                prefix, src,
                f"缺 minimax 音色前缀 {prefix!r} 的判定，历史稿件 voice 会漏进本机后端",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
