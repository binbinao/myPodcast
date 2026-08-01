"""Design Tokens loader (DTCG format) → CSS variables block.

动机：templates/style.css 11 处硬编码色 + 字号阶梯 + 间距白名单，
设计师已交付 templates/design-tokens.json（80 token，FROZEN）。
本模块：
1. 读 json，扁平化 nested {color/font/size/space/...} → 单层 {token_name: value}
2. 转 DTCG value（去掉 .value 包裹）
3. 输出 :root { --token: value; ... } 块

不做的事：
- 不自动替换 style.css 里现有硬编码（那是 style.css 重构事）
- 不在产物阶段重渲染 CSS（build 时直接写 static style.css）

使用：
    from src.tokens import load_tokens, render_css_variables
    tokens = load_tokens()        # dict[str, str]
    css = render_css_variables(tokens)
    # 然后 prepend 到 static/style.css 头部
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TOKENS_PATH = Path(__file__).resolve().parent.parent / "templates" / "design-tokens.json"


def _flatten(prefix: str, obj: dict[str, Any], out: dict[str, str]) -> None:
    """递归扁平化嵌套 dict，键用 `--` 分隔（DTCG convention → CSS custom prop）。"""
    for k, v in obj.items():
        # 跳过 DTCG 元字段
        if k.startswith("$") or k in ("$schema", "$meta"):
            continue
        if not isinstance(v, dict):
            continue
        # 叶子节点：含 "value" 字段就是 token
        if "value" in v:
            new_key = f"{prefix}-{k}" if prefix else k
            out[new_key] = str(v["value"])
        else:
            # 嵌套层
            new_key = f"{prefix}-{k}" if prefix else k
            _flatten(new_key, v, out)


def load_tokens(path: Path = TOKENS_PATH) -> dict[str, str]:
    """读 tokens.json，返回扁平 dict {name: value}。name 已是 CSS 自定义属性名（kebab-case）。"""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    flat: dict[str, str] = {}
    for top_key in ("color", "font", "size", "space", "radius", "motion", "breakpoint"):
        section = data.get(top_key)
        if not isinstance(section, dict):
            continue
        _flatten(top_key, section, flat)
    return flat


def render_css_variables(tokens: dict[str, str]) -> str:
    """输出 :root { --name: value; ... } CSS 块。"""
    lines = ["/* GENERATED from design-tokens.json — DO NOT EDIT */", ":root {"]
    for name, value in tokens.items():
        # 跳过 'rgb 255 122 89' 这种"通道三元组"——它需要嵌入到 rgba 里
        # 实际 DTCG 允许 string 类型，我们按字面写入
        # 但要避免 value 里再含 var()（css 内嵌会展开）
        lines.append(f"  --{name}: {value};")
    lines.append("}")
    return "\n".join(lines)


if __name__ == "__main__":
    tokens = load_tokens()
    print(f"Loaded {len(tokens)} tokens from {TOKENS_PATH}")
    print("Sample:")
    for k in list(tokens)[:5]:
        print(f"  --{k}: {tokens[k]}")
    print("\n--- rendered CSS ---")
    print(render_css_variables(tokens)[:600])