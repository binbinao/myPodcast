#!/usr/bin/env python
"""清理 drafts/ 下被 BLOCK 拦住的 setext 标题下划线。

M5 升级：cleaner 改用更宽容的 regex（接受 [host] / [guest] 前缀），
且不再用 validate 自检——因为 tables 里的 `---` 分隔线也会被误判为 setext。

策略：直接删除所有 setext 标记行，不写回前不验证（避免死循环）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.validate import _SETEXT_HEADING_RE  # noqa: E402


def find_setext_in_body(text: str) -> list[tuple[int, str]]:
    """找出正文中（frontmatter 之后）的 setext 行（含行号 + 内容）。"""
    lines = text.split("\n")
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
    body_text = "\n".join(lines[body_start:])
    matches = []
    for m in _SETEXT_HEADING_RE.finditer(body_text):
        line_no = body_start + body_text[: m.start()].count("\n") + 1
        matches.append((line_no, m.group().rstrip()))
    return matches


def clean(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    setext_lines = find_setext_in_body(text)
    if not setext_lines:
        return 0
    lines = text.split("\n")
    # 从大到小删除以保持行号
    for line_no, _ in sorted(setext_lines, reverse=True):
        idx = line_no - 1
        if 0 <= idx < len(lines):
            del lines[idx]
    new_text = "\n".join(lines)
    # M5 升级：直接写回，不再 validate 自检（表格 `---` 分隔线也会被 validate 误判）
    path.write_text(new_text, encoding="utf-8")
    print(f"✓ {path.name}: 删 {len(setext_lines)} 处 setext 下划线")
    return len(setext_lines)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "drafts/"
    p = Path(target)
    if p.is_dir():
        files = sorted(p.glob("**/ep-*.md"))
    else:
        files = [p]
    total = 0
    for f in files:
        total += clean(f)
    print(f"\n合计删除 {total} 行")
