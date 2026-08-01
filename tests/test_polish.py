"""src.polish 单元测试（unittest.TestCase 风格，零依赖）。

LLM 链路兜底：heuristic_clean 应当把 LLM 输出的常见 markdown 残留
去干净，且保留 [角色] 标签不动。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.polish import heuristic_clean, resolve_api_key


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


if __name__ == "__main__":
    unittest.main()
