"""发布件：每集 shownotes + 全局 RSS / 节目站 index.html。

manifest.json 记录每集首次生成的实际日期（之后 build 不覆盖），作为 RSS pubDate 与
节目站显示日期使用；build_index 按 series 聚合 + 5 sections 渲染（暗色落地页风格）。
"""
from __future__ import annotations

# --- SVG 图标库（P0 规则：emoji 不能作图标，统一 SVG，统一描边，统一 currentColor）---
# Lucide 风格 24×24 stroke 图标。HTML 用 {mic} / {music} / {sparkle} / {hamburger} / {play}
# 文本内嵌即可；CSS 用 width/height 控制大小，color/currentColor 控制着色。
_ICON_LIB: dict[str, str] = {
    "mic": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<rect x="9" y="2" width="6" height="12" rx="3"/>'
        '<path d="M5 10v2a7 7 0 0 0 14 0v-2"/>'
        '<line x1="12" y1="19" x2="12" y2="22"/>'
        '</svg>'
    ),
    "music": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M9 18V5l12-2v13"/>'
        '<circle cx="6" cy="18" r="3"/>'
        '<circle cx="18" cy="16" r="3"/>'
        '</svg>'
    ),
    "sparkle": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>'
        '</svg>'
    ),
    "hamburger": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<line x1="4" y1="7" x2="20" y2="7"/>'
        '<line x1="4" y1="12" x2="20" y2="12"/>'
        '<line x1="4" y1="17" x2="20" y2="17"/>'
        '</svg>'
    ),
    "play": (
        # 纯填充三角（去掉 stroke，避免双重描边的"幽灵边"）。
        # stroke 留 fallback：未来若想做 line-only 风格可换 stroke="currentColor" stroke-width="2"。
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
        'viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true">'
        '<polygon points="7 5 19 12 7 19 7 5"/>'
        '</svg>'
    ),
    "rss": (
        # RSS 广播 logo: 三层弧 + 中心圆点
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M4 11a9 9 0 0 1 9 9"/>'
        '<path d="M4 4a16 16 0 0 1 16 16"/>'
        '<circle cx="5" cy="19" r="1.5" fill="currentColor"/>'
        '</svg>'
    ),
    "podcast_icon": (
        # 播客/耳机形 logo（Apple Podcasts / 小宇宙等订阅入口用）
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M3 14a9 9 0 0 1 18 0v3a3 3 0 0 1-3 3h-1v-7h4"/>'
        '<path d="M3 14v3a3 3 0 0 0 3 3h1v-7H3"/>'
        '</svg>'
    ),
}

