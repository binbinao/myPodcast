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
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
        'viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
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


# ---------- helpers ----------

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

def build_index(out_dir: Path, podcast: dict[str, Any]) -> Path:
    """生成暗色主题的节目站 index.html。

    sections（按 landing-page guideline）：
      Header → Hero(Featured Episode) → All Series Grid → Latest →
      About / Why listen → Subscribe / RSS → Footer
    """
    # 解构 _ICON_LIB 到局部（让 f-string 子模板里 {mic}/{music}/{hamburger} 等能解析）
    # P0: emoji 不可作图标，统一用 SVG 描边。
    # 注意：不能用 key='podcast'，会覆盖函数参数 `podcast`（dict）。
    mic, music, sparkle, hamburger, play, rss, podcast_icon = (
        _ICON_LIB["mic"],
        _ICON_LIB["music"],
        _ICON_LIB["sparkle"],
        _ICON_LIB["hamburger"],
        _ICON_LIB["play"],
        _ICON_LIB["rss"],
        _ICON_LIB["podcast_icon"],
    )
    data = load_manifest(out_dir)
    base = podcast.get("website", "").rstrip("/")
    title = podcast.get("title", "Podcast")
    desc = podcast.get("description", "")
    author = podcast.get("author", "")
    language = podcast.get("language", "zh-CN")
    cover = podcast.get("cover", "/cover.jpg")
    subscribe_enabled = podcast.get("subscribe", {}).get("enabled", True)

    episodes = data["episodes"]
    groups = _group_by_series(episodes)

    # Featured：第一组第一集
    featured = groups[0]["items"][0] if groups else None
    featured_slug = featured["slug"] if featured else None
    # Latest：全部单集按日期倒序
    latest = list(episodes)
    latest.sort(key=lambda x: x.get("date", ""), reverse=True)

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

    def _ep_card(e: dict[str, Any], compact: bool = False) -> str:
        dur = _fmt_dur(e.get("duration", 0))
        ep_idx = e.get("episode")
        total = e.get("total")
        ep_label = f"第 {ep_idx}/{total} 集" if ep_idx and total else ""
        cls = "ep-card compact" if compact else "ep-card"
        return f"""<article class="{cls}" data-slug="{escape(e['slug'])}">
  <div class="ep-meta">
    <time datetime="{e.get('date','')}">{e.get('date','')}</time>
    {f'<span class="badge">{escape(ep_label)}</span>' if ep_label else ''}
    <span class="duration">{dur}</span>
  </div>
  <h3 class="ep-title">{escape(_display_title(e))}</h3>
  <p class="ep-desc">{escape(e.get('description',''))}</p>
  <audio controls preload="none" src="{_audio_src(e)}"></audio>
  <div class="ep-links">
    <a href="{_audio_src(e)}">收听</a>
    <a href="{_ep_shownotes_src(e)}">Shownotes</a>
    <a href="{_audio_src(e)}" download>下载</a>
  </div>
</article>"""

    # Hero（featured episode）
    cover_abs = (Path(out_dir) / Path(cover).name).resolve() if cover else None
    cover_exists = cover_abs.exists() if cover_abs else False
    # cover 图用相对文件名：index.html 与 cover.jpg 同处站点根目录，
    # 相对路径在 gh-pages 子路径(/myPodcast/)也能正确解析，避免 /cover.jpg 域根 404
    cover_src = Path(cover).name if cover_exists else ""
    # og:image 需要绝对地址才利于社交卡片抓取；base 为空时退回相对
    og_image = f"{base}/{cover_src}" if (base and cover_src) else cover_src
    if featured:
        art_block = (
            f'<img class="hero-img" src="{cover_src}" alt="{escape(title)} 封面" loading="eager">'
            if cover_exists else
            '<div class="hero-art" aria-hidden="true"><div class="art-gradient"></div><div class="art-glyph">{mic}</div></div>'
        )
        hero_html = f"""<section class="hero">
  <div class="hero-media">
    {art_block}
  </div>
  <div class="hero-content">
    <p class="hero-eyebrow">最新一期 · <time datetime="{featured.get('date','')}">{featured.get('date','')}</time></p>
    <h1 class="hero-title">{escape(_display_title(featured))}</h1>
    <p class="hero-desc">{escape(featured.get('description',''))}</p>
    <div class="hero-cta">
      <a class="btn btn-primary" href="{_audio_src(featured)}" data-action="play-now"><span class="btn-play">{play}</span><span>现在就听</span></a>
      {f'<a class="btn btn-ghost" href="#subscribe">订阅 RSS</a>' if subscribe_enabled else ''}
    </div>
    <p class="hero-quote">"{desc}"</p>
  </div>
</section>"""
    else:
        hero_html = f"""<section class="hero">
  <div class="hero-content">
    <h1 class="hero-title">{escape(title)}</h1>
    <p class="hero-desc">{escape(desc)}</p>
  </div>
</section>"""

    # Series 卡片网格 — 合集型：每卡展示一个 series 含旗下 ep 的紧凑列表
    # 区别于"全部单集"扁平流：合集卡看 series 全貌，单集流按发布时间刷新。
    series_cards = []
    for g in groups:
        cover_letter = (g["series"] or "?").strip()[0] if (g["series"] or "?").strip() else "?"
        dur_total = _fmt_dur(g["total_duration"])
        # 该 series 的 ep 紧凑行（编号 / 标题 / 时长 / play）
        ep_rows = []
        for it in g.get("items", []):
            ep_rows.append(
                f'<li class="series-ep-item">'
                f'<span class="series-ep-num">EP {int(it.get("ep_index", it.get("episode", 1)) or 1):02d}</span>'
                f'<a class="series-ep-title" href="{_ep_shownotes_src(it)}" title="{escape(it.get("title",""))}">'
                f'{escape(_display_title(it))}</a>'
                f'<span class="series-ep-dur">{_fmt_dur(it.get("duration", 0))}</span>'
                f'<a class="series-ep-play" href="{_audio_src(it)}" aria-label="听 {_audio_label(it)}" download>▶</a>'
                f'</li>'
            )
        # 该 series 的所有 ep 共享 series 描述（取第一集切片用作节目简介）
        s_desc = g.get("description", "")
        # 单集描述如果以"（第"开头截掉避免噪音
        s_desc = s_desc.split("（第")[0].strip() if "（第" in s_desc else s_desc
        series_cards.append(f"""<article class="series-card" data-slug="{escape(g['slug'])}">
  <div class="series-cover" aria-hidden="true" style="background-image:url('{cover_src}')">
    <span class="cover-letter">{escape(cover_letter)}</span>
  </div>
  <div class="series-body">
    <h3>{escape(g['series'])}</h3>
    <p class="series-meta">{g['count']} 集 · 总时长 {dur_total}</p>
    <p class="series-desc">{escape(s_desc)}</p>
    <ol class="series-ep-list">
{chr(10).join(ep_rows)}
    </ol>
  </div>
</article>""")

    # Latest 单集（featured 之外的全部，显示最近 6 个）
    latest_html = "\n".join(_ep_card(e, compact=True) for e in latest)

    # About
    about_html = f"""<section class="about">
  <h2>关于 {escape(title)}</h2>
  <p>{escape(desc)}</p>
  <ul class="about-points">
    <li><strong>{len(groups)}</strong> 个节目系列</li>
    <li><strong>{len(episodes)}</strong> 集已上线</li>
    <li><strong>{_fmt_dur(sum(e.get('duration',0) for e in episodes))}</strong> 总时长</li>
    <li><strong>{language}</strong></li>
  </ul>
</section>"""

    # Subscribe（可用 config subscribe.enabled 关闭）
    subscribe_html = f"""<section class="subscribe" id="subscribe">
  <h2>在更多地方听</h2>
  <p class="subscribe-lead">订阅 RSS / Apple Podcasts / 小宇宙 等任意平台，新一期会自动同步过去。</p>
  <div class="subscribe-grid">
    <a class="sub-card" href="feed.xml">
      <span class="sub-icon" aria-hidden="true">{rss}</span>
      <span class="sub-title">RSS / Atom</span>
      <span class="sub-desc">feed.xml — 任何播客客户端可订阅</span>
    </a>
    <a class="sub-card" href="{base}/feed.xml" target="_blank" rel="noopener">
      <span class="sub-icon" aria-hidden="true">{podcast_icon}</span>
      <span class="sub-title">Apple Podcasts</span>
      <span class="sub-desc">把 RSS 链接粘贴到 Apple Podcasts</span>
    </a>
    <a class="sub-card" href="https://www.xiaoyuzhoufm.com/" target="_blank" rel="noopener">
      <span class="sub-icon" aria-hidden="true">{sparkle}</span>
      <span class="sub-title">小宇宙</span>
      <span class="sub-desc">手动添加 RSS 订阅</span>
    </a>
    <a class="sub-card" href="https://music.163.com/" target="_blank" rel="noopener">
      <span class="sub-icon" aria-hidden="true">{music}</span>
      <span class="sub-title">网易云音乐</span>
      <span class="sub-desc">搜索节目名订阅</span>
    </a>
  </div>
</section>""" if subscribe_enabled else ""

    # Footer
    footer_html = f"""<footer class="site-footer">
  <div class="footer-grid">
    <div class="footer-brand">
      <h3>{escape(title)}</h3>
      <p>{escape(desc)}</p>
    </div>
    <div class="footer-col">
      <h4>节目</h4>
      <ul>{''.join(f'<li><a href="#series">{escape(g["series"])}</a></li>' for g in groups[:6])}</ul>
    </div>
    <div class="footer-col">
      <h4>订阅</h4>
      <ul>
        <li><a href="feed.xml">RSS</a></li>
        <li><a href="https://www.xiaoyuzhoufm.com/">小宇宙</a></li>
        <li><a href="https://podcasts.apple.com/">Apple Podcasts</a></li>
      </ul>
    </div>
  </div>
  <p class="footer-bottom">© {date.today().year} {escape(author or title)} · 由 <code>myPodcast</code> 自动生成</p>
</footer>"""

    # Header
    header_html = f"""<header class="site-header">
  <a class="brand" href="#">
    <span class="brand-mark" aria-hidden="true">{mic}</span>
    <span class="brand-text">{escape(title)}</span>
  </a>
  <nav class="site-nav" id="site-nav" aria-label="主导航">
    <a href="#series">节目</a>
    <a href="#latest">最新</a>
    <a href="#about">关于</a>
    {f'<a href="#subscribe">订阅</a>' if subscribe_enabled else ''}
    <a class="nav-cta" href="feed.xml">RSS</a>
  </nav>
  <button class="nav-toggle" aria-label="打开菜单" aria-expanded="false" aria-controls="site-nav">{hamburger}</button>
</header>"""

    # All HTML
    html = f"""<!doctype html>
<html lang="{language}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(desc)}">
<meta property="og:type" content="website">
<meta property="og:image" content="{og_image}">
<link rel="alternate" type="application/rss+xml" title="{escape(title)}" href="feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,600;700&display=swap" rel="stylesheet" media="(min-width: 1024px) and (prefers-reduced-motion: no-preference)">
<link rel="stylesheet" href="style.css">
</head>
<body>
<a class="skip" href="#main">跳到主内容</a>
{header_html}
<main id="main">
{hero_html}
<section id="series">
  <h2>节目</h2>
  <p class="lead">{len(groups)} 个系列 · 按发布时间倒序。每个系列从首页第一行起编号。</p>
  <div class="series-grid">
{chr(10).join(series_cards)}
  </div>
</section>
<section id="latest">
  <h2>全部单集</h2>
  <p class="lead">所有已上线单集，按发布日期倒序。</p>
  <div class="ep-grid">
{latest_html}
  </div>
</section>
{about_html}
{subscribe_html}
</main>
{footer_html}
<script>
document.addEventListener('click', function(e) {{
  var t = e.target;
  if (t.matches && t.matches('[data-action="play-now"]')) {{
    var a = document.querySelector('#latest audio, .hero audio');
    if (a) {{ a.scrollIntoView({{block: 'center'}}); a.play().catch(function(){{}}); }}
    e.preventDefault();
  }}
}});
var nt = document.querySelector('.nav-toggle');
if (nt) {{
  nt.addEventListener('click', function() {{
    var n = document.getElementById('site-nav');
    var open = n.classList.toggle('nav-open');
    nt.setAttribute('aria-expanded', open ? 'true' : 'false');
  }});
}}
// 全局 audio 互斥：任一 audio 开始播放时暂停其他所有
// 同时给当前播放的 audio 父卡片加 .is-playing 视觉反馈
(function() {{
  var audios = Array.prototype.slice.call(document.querySelectorAll('audio'));
  function clearActive() {{
    audios.forEach(function(a) {{
      var card = a.closest('.ep-card, .hero');
      if (card) card.classList.remove('is-playing');
    }});
  }}
  // 监听 capture 阶段 play/pause/ended，确保捕获冒泡
  document.addEventListener('play', function(e) {{
    if (e.target.tagName !== 'AUDIO') return;
    audios.forEach(function(a) {{
      if (a !== e.target && !a.paused) a.pause();
    }});
    clearActive();
    var card = e.target.closest('.ep-card, .hero');
    if (card) card.classList.add('is-playing');
  }}, true);
  document.addEventListener('pause', function(e) {{
    if (e.target.tagName !== 'AUDIO') return;
    var card = e.target.closest('.ep-card, .hero');
    if (card) card.classList.remove('is-playing');
  }}, true);
  document.addEventListener('ended', function(e) {{
    if (e.target.tagName !== 'AUDIO') return;
    var card = e.target.closest('.ep-card, .hero');
    if (card) card.classList.remove('is-playing');
  }}, true);
  // 合集卡 EP 行的 play 按钮：找匹配的 audio 元素 .play()，滚动到该卡片
  document.addEventListener('click', function(e) {{
    var play = e.target.closest('.series-ep-play');
    if (!play) return;
    e.preventDefault();
    var href = play.getAttribute('href');
    if (!href) return;
    var parts = href.match(/series\/([^/]+)\/ep-(\d+)\/episode\.mp3/);
    if (!parts) return;
    var slug = parts[1], epn = parseInt(parts[2], 10);
    var epKey = 'series/' + slug + '/ep-' + (epn < 10 ? '0' + epn : epn) + '/episode.mp3';
    var target = null;
    document.querySelectorAll('audio').forEach(function(a) {{
      if (!target && (a.getAttribute('src') || '').indexOf(epKey) !== -1) target = a;
    }});
    if (target) {{
      target.currentTime = 0;
      target.play().catch(function(){{}});
      target.closest('.ep-card').scrollIntoView({{block: 'center', behavior: 'smooth'}});
    }} else {{
      // 找不到（ep 未 build）— fallback 链接，让浏览器当下载
      window.location.href = href;
    }}
  }});
}})();
</script>
</body>
</html>
"""
    path = Path(out_dir) / "index.html"
    path.write_text(html, encoding="utf-8")
    # 复制样式模板到 output 根（HTML 引用 /style.css）
    import shutil
    css_src = Path(__file__).resolve().parent.parent / "templates" / "style.css"
    if css_src.exists():
        shutil.copy(css_src, Path(out_dir) / "style.css")
    return path