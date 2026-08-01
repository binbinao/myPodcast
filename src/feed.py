"""发布件：每集 shownotes + 全局 RSS / 节目站 index.html。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

MANIFEST = "manifest.json"


def _manifest_path(out_dir: Path) -> Path:
    return Path(out_dir) / MANIFEST


def load_manifest(out_dir: Path) -> dict[str, Any]:
    p = _manifest_path(out_dir)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"episodes": []}


def save_manifest(out_dir: Path, data: dict[str, Any]) -> None:
    _manifest_path(out_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_shownotes(ep_dir: Path, meta: dict[str, Any], segments: list[dict[str, str]], duration: int) -> Path:
    ep_dir = Path(ep_dir)
    lines = [
        f"# {meta.get('title', '未命名')}",
        "",
        f"> {meta.get('description', '')}",
        "",
        f"- 主播：{meta.get('host', '小搭')}"
        + (f" / 嘉宾：{meta.get('guest', '')}" if meta.get("guest") else ""),
        f"- 时长：{duration // 60} 分 {duration % 60} 秒",
        f"- 日期：{meta.get('date', date.today().isoformat())}",
        "",
        "## 正文",
        "",
    ]
    for seg in segments:
        lines.append(f"**[{seg['role']}]** {seg['text']}")
        lines.append("")
    path = ep_dir / "shownotes.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def register_episode(out_dir: Path, meta: dict[str, Any], slug: str, duration: int, size: int) -> None:
    data = load_manifest(out_dir)
    eps = data["episodes"]
    entry = {
        "slug": slug,
        "title": meta.get("title", slug),
        "subtitle": meta.get("subtitle", ""),
        "description": meta.get("description", ""),
        "date": meta.get("date", date.today().isoformat()),
        "duration": duration,
        "size": size,
        "url": f"{slug}/episode.mp3",
        "series": meta.get("series", ""),
        "episode": meta.get("episode", ""),
        "total": meta.get("total", ""),
    }
    eps = [e for e in eps if e["slug"] != slug]
    eps.insert(0, entry)
    data["episodes"] = eps
    save_manifest(out_dir, data)


def build_feed(out_dir: Path, podcast: dict[str, Any]) -> Path:
    data = load_manifest(out_dir)
    base = podcast.get("website", "https://example.com").rstrip("/")
    items = []
    for e in data["episodes"]:
        items.append(
            "    <item>\n"
            f"      <title>{escape(e['title'])}</title>\n"
            f"      <description>{escape(e['description'])}</description>\n"
            f"      <pubDate>{e['date']}</pubDate>\n"
            + (f"      <itunes:episode>{e['episode']}</itunes:episode>\n" if e.get("episode") else "")
            + (f"      <itunes:season>1</itunes:season>\n" if e.get("series") else "")
            + f'      <enclosure url="{base}/{e["url"]}" type="audio/mpeg" length="{e["size"]}"/>\n'
            f"      <itunes:duration>{e['duration']}</itunes:duration>\n"
            "    </item>"
        )
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{escape(podcast.get('title', 'Podcast'))}</title>
    <description>{escape(podcast.get('description', ''))}</description>
    <link>{base}</link>
    <language>{podcast.get('language', 'zh-CN')}</language>
    <itunes:author>{escape(podcast.get('author', ''))}</itunes:author>
{chr(10).join(items)}
  </channel>
</rss>
"""
    path = Path(out_dir) / "feed.xml"
    path.write_text(rss, encoding="utf-8")
    return path


def build_index(out_dir: Path, podcast: dict[str, Any]) -> Path:
    data = load_manifest(out_dir)
    base = podcast.get("website", "").rstrip("/")
    cards = []
    for e in data["episodes"]:
        audio_src = f"{base}/{e['url']}" if base else e["url"]
        cards.append(
            f'<div class="ep">\n'
            f'  <h2>{escape(e["title"])}</h2>\n'
            f'  <p class="meta">{e["date"]} · {e["duration"] // 60}分{e["duration"] % 60}秒</p>\n'
            f'  <p>{escape(e["description"])}</p>\n'
            f'  <audio controls src="{audio_src}"></audio>\n'
            f'  <a href="{e["slug"]}/shownotes.md">Shownotes</a>\n'
            f"</div>"
        )
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{escape(podcast.get('title', 'Podcast'))}</title>
<style>body{{font-family:system-ui;max-width:720px;margin:2rem auto;padding:0 1rem;color:#222}}
.ep{{border-top:1px solid #eee;padding:1.2rem 0}}.meta{{color:#888;font-size:.85rem}}
audio{{width:100%}}</style></head>
<body><h1>{escape(podcast.get('title', 'Podcast'))}</h1>
<p>{escape(podcast.get('description', ''))}</p>
{chr(10).join(cards)}
</body></html>"""
    path = Path(out_dir) / "index.html"
    path.write_text(html, encoding="utf-8")
    return path
