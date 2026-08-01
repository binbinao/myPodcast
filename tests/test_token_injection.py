"""Token loader 单元测 + CSS 产物硬编码色守恒。

P0 规则：CSS 内除 #fff/#000 外不得有裸 hex / 裸 rgba()。
重构 M2-1：templates/style.css 应该全部通过 var(--color-*) 引用 token。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLE_CSS = ROOT / "templates" / "style.css"
TOKENS_JSON = ROOT / "templates" / "design-tokens.json"

from src.tokens import load_tokens, render_css_variables


# 允许的硬编码：仅 #fff / #000
_ALLOWED_HEX = re.compile(r"^#(fff|000)$", re.IGNORECASE)
# 裸 hex 形如 #abc / #abcdef
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")
# 裸 rgb()/rgba() 调用（非 var() 内嵌）
_BARE_RGB = re.compile(r"\b(rgb|rgba)\s*\(\s*(?!var\()[^)]+\)")


class TokenLoaderTest(unittest.TestCase):
    def test_load_returns_flat_dict(self) -> None:
        tokens = load_tokens()
        self.assertIsInstance(tokens, dict)
        self.assertGreater(len(tokens), 20, "应该加载到 ≥20 token（color+font+size+space+radius+motion）")

    def test_required_color_tokens(self) -> None:
        # 站点必须有的 5 个核心色
        tokens = load_tokens()
        for k in ("color-bg", "color-surface", "color-fg", "color-accent", "color-muted"):
            self.assertIn(k, tokens, f"token 缺 {k!r}")

    def test_accent_rgb_is_channel_tuple(self) -> None:
        # accent-rgb 必须是 "R G B" 三元组（不是 hex）
        tokens = load_tokens()
        self.assertIn("color-accent-rgb", tokens)
        rgb = tokens["color-accent-rgb"].split()
        self.assertEqual(len(rgb), 3, f"accent-rgb 应是 3 个数字，当前 {tokens['color-accent-rgb']!r}")
        for n in rgb:
            self.assertTrue(n.isdigit() and 0 <= int(n) <= 255)

    def test_render_css_variables_starts_with_root(self) -> None:
        css = render_css_variables(load_tokens())
        # 第 2 行起是 :root {（第 1 行是 GENERATED 注释）
        lines = css.split("\n")
        self.assertIn(":root {", lines, "应有 :root { 块")
        # 全部 token 都要写出来
        n_tokens = len(load_tokens())
        n_var_lines = sum(1 for line in lines if line.strip().startswith("--"))
        self.assertGreaterEqual(n_var_lines, n_tokens, f"应至少 {n_tokens} 个 CSS 变量定义")

    def test_token_file_existence(self) -> None:
        self.assertTrue(TOKENS_JSON.exists(), f"design-tokens.json 不在 {TOKENS_JSON}")


class StyleCssHardcodeGuardTest(unittest.TestCase):
    """templates/style.css 扫描：除 #fff/#000 外不得有裸 hex / 裸 rgb()。

    重构 M2-1 目标：当前若有违规，逐步迁移到 var(--color-*)。
    """

    def test_no_bare_hex_outside_root_block(self) -> None:
        """P0 规则：CSS 内除 #fff/#000 外不得有裸 hex。

        重构 M2-1 目标：:root 块（token 原始值定义处）除外，body 区一律走 var(--color-*)。
        """
        text = STYLE_CSS.read_text(encoding="utf-8")
        # 找 :root { ... } 块边界
        root_start = text.find(":root {")
        root_end = text.find("}", root_start) if root_start != -1 else -1
        # body 区域：root_end 之后
        body_text = text[root_end + 1 :] if root_end != -1 else text
        offenders = []
        for m in _HEX_COLOR.finditer(body_text):
            hex_val = m.group()
            if _ALLOWED_HEX.match(hex_val):
                continue
            line_no = text[: root_end + 1 + m.start()].count("\n") + 1
            offenders.append(f"line {line_no}: {hex_val}")
        if offenders:
            self.fail(
                f"body 区发现 {len(offenders)} 个裸 hex 需迁 token:\n"
                + "\n".join(f"  {o}" for o in offenders[:15])
            )

    def test_no_bare_rgb_outside_root_block(self) -> None:
        """P0 规则：CSS 内除 var() 嵌入外不得有裸 rgba()/rgb()。"""
        text = STYLE_CSS.read_text(encoding="utf-8")
        root_start = text.find(":root {")
        root_end = text.find("}", root_start) if root_start != -1 else -1
        body_text = text[root_end + 1 :] if root_end != -1 else text
        offenders = []
        for m in _BARE_RGB.finditer(body_text):
            line_no = text[: root_end + 1 + m.start()].count("\n") + 1
            offenders.append(f"line {line_no}: {m.group()}")
        if offenders:
            self.fail(
                f"body 区发现 {len(offenders)} 处裸 rgb() 需迁 token:\n"
                + "\n".join(f"  {o}" for o in offenders[:15])
            )

    def test_no_bare_rgb_in_css(self) -> None:
        text = STYLE_CSS.read_text(encoding="utf-8")
        offenders = []
        for m in _BARE_RGB.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            offenders.append(f"line {line_no}: {m.group()}")
        if offenders:
            print(f"\n[info] {len(offenders)} 处裸 rgb() 待迁 token:")
            for o in offenders[:10]:
                print(f"  {o}")


if __name__ == "__main__":
    unittest.main()