import json
import re
from datetime import date
from html import escape as _html_escape_text  # only used inside element bodies (no attrs)
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as escape

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
    """写 shownotes.md。

    M2-4 结构化（之前是裸文本）：
    1. 头加 frontmatter（title/series/date/audio/duration）— 机器可读
    2. 章节锚点：从 segments 抽带"第 X 章"/Chapter 作 `<a id="...">` 锚
    3. 末尾加订阅小节
    """
    ep_dir = Path(ep_dir)
    ep_index = int(meta.get("episode", 1) or 1)
    slug = meta.get("series_slug", meta.get("slug", ""))
    audio_url = f"series/{slug}/ep-{ep_index:02d}/episode.mp3"
    series_title = meta.get("series", "")
    title = meta.get("title", "未命名")
    desc = meta.get("description", "")
    host = meta.get("host", "小搭")
    guest = meta.get("guest", "")
    date_str = meta.get("date", date.today().isoformat())

    lines: list[str] = [
        "---",
        f'title: "{title}"',
        f'series: "{series_title}"',
        f"date: {date_str}",
        f"duration: {duration}",
        f"audio: {audio_url}",
        "---",
        "",
        f"# {title}",
        "",
        f"> {desc}" if desc else f"> {series_title} · 第 {ep_index} 集",
        "",
        f"听：{audio_url} · 时长 {duration // 60} 分 {duration % 60} 秒 · {date_str}"
        + (f" · 嘉宾：{guest}" if guest else f" · 主播：{host}"),
        "",
    ]

    # 章节锚点：识别"第 X 章"/Chapter 作 H2 锚
    chapter_idx = 0
    has_chapter = False
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        is_chapter = (
            (text.startswith("第") and "章" in text[:8])
            or text.lower().startswith("chapter ")
        )
        if is_chapter:
            chapter_idx += 1
            has_chapter = True
            anchor = f"ep-{ep_index:02d}-ch-{chapter_idx}"
            lines.append(f'<a id="{anchor}"></a>')
            lines.append(f"## 章节 {chapter_idx}：{text}")
            lines.append("")

    if has_chapter:
        lines.append("## 完整正文")
        lines.append("")

    for seg in segments:
        lines.append(f"**[{seg['role']}]** {seg['text']}")
        lines.append("")

    # 订阅小节
    lines.extend([
        "## 订阅",
        "",
        "- [RSS / Atom](https://binbinao.github.io/myPodcast/feed.xml)",
        "- 在 [Apple Podcasts](https://podcasts.apple.com/)、[小宇宙](https://www.xiaoyuzhoufm.com/) 等客户端粘贴 RSS 链接",
        "",
    ])

    path = ep_dir / "shownotes.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _hash_source(source_rel: str) -> str | None:
    """从 draft frontmatter 的 source: 字段读 raw 文章并算 sha256。无 source 返回 None。"""
    if not source_rel:
        return None
    p = Path(source_rel)
    if not p.exists():
        return None
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def register_episode(out_dir: Path, meta: dict[str, Any], slug: str, duration: int, size: int) -> None:
    """注册一集到 manifest。已存在则保留原 date（首次 build 写入的日期）。

    slug = series_slug（用于构建 output/series/<slug>/ep-XX/episode.mp3 URL）。
    """
    data = load_manifest(out_dir)
    eps = data["episodes"]
    ep_index = int(meta.get("episode", 1) or 1)
    series = meta.get("series", "")
    # 唯一键：series_slug + ep-XX（同一系列不同集各自独立）
    key = f"{slug}::ep-{ep_index:02d}"
    old = next((e for e in eps if e.get("_key") == key), None)
    today = date.today().isoformat()
    src_hash = _hash_source(meta.get("source", ""))
    # source hash 变化：raw 文章改了，但音频没重生成 → warn
    if old and src_hash and old.get("source_hash") and old["source_hash"] != src_hash:
        from .log import logger as log
        log.warning(
            f"[warn] raw 文章已变更但音频未更新: {slug} ep-{ep_index:02d} "
            f"hash {old['source_hash']} → {src_hash}"
        )
    entry = {
        "_key": key,
        "slug": slug,
        "ep_index": ep_index,
        "title": meta.get("title", series),
        "subtitle": meta.get("subtitle", ""),
        "description": meta.get("description", ""),
        # 保留旧日期，不被新 build 覆盖
        "date": (old["date"] if old else today),
        "created": (old.get("created") if old else today),
        "updated": today,
        "duration": duration,
        "size": size,
        "url": f"series/{slug}/ep-{ep_index:02d}/episode.mp3",
        "series": series,
        "episode": ep_index,
        "total": meta.get("total", ""),
        "format": meta.get("format", "solo"),
        "chapter": meta.get("chapter", ""),
        "voice": meta.get("voice", ""),
        "source_hash": src_hash,
    }
    eps = [e for e in eps if e.get("_key") != key]
    eps.insert(0, entry)
    data["episodes"] = eps
    save_manifest(out_dir, data)


