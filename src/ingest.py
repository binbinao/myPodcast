"""解析播客脚本：frontmatter 元数据 + [角色] 标签分段。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .naming import ascii_slug, chinese_to_ascii

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
TAG_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


def parse_script(text: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """返回 (metadata, segments)。segments: [{role, text}]。"""
    meta: dict[str, Any] = {}
    body = text
    m = FRONTMATTER_RE.match(text)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        body = m.group(2)

    segments: list[dict[str, str]] = []
    current_role: str | None = None
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        tag = TAG_RE.match(line)
        if tag:
            current_role = tag.group(1).strip().lower()
            content = tag.group(2).strip()
        else:
            content = line.strip()
            if current_role is None:
                current_role = "default"
        if content:
            segments.append({"role": current_role, "text": content})
    return meta, segments


def load_episode(path: str | Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    return parse_script(Path(path).read_text(encoding="utf-8"))


# 兼容旧 import：返回 ASCII kebab-case slug（不再保留中文）
def slugify(title: str) -> str:
    """ASCII kebab-case slug。中文标题会转拼音（无 pypinyin 时降级）。"""
    return chinese_to_ascii(title)
