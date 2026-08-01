"""CSS content 守卫：禁止 `content:` 携带非空字面量。

项目设计纪律（重构路线图 P0-D）：所有 UI 图标必须来自 src/feed.py::_ICON_LIB，
CSS `content:` 仅允许空串（`content: ""` 或 `content: none`）。

任何对 `::before / ::after` 注入字符字面量（包括 emoji 和 ▶ 等装饰符号）
都会绕过图标体系导致跨平台渲染不一致，必须在 CI 拦截。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CSS_GLOB = list((ROOT / "templates").rglob("*.css"))

# 匹配 `content: "<非空内容>"`
_CONTENT_NONEMPTY_RE = re.compile(
    r"""content\s*:\s*['"]([^'"]+)['"]""",
    flags=re.MULTILINE,
)


class CssContentAudit(unittest.TestCase):
    """逐 CSS 文件扫：禁止 content: '<非空字面>'。"""

    def test_no_nonempty_content(self) -> None:
        offenders: list[tuple[Path, str]] = []
        for css_path in CSS_GLOB:
            text = css_path.read_text(encoding="utf-8")
            for match in _CONTENT_NONEMPTY_RE.finditer(text):
                offenders.append((css_path.relative_to(ROOT), match.group(0).strip()))
        if offenders:
            detail = "\n".join(f"  {p}: {m}" for p, m in offenders)
            self.fail(
                "检测到 CSS `content:` 携带非空字面量。图标必须用 SVG "
                "(src/feed.py::_ICON_LIB)，禁止通过 ::before 注入字符。\n"
                + detail
            )


if __name__ == "__main__":
    unittest.main()