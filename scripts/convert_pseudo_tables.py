#!/usr/bin/env python3
"""把 draft 里残留的伪表格（缺 `|` 但有 ---{3,} 分隔线 + 双/多列空格分隔）转成散文。

适用：drafts/2026-03-09-ai-infra-redefined/ep-02 / ep-07 / ep-14 / ep-15。
跑后这 4 集不会再触发 validate._SETEXT_HEADING_RE 的 BLOCK 拦截。

策略：
1. 正文中找形如 `---{3,}` 的整行作锚点
2. 上一行 = 表头（无 `---` 仅有空格分隔的列名）
3. 接下来 N 行 = 数据行（首列=维度名, 后续列=各场景值）
4. 拼成朗读友好的散文："在<维度名>上，<场景1>是<值1>，<场景2>是<值2>。"
5. 整段替换：表头 + 分隔线 + 数据行 → 单行散文

幂等：跑两次第二次不会重复替换（因为 --- 行已被散文替换）
"""
from __future__ import annotations
import re
from pathlib import Path

PROJECT = Path(__file__).parent.parent
DRAFTS = PROJECT / "drafts/2026-03-09-ai-infra-redefined"

# 仅处理这 4 个目标文件
TARGETS = [
    "ep-02.md",
    "ep-07.md",
    "ep-14.md",
    "ep-15.md",
]

# 伪表格锚点：连续 3+ 个 `-` 整行（不带 [role] 前缀）
_PSEUDO_SEP_RE = re.compile(r"^---{3,}\s*$")


def _split_columns(line: str) -> list[str]:
    """按 ≥2 连续空格切列。"""
    parts = re.split(r"\s{2,}", line.strip())
    return [p.strip() for p in parts if p.strip()]


def _convert_table_block(lines: list[str], sep_idx: int) -> tuple[str, int] | None:
    """lines[sep_idx] 是 ---{3,} 行。返回 (prose_replacement, lines_consumed)。

    lines_consumed = 表头(1) + 分隔(1) + 数据行(N)
    若锚点上下不构成伪表格（缺表头/数据），返回 None。
    """
    if sep_idx < 1:
        return None
    header_line = lines[sep_idx - 1]
    # 表头必须有 ≥2 个非空列且不带 `---`/`==`
    if not header_line.strip() or "---" in header_line or "===" in header_line:
        return None
    cols = _split_columns(header_line)
    if len(cols) < 2:
        return None
    # 数据行：sep_idx 之后直到遇 [host] / 空行 / frontmatter
    data: list[list[str]] = []
    j = sep_idx + 1
    while j < len(lines):
        line = lines[j]
        stripped = line.strip()
        if not stripped:
            break
        if stripped.startswith("[host]") or stripped.startswith("[guest]"):
            break
        # 必须是 ≥2 列的空格分隔行
        row_cols = _split_columns(line)
        if len(row_cols) < 2:
            break
        data.append(row_cols)
        j += 1
    if not data:
        return None
    # 拼散文：维度名 = data[*][0]; 各列 = data[*][1:]
    col_names = cols[1:]  # 第 0 列是"对比维度"标签,实际场景从 cols[1] 开始
    sentences: list[str] = []
    for row in data:
        dim = row[0]
        values = row[1:]
        parts = [f"{col_names[k]}侧重{values[k]}" for k in range(min(len(col_names), len(values)))]
        if len(parts) == 2:
            sentences.append(f"{dim}方面，{parts[0]}，{parts[1]}。")
        else:
            # 3+ 列用顿号连接
            sentences.append(f"{dim}方面，{','.join(parts[:-1])}和{parts[-1]}。")
    prose = "[host] " + "".join(sentences)
    consumed = (sep_idx - 1, j)  # 替换 [表头, 数据末尾]
    return prose, consumed


def convert_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    # 不动 frontmatter
    m = re.match(r"^(---\n.*?\n---\n)(.*)$", text, flags=re.S)
    if not m:
        return 0
    fm, body = m.group(1), m.group(2)
    body_lines = body.splitlines(keepends=False)
    # 从尾到头替换（避免索引偏移）
    out_lines = list(body_lines)
    converted = 0
    i = 0
    while i < len(out_lines):
        if _PSEUDO_SEP_RE.match(out_lines[i].strip()):
            result = _convert_table_block(out_lines, i)
            if result:
                prose, (start, end) = result
                # 替换 [start, end) 为 prose
                out_lines[start:end] = [prose]
                converted += 1
                i = start + 1  # 跳过已替换的散文
                continue
        i += 1
    if converted == 0:
        return 0
    new_body = "\n".join(out_lines) + "\n"
    path.write_text(fm + new_body, encoding="utf-8")
    return converted


def main() -> None:
    total = 0
    for name in TARGETS:
        p = DRAFTS / name
        if not p.exists():
            print(f"  - {name}: not found, skip")
            continue
        n = convert_file(p)
        total += n
        print(f"  ✓ {name}: 转换 {n} 处伪表格" if n else f"  · {name}: 无伪表格，跳过")
    print(f"\n共转换 {total} 处")


if __name__ == "__main__":
    main()