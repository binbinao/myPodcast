"""src.llm 单元测试（unittest.TestCase 风格，零依赖）。

LLM 链路兜底：heuristic_clean 应当把 LLM 输出的常见 markdown 残留
去干净，且保留 [角色] 标签不动；resolve_api_key 三级兜底。
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.llm import heuristic_clean, resolve_api_key


class TestHeuristicClean(unittest.TestCase):
    """heuristic_clean 输入 markdown 残留，输出干净脚本。"""

    def test_strips_bold(self):
        body = "[host] 这是 **加粗** 残留"
        out = heuristic_clean(body)
        self.assertNotIn("**", out)
        self.assertIn("[host]", out)
        self.assertIn("加粗", out)

    def test_strips_inline_code(self):
        body = "[host] 这里有 `inline code` 残留"
        out = heuristic_clean(body)
        self.assertNotIn("`", out)

    def test_strips_heading(self):
        body = "[host] ## 这是 H2 标题残留"
        out = heuristic_clean(body)
        # 标题 # 应被剥掉
        self.assertNotIn("# ", out)

    def test_strips_unordered_list(self):
        body = "- 项目 A\n- 项目 B\n[host] 然后说话"
        out = heuristic_clean(body)
        # 列表前缀 "- " 应被剥掉（行首才有效果）
        self.assertNotIn("- ", out)

    def test_preserves_role_tag(self):
        body = "[guest] 这是嘉宾说话\n[host] 这是主播说话"
        out = heuristic_clean(body)
        self.assertIn("[guest]", out)
        self.assertIn("[host]", out)

    def test_strips_emoji_when_simple(self):
        """heuristic 不会自动去 emoji（它不识别 emoji 字符类是字符串替换），
        但不应抛。"""
        body = "[host] 有 emoji 🎉"
        out = heuristic_clean(body)
        # heuristic 不去 emoji，emoji 应当原样保留
        self.assertIn("🎉", out)


class TestResolveApiKey(unittest.TestCase):
    """resolve_api_key 三级兜底：cfg > env。"""

    def test_cfg_first(self):
        cfg = {"api_key": "from-cfg"}
        env_value = "from-env"
        # 显式 cfg 覆盖 env
        old = ""
        import os
        for k in ("LLM_API_KEY", "MINIMAX_API_KEY", "OPENAI_API_KEY"):
            old = os.environ.get(k, "")
            os.environ[k] = env_value
        try:
            self.assertEqual(resolve_api_key(cfg), "from-cfg")
        finally:
            for k in ("LLM_API_KEY", "MINIMAX_API_KEY", "OPENAI_API_KEY"):
                if k in os.environ:
                    del os.environ[k]

    def test_empty_cfg_falls_back_to_env(self):
        cfg = {"api_key": ""}
        import os
        os.environ["LLM_API_KEY"] = "env-lm"
        try:
            self.assertEqual(resolve_api_key(cfg), "env-lm")
        finally:
            del os.environ["LLM_API_KEY"]

    def test_no_key_returns_empty(self):
        cfg = {"api_key": ""}
        import os
        for k in ("LLM_API_KEY", "MINIMAX_API_KEY", "OPENAI_API_KEY"):
            os.environ.pop(k, None)
        self.assertEqual(resolve_api_key(cfg), "")

    def test_placeholder_not_treated_as_key(self):
        """`${...}` 占位符被视为空，跳到 env 兜底。"""
        cfg = {"api_key": "${...}"}
        import os
        os.environ["MINIMAX_API_KEY"] = "env-mm"
        try:
            self.assertEqual(resolve_api_key(cfg), "env-mm")
        finally:
            del os.environ["MINIMAX_API_KEY"]


class TestLocalEndpoint(unittest.TestCase):
    """本机端点判定：本机端点不需要 api_key（离线备选路径仍保留）。"""

    def test_loopback_variants(self):
        from src.llm import _is_local_endpoint
        self.assertTrue(_is_local_endpoint("http://127.0.0.1:11434/v1"))
        self.assertTrue(_is_local_endpoint("http://localhost:11434/v1"))

    def test_remote_is_not_local(self):
        from src.llm import _is_local_endpoint
        self.assertFalse(_is_local_endpoint("https://api.scnet.cn/api/llm/v1"))
        self.assertFalse(_is_local_endpoint("https://api.minimaxi.com/v1"))


class TestApiKeyEnv(unittest.TestCase):
    """api_key_env 显式声明时只认该列表 —— 防止静默用错 provider 的 key。"""

    def setUp(self):
        import os
        self.os = os
        self.saved = {k: os.environ.get(k) for k in
                      ("SCNET_API_KEY", "MINIMAX_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")}
        for k in self.saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.saved.items():
            self.os.environ.pop(k, None)
            if v is not None:
                self.os.environ[k] = v

    def test_declared_env_wins_over_default_order(self):
        from src.llm import resolve_api_key
        # MINIMAX 已欠费，SCNET 才是要用的：即使两者都在，也必须取 SCNET
        self.os.environ["MINIMAX_API_KEY"] = "dead-minimax"
        self.os.environ["SCNET_API_KEY"] = "good-scnet"
        cfg = {"api_key": "", "api_key_env": ["SCNET_API_KEY"]}
        self.assertEqual(resolve_api_key(cfg), "good-scnet")

    def test_declared_env_missing_does_not_fall_back(self):
        """声明了 api_key_env 但该 env 缺失 → 返回空，而不是抓 MINIMAX 的 key。"""
        from src.llm import resolve_api_key
        self.os.environ["MINIMAX_API_KEY"] = "dead-minimax"
        cfg = {"api_key": "", "api_key_env": ["SCNET_API_KEY"]}
        self.assertEqual(resolve_api_key(cfg), "")

    def test_cfg_api_key_still_first(self):
        from src.llm import resolve_api_key
        self.os.environ["SCNET_API_KEY"] = "good-scnet"
        cfg = {"api_key": "explicit", "api_key_env": ["SCNET_API_KEY"]}
        self.assertEqual(resolve_api_key(cfg), "explicit")


class TestModelWhitelist(unittest.TestCase):
    """模型白名单预检：配错名要报出可用清单，而不是裸 404。"""

    FAKE_MODELS = json.dumps({"data": [
        {"id": "DeepSeek-V4.1-Flash"},
        {"id": "DeepSeek-V4-Pro"},
        {"id": "GLM-5.3"},
    ]}).encode()

    def setUp(self):
        import urllib.request as _ur
        from src import llm as _llm
        self.ur, self.llm_mod = _ur, _llm
        self.orig = _ur.urlopen

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return TestModelWhitelist.FAKE_MODELS

        self.FakeResp = FakeResp
        _llm._MODEL_LIST_CACHE.clear()

    def tearDown(self):
        self.ur.urlopen = self.orig
        self.llm_mod._MODEL_LIST_CACHE.clear()

    def test_known_model_passes(self):
        self.ur.urlopen = lambda *a, **kw: self.FakeResp()
        # 大小写不敏感
        self.llm_mod._check_model_available("https://api.example.com/v1", "k", "deepseek-v4.1-flash")

    def test_unknown_model_raises_with_list(self):
        self.ur.urlopen = lambda *a, **kw: self.FakeResp()
        with self.assertRaises(RuntimeError) as cm:
            self.llm_mod._check_model_available("https://api.example.com/v1", "k", "gpt-4o-mini")
        msg = str(cm.exception)
        self.assertIn("gpt-4o-mini", msg)
        self.assertIn("DeepSeek-V4.1-Flash", msg)
        self.assertIn("只能从以下模型选择", msg)

    def test_endpoint_down_skips_precheck(self):
        """/models 不通就跳过预检（让正式调用自己报错），不应抛。"""
        def boom(*a, **kw):
            raise OSError("connection refused")

        self.ur.urlopen = boom
        self.llm_mod._check_model_available("https://api.example.com/v1", "k", "whatever")

    def test_invalid_base_url_skips_precheck(self):
        """base_url 缺失/非绝对 URL 时不能抛 ValueError（曾是回归：urlopen 报
        'unknown url type' 把降级路径炸掉）。"""
        for bad in ("", "/v1", "api.example.com/v1"):
            self.llm_mod._check_model_available(bad, "k", "whatever")


class TestConfigDefaultLlm(unittest.TestCase):
    """钉住写稿 LLM 默认配置：SCNet + DeepSeek-V4.1-Flash + 显式 key env。"""

    def setUp(self):
        import yaml
        self.llm = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["llm"]

    def test_endpoint_and_model(self):
        self.assertEqual(self.llm["base_url"], "https://api.scnet.cn/api/llm/v1")
        self.assertEqual(self.llm["model"], "DeepSeek-V4.1-Flash")

    def test_key_comes_from_explicit_env(self):
        """不能把 key 提交进仓库；且必须显式指定 env，避免抓到已欠费的 MINIMAX_API_KEY。"""
        self.assertEqual(self.llm.get("api_key", ""), "")
        self.assertEqual(self.llm.get("api_key_env"), ["SCNET_API_KEY"])

    def test_budget_covers_reasoning(self):
        """V4.1-Flash 的 reasoning 与正文共享 max_tokens，预算不足会正文为空。"""
        self.assertGreaterEqual(int(self.llm["max_tokens"]), 12000)


if __name__ == "__main__":
    unittest.main()
