#!/usr/bin/env python
"""清理 drafts/ 下被 BLOCK 拦住的 setext 标题下划线。

重构后背景：validate.py 新增 setext BLOCK（防止 TTS 念 '等号'/'减号'），
历史 drafts/2026-03-09-ai-infra-redefined/ 有 6 个 ep 在正文里残留了
孤立的 === / --- 行（实际是表头分隔误用）。

策略：
1. 读 frontmatter 范围（首两行 `---` 之间）—— 不动
2. 之后的正文里，匹配 `^[=\-]{3,}\s*$`（escape 写 raw string r`^[=\-]{3,}\s*$`）且**前面一行不是空行也不是 markdown 控制
   字符**，直接删除该行（不留空白）
3. 只对 BLOCK 失败的 draft 操作（白名单 = BLOCK 校验报告里失败的 ep）

依赖：src/validate.py（运行时 import）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.validate import _BLOCK_PREFIX, _SETEXT_HEADING_RE  # noqa: E402


def find_setext_in_body(text: str) -> list[tuple[int, str]]:
    """找出正文中（frontmatter 之后）的 setext 行（含行号 + 内容）。"""
    # 找 frontmatter 边界：首段连续 --- ... ---
    lines = text.split("\n")
    # 跳过 frontmatter：以 `---` 开头，找下一个 `---` 结束的下一行
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
    # 跑一次 validate 看 BLOCK 是否消失（手动分离 frontmatter）
    import re as _re  # noqa: PLC0415
    fm_match = _re.match(r"^---\n.*?\n---\n(.*)$", new_text, flags=_re.S)
    body_text = fm_match.group(1) if fm_match else new_text
    meta = {}
    if fm_match:
        fm_text = new_text[: fm_match.start(1)]
        for line in fm_text.split("\n"):
            if ":" in line and not line.startswith("---"):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    from src.validate import validate_script  # noqa: E402, PLC0415

    warns = validate_script(meta, body_text)
    blocks = [w for w in warns if w.startswith(_BLOCK_PREFIX)]
    if blocks:
        print(f"✗ {path.name}: 仍有 BLOCK → {blocks}")
        return 0  # 不写回，留待人工
    path.write_text(new_text, encoding="utf-8")
    print(f"✓ {path.name}: 删 {len(setext_lines)} 处 setext 下划线")
    return len(setext_lines)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "drafts/2026-03-09-ai-infra-redefined"
    p = Path(target)
    if p.is_dir():
        files = sorted(p.glob("ep-*.md"))
    else:
        files = [p]
    total = 0
    for f in files:
        total += clean(f)
    print(f"\n合计删除 {total} 行")