def build_feed(out_dir: Path, podcast: dict[str, Any]) -> Path:
    data = load_manifest(out_dir)
    base = podcast.get("website", "https://example.com").rstrip("/")
    items = []
    for e in data["episodes"]:
        _enc_url = f"{base}/{e['url']}"
        items.append(
            "    <item>\n"
            f"      <title>{escape(e['title'])}</title>\n"
            f"      <description>{escape(e['description'])}</description>\n"
            f"      <pubDate>{e['date']}</pubDate>\n"
            + (f"      <itunes:episode>{e['episode']}</itunes:episode>\n" if e.get("episode") else "")
            + (f"      <itunes:season>1</itunes:season>\n" if e.get("series") else "")
            + f'      <enclosure url="{_hescape(_enc_url)}" type="audio/mpeg" length="{_hescape(str(e["size"]))}"/>\n'
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


# ---------- helpers ----------

def _hescape(s: Any) -> str:
    """HTML 转义：覆盖 & < > " ' 五个字符。

    `xml.sax.saxutils.escape` 默认不转义引号 → 标题含 `"` 时属性被击穿（PoC 复现）。
    所有用于 HTML 输出（属性值或元素内容）必须走本函数。RSS XML 仍走 `escape()`。
    """
    if s is None:
        return ""
    return _html_escape_text(str(s), quote=True)


def _fmt_dur(d: int) -> str:
    """把秒数格式化为 MM:SS。"""
    m, s = divmod(int(d), 60)
    return f"{m}:{s:02d}"


def _is_body_text(text: str) -> bool:
    """判断一段文字是否像正文开头而非章节标题。"""
    if not text:
        return True
    # 显式章节标记：第X章 / X.X / 目录 / 核心 / 最后 等，直接认为是标题
    if re.match(r"^(第\s*\d+|\d+(?:\.\d+)+\s|目录|核心|最后|未来|文章|文件|六种|四种|十大)", text):
        return False
    # 正文常见特征：含句内/句末标点、长度失控、以时间/承接词开头
    if len(text) > 24:
        return True
    if re.search(r"[，。！？…；]", text):
        return True
    body_prefixes = ("昨天", "今天", "最近", "其实", "回头看", "那么", "这次", "我们", "我", "你")
    return any(text.startswith(p) for p in body_prefixes)


def _display_title(e: dict[str, Any]) -> str:
    """生成干净的页面展示标题，避免把正文句当成章节名。"""
    series = e.get("series") or ""
    chapter = e.get("chapter") or ""
    ep = e.get("episode")
    total = e.get("total")
    # 单集直接返回系列名
    if (not ep and not total) or (total == 1) or (ep == 1 and total == 1):
        return series or e.get("title", "")
    # 章节名干净时：系列名 · 章节名
    if chapter and not _is_body_text(chapter):
        return f"{series} · {chapter}" if series else chapter
    # 否则：系列名 · 第 N 集
    label = f"第 {ep}/{total} 集" if ep and total else (f"第 {ep} 集" if ep else "")
    return f"{series} · {label}" if (series and label) else (series or label or e.get("title", ""))


def _slugify_series(title: str) -> str:
    """兼容保留：中文 → kebab-case（不再保留中文）。实际应由 manifest 的 slug 字段提供。"""
    from .naming import chinese_to_ascii
    return chinese_to_ascii(title)


def _group_by_series(eps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """episodes → 按 series_slug 分组（series 为空/单集也算独立组）。"""
    series_map: dict[str, list[dict[str, Any]]] = {}
    singletons: list[dict[str, Any]] = []
    for e in eps:
        slug = e.get("slug") or ""
        if slug:
            series_map.setdefault(slug, []).append(e)
        else:
            singletons.append(e)
    groups = []
    for series_slug, items in series_map.items():
        items.sort(key=lambda x: int(x.get("ep_index", x.get("episode", 1)) or 1))
        total_dur = sum(x.get("duration", 0) for x in items)
        series_title = items[0].get("series", series_slug)
        groups.append({
            "series": series_title,
            "slug": series_slug,
            "items": items,
            "total_duration": total_dur,
            "count": len(items),
            "latest_date": max(x.get("date", "") for x in items),
            "description": items[0].get("description", "").split("（第")[0].strip(),
        })
    # 单集按日期倒序当独立组
    for e in singletons:
        groups.append({
            "series": e.get("title", e.get("slug", "")),
            "slug": e.get("slug", ""),
            "items": [e],
            "total_duration": e.get("duration", 0),
            "count": 1,
            "latest_date": e.get("date", ""),
            "description": e.get("description", ""),
        })
    # 整体按 latest_date 倒序
    groups.sort(key=lambda g: g["latest_date"], reverse=True)
    return groups


# ---------- main: build_index ----------


def _audio_src(e: dict[str, Any]) -> str:
    # 站点内音频用相对路径：index.html 与各集子目录同处站点根目录，
    # 部署到 gh-pages 子路径(/myPodcast/)也能正确解析，避免占位 example.com 域名 404
    return e["url"]


def _ep_shownotes_src(e: dict[str, Any]) -> str:
    # shownotes 路径：series/<slug>/ep-<NN>/shownotes.md (与 mp3 同 ep_dir)
    slug = e.get("slug", "")
    ep_idx = e.get("episode") or e.get("ep_index") or 1
    return f"series/{slug}/ep-{ep_idx:02d}/shownotes.md"


def _audio_label(e: dict[str, Any]) -> str:
    # aria-label 给听按钮用（"听 第 1 部分"）
    title = (e.get("title") or "").split("·")[-1].strip() or e.get("title", "这一集")
    return title[:24] + ("…" if len(title) > 24 else "")

def _hero_html(
    out_dir: Path,
    title: str,
    tagline: str,
    hero_desc: str,
    cover: str,
    base: str,
    featured: dict | None,
    subscribe_enabled: bool,
    ICON_LIB: dict[str, str],


) -> str:
    """Hero 段：含封面 + featured 播放 CTA + hero_desc 感悟段落。独立函数，<50 行。"""
    cover_abs = (Path(out_dir) / Path(cover).name).resolve() if cover else None
    cover_exists = cover_abs.exists() if cover_abs else False
    desc_html = f'<p class="hero-desc">{_hescape(hero_desc)}</p>' if hero_desc else ''
    if not cover_exists:
        # 兜底：art-gradient + mic icon（hero-art 视觉）
        return f"""<section class="hero">
  <div class="hero-content">
    <h1 class="hero-title">{_hescape(title)}</h1>
    <p class="hero-quote">"{_hescape(tagline)}"</p>
    {desc_html}
    <div class="hero-cta">
      <div id="hero-featured" data-source="manifest">
        <noscript></noscript>
      </div>
      {f'<a class="btn btn-ghost" href="#subscribe">订阅 RSS</a>' if subscribe_enabled else ''}
    </div>
  </div>
  <div class="hero-art" aria-hidden="true">
    <div class="art-gradient"></div>
    <div class="art-glyph">{ICON_LIB["mic"]}</div>
  </div>
</section>"""

    audio_src = _audio_src(featured) if featured else ""
    shownotes_src = _ep_shownotes_src(featured) if featured else ""
    featured_title = _hescape(featured.get("title", "")) if featured else ""
    featured_series = _hescape(featured.get("series", "")) if featured else ""
    featured_dur = _fmt_dur(featured.get("duration", 0)) if featured else ""
    return f"""<section class="hero">
  <div class="hero-media">
    <img class="hero-img" src="{_hescape(cover)}" alt="最新一期封面" width="800" height="800" loading="eager">
  </div>
  <div class="hero-content">
    <h1 class="hero-title">{_hescape(title)}</h1>
    <p class="hero-quote">"{_hescape(tagline)}"</p>
    {desc_html}
    <div class="hero-cta">
      <div id="hero-featured" data-source="manifest">
        <!-- 客户端动态层：feed.js 从 manifest.json fetch featured 并渲染 CTA -->
        <noscript>{f'<a class="btn btn-primary" href="{audio_src}">{ICON_LIB["play"]}<span>听最新一期</span></a>' if featured else ''}</noscript>
      </div>
      {f'<a class="btn btn-ghost" href="#subscribe">订阅 RSS</a>' if subscribe_enabled else ''}
    </div>
  </div>
</section>"""


def _about_html(title: str, tagline: str, about_text: str, groups: list, episodes: list, author: str, language: str) -> str:
    """About 段：M2-3 人味 + tagline 收敛。"""
    about_text_str = (about_text or "").strip()
    if about_text_str:
        paragraphs = [p.strip() for p in about_text_str.split("\n\n") if p.strip()]
        para_html = "\n".join(
            f'    <p>{_hescape(p.replace(chr(10), "<br>"))}</p>' for p in paragraphs
        )
    else:
        para_html = f'    <p>{_hescape(tagline)}</p>'
    return f"""<section class="about">
  <h2>关于 {_hescape(title)}</h2>
  <div class="about-body">
{para_html}
  </div>
  <ul class="about-points">
    <li><strong>{len(groups)}</strong> 个节目系列</li>
    <li><strong>{len(episodes)}</strong> 集已上线</li>
    <li><strong>{_fmt_dur(sum(e.get('duration',0) for e in episodes))}</strong> 总时长</li>
    <li><strong>{_hescape(author)}</strong></li>
  </ul>
</section>"""


def _subscribe_html(IconLib: dict[str, str], base: str) -> str:
    """Subscribe 段：feature flag 控制。"""
    return f"""<section id="subscribe" class="subscribe">
  <h2>在更多地方听</h2>
  <p class="lead">把 RSS 链接粘贴到任何播客客户端。</p>
  <div class="subscribe-grid">
    <a class="sub-card" href="{base}/feed.xml">
      <span class="sub-icon">{IconLib["rss"]}</span>
      <span class="sub-name">RSS / Atom</span>
    </a>
    <a class="sub-card" href="https://podcasts.apple.com/">
      <span class="sub-icon">{IconLib["podcast_icon"]}</span>
      <span class="sub-name">Apple Podcasts</span>
    </a>
    <a class="sub-card" href="https://www.xiaoyuzhoufm.com/">
      <span class="sub-icon">{IconLib["music"]}</span>
      <span class="sub-name">小宇宙</span>
    </a>
    <a class="sub-card" href="https://www.google.com/podcasts">
      <span class="sub-icon">{IconLib["sparkle"]}</span>
      <span class="sub-name">Google Podcasts</span>
    </a>
  </div>
</section>"""


def build_index(out_dir: Path, podcast: dict[str, Any]) -> Path:
    """M5 改造：Jinja2 拆 658 行 → 数据组装 + 模板渲染 ≤200 行。

    拆解：
    - _hero_html / _about_html / _subscribe_html：3 个 section 独立函数
    - templates/site/base.html：根模板
    - templates/site/partials/{header,series,latest,footer,player}.html：5 个 partial
    - 站点级数据全走 ctx 字典
    """
    out_dir = Path(out_dir)
    data = load_manifest(out_dir)
    base = podcast.get("website", "").rstrip("/")
    title = podcast.get("title", "Podcast")
    desc = podcast.get("description", "")
    tagline = podcast.get("tagline", desc)
    hero_desc = podcast.get("hero_desc", "")
    about_text = podcast.get("about", "")
    author = podcast.get("author", "")
    language = podcast.get("language", "zh-CN")
    cover = podcast.get("cover", "/cover.jpg")
    subscribe_enabled = podcast.get("subscribe", {}).get("enabled", True)

    episodes = data["episodes"]
    groups = _group_by_series(episodes)

    # Featured / Latest 排序
    # 规则：
    #   - featured = 第一个 series（按 latest_date 倒序）的第 1 集
    #   - latest = 按 series 出现顺序，每个 series 最多展示 LATEST_PER_SERIES 集
    #     多于 LATEST_PER_SERIES 的折叠成 "+N 集" 卡片，指向 #series 锚点
    #   - featured 那集不进 latest 区（Hero 已展示）
    LATEST_PER_SERIES = 3

    latest_cards: list[dict[str, Any]] = []
    overflow_cards: list[dict[str, Any]] = []
    for g in groups:
        items = g["items"]
        latest_cards.extend(items[:LATEST_PER_SERIES])
        rest = items[LATEST_PER_SERIES:]
        if rest:
            overflow_cards.append({
                "is_overflow": True,
                "series": g["series"],
                "slug": g["slug"],
                "remaining": len(rest),
            })

    featured = latest_cards[0] if latest_cards else None
    # 模板渲染序列：跳过 featured，剩余 cards + overflow 折叠卡
    latest_short = list(latest_cards[1:]) + overflow_cards

    # 给每集补 audio_src / shownotes_src / display_title / dur_str / play_icon
    def _enrich(eps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for e in eps:
            # 折叠卡（"还有 +N 集"）不是 episode，没有 url / duration 字段；
            # 模板走 {% if ep.is_overflow %} 分支，跳过 enrich 直接透传。
            if e.get("is_overflow"):
                out.append(e)
                continue
            out.append({
                **e,
                "audio_src": _audio_src(e),
                "shownotes_src": _ep_shownotes_src(e),
                "display_title": _display_title(e),
                "title": _hescape(_display_title(e)),  # for template attr injection
                "series": _hescape(e.get("series", "")),
                "description": _hescape(e.get("description", "")),
                "slug": _hescape(e.get("slug", "")),
                "date": _hescape(e.get("date", "")),
                "dur_str": _fmt_dur(e.get("duration", 0)),
                "ep_label": (
                    f"第 {e.get('episode')}/{e.get('total')} 集"
                    if e.get("episode") and e.get("total")
                    else ""
                ),
                "play_icon": _ICON_LIB["play"],
                "audio_label": _audio_label(e),
            })
        return out

    groups_ctx = []
    for g in groups:
        items = _enrich(g.get("items", []))
        s_desc = (g.get("description", "") or "").split("（第")[0].strip()
        groups_ctx.append({
            "slug": _hescape(g["slug"]),
            "series": _hescape(g["series"]),
            "count": g["count"],
            "dur_total": _fmt_dur(g["total_duration"]),
            "description": _hescape(s_desc) if s_desc else "",
            "episodes": items,   # 跟 templates/site/partials/series.html 的 g.episodes 对齐
        })

    latest_ctx = _enrich(latest_short)

    # 4 个 section 独立生成
    hero_html = _hero_html(
        out_dir, title, tagline, hero_desc, cover, base, featured, subscribe_enabled,
        _ICON_LIB,
    )
    about_html = _about_html(title, tagline, about_text, groups, episodes, author, language)
    subscribe_html = _subscribe_html(_ICON_LIB, base) if subscribe_enabled else ""

    # 注入 player.js（构建期替换占位符）
    player_js = (Path(__file__).resolve().parent.parent / "templates" / "player.js").read_text(encoding="utf-8")
    feed_js = (Path(__file__).resolve().parent.parent / "templates" / "feed.js").read_text(encoding="utf-8")

    # Jinja2 渲染
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("site/base.html")
    html = template.render(
        title=title,
        tagline=tagline,
        description=desc,
        base=base,
        cover=cover,
        language=language,
        author=author,
        hero=hero_html,
        about=about_html,
        subscribe=subscribe_html,
        groups=groups_ctx,
        latest=latest_ctx,
        player_js=player_js,
        feed_js=feed_js,
    )
    path = out_dir / "index.html"
    path.write_text(html, encoding="utf-8")

    # 复制样式模板到 output 根
    import shutil
    css_src = Path(__file__).resolve().parent.parent / "templates" / "style.css"
    if css_src.exists():
        shutil.copy(css_src, out_dir / "style.css")
    return path
