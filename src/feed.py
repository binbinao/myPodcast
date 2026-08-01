"""发布件：每集 shownotes + 全局 RSS / 节目站 index.html。

manifest.json 记录每集首次生成的实际日期（之后 build 不覆盖），作为 RSS pubDate 与
节目站显示日期使用；build_index 按 series 聚合 + 5 sections 渲染（暗色落地页风格）。
"""
from __future__ import annotations

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


def register_episode(out_dir: Path, meta: dict[str, Any], slug: str, duration: int, size: int) -> None:
    """注册一集到 manifest。已存在则保留原 date（首次 build 写入的日期）。"""
    data = load_manifest(out_dir)
    eps = data["episodes"]
    # 找旧条目（如有）保留 date
    old = next((e for e in eps if e["slug"] == slug), None)
    today = date.today().isoformat()
    entry = {
        "slug": slug,
        "title": meta.get("title", slug),
        "subtitle": meta.get("subtitle", ""),
        "description": meta.get("description", ""),
        # 保留旧日期，不被新 build 覆盖
        "date": (old["date"] if old else today),
        "created": (old.get("created") if old else today),
        "updated": today,
        "duration": duration,
        "size": size,
        "url": f"{slug}/episode.mp3",
        "series": meta.get("series", ""),
        "episode": meta.get("episode", ""),
        "total": meta.get("total", ""),
        "format": meta.get("format", "solo"),
        "chapter": meta.get("chapter", ""),
        "voice": meta.get("voice", ""),  # frontmatter 显式 voice 可写入
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


# ---------- helpers ----------

def _fmt_dur(d: int) -> str:
    """把秒数格式化为 MM:SS。"""
    m, s = divmod(int(d), 60)
    return f"{m}:{s:02d}"


def _slugify_series(title: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", str(title)).strip("-")


def _group_by_series(eps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """episodes → 按 series 分组（series 为空/单集也算独立组）。"""
    series_map: dict[str, list[dict[str, Any]]] = {}
    singletons: list[dict[str, Any]] = []
    for e in eps:
        s = e.get("series") or ""
        if s:
            series_map.setdefault(s, []).append(e)
        else:
            singletons.append(e)
    groups = []
    for series_title, items in series_map.items():
        items.sort(key=lambda x: x.get("episode", 1) or 1)
        total_dur = sum(x.get("duration", 0) for x in items)
        groups.append({
            "series": series_title,
            "slug": _slugify_series(series_title),
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
    data = load_manifest(out_dir)
    base = podcast.get("website", "").rstrip("/")
    title = podcast.get("title", "Podcast")
    desc = podcast.get("description", "")
    author = podcast.get("author", "")
    language = podcast.get("language", "zh-CN")
    cover = podcast.get("cover", "/cover.jpg")

    episodes = data["episodes"]
    groups = _group_by_series(episodes)

    # Featured：第一组第一集
    featured = groups[0]["items"][0] if groups else None
    featured_slug = featured["slug"] if featured else None
    # Latest：featured 之外的全部按日期倒序
    latest = [e for e in episodes if e.get("slug") != featured_slug]
    latest.sort(key=lambda x: x.get("date", ""), reverse=True)

    def _audio_src(e: dict[str, Any]) -> str:
        # 站点内音频用相对路径：index.html 与各集子目录同处站点根目录，
        # 部署到 gh-pages 子路径(/myPodcast/)也能正确解析，避免占位 example.com 域名 404
        return e["url"]

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
  <h3 class="ep-title"><a href="{_audio_src(e)}">听</a> {escape(e.get('title',''))}</h3>
  <p class="ep-desc">{escape(e.get('description',''))}</p>
  <audio controls preload="none" src="{_audio_src(e)}"></audio>
  <div class="ep-links">
    <a href="{e.get('slug','')}/shownotes.md">Shownotes</a>
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
            '<div class="hero-art" aria-hidden="true"><div class="art-gradient"></div><div class="art-glyph">🎙</div></div>'
        )
        hero_html = f"""<section class="hero">
  <div class="hero-media">
    {art_block}
  </div>
  <div class="hero-content">
    <p class="hero-eyebrow">最新一期 · <time datetime="{featured.get('date','')}">{featured.get('date','')}</time></p>
    <h1 class="hero-title">{escape(featured.get('title',''))}</h1>
    <p class="hero-desc">{escape(featured.get('description',''))}</p>
    <div class="hero-cta">
      <a class="btn btn-primary" href="{_audio_src(featured)}" data-action="play-now">▶ 现在就听</a>
      <a class="btn btn-ghost" href="#subscribe">订阅 RSS</a>
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

    # Series 卡片网格
    series_cards = []
    for g in groups:
        cover_letter = (g["series"] or "?").strip()[0]
        dur_total = _fmt_dur(g["total_duration"])
        # 取每组描述（短）
        s_desc = g.get("description", "")
        # 取首图 mp3 第一个 episode
        first = g["items"][0]
        items_html = "\n".join(
            f"""<li>
  <span class="li-title">{escape(it.get('title','').split('·',1)[-1].strip())}</span>
  <span class="li-meta">{_fmt_dur(it.get('duration',0))} · <a href="{_audio_src(it)}">听</a></span>
</li>""" for it in g["items"][:5]
        )
        series_cards.append(f"""<article class="series-card" data-slug="{escape(g['slug'])}">
  <div class="series-cover" aria-hidden="true">
    <span class="cover-letter">{escape(cover_letter)}</span>
  </div>
  <div class="series-body">
    <h3>{escape(g['series'])}</h3>
    <p class="series-meta">{g['count']} 集 · 总时长 {dur_total}</p>
    <p class="series-desc">{escape(s_desc)}</p>
    <ul class="episode-list">
      {items_html}
    </ul>
    <p class="series-cta"><a href="#latest">查看全部</a></p>
  </div>
</article>""")

    # Latest 单集（featured 之外的全部，显示最近 6 个）
    latest_html = "\n".join(_ep_card(e, compact=True) for e in latest[:6])

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

    # Subscribe
    subscribe_html = f"""<section class="subscribe" id="subscribe">
  <h2>在更多地方听</h2>
  <p class="subscribe-lead">订阅 RSS / Apple Podcasts / 小宇宙 等任意平台，新一期会自动同步过去。</p>
  <div class="subscribe-grid">
    <a class="sub-card" href="feed.xml">
      <span class="sub-icon" aria-hidden="true">📡</span>
      <span class="sub-title">RSS / Atom</span>
      <span class="sub-desc">feed.xml — 任何播客客户端可订阅</span>
    </a>
    <a class="sub-card" href="{base}/feed.xml" target="_blank" rel="noopener">
      <span class="sub-icon" aria-hidden="true">🍎</span>
      <span class="sub-title">Apple Podcasts</span>
      <span class="sub-desc">把 RSS 链接粘贴到 Apple Podcasts</span>
    </a>
    <a class="sub-card" href="https://www.xiaoyuzhoufm.com/" target="_blank" rel="noopener">
      <span class="sub-icon" aria-hidden="true">🌌</span>
      <span class="sub-title">小宇宙</span>
      <span class="sub-desc">手动添加 RSS 订阅</span>
    </a>
    <a class="sub-card" href="https://music.163.com/" target="_blank" rel="noopener">
      <span class="sub-icon" aria-hidden="true">🎵</span>
      <span class="sub-title">网易云音乐</span>
      <span class="sub-desc">搜索节目名订阅</span>
    </a>
  </div>
</section>"""

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
  <a class="brand" href="#top">
    <span class="brand-mark" aria-hidden="true">🎙</span>
    <span class="brand-text">{escape(title)}</span>
  </a>
  <nav class="site-nav" aria-label="主导航">
    <a href="#series">节目</a>
    <a href="#latest">最新</a>
    <a href="#about">关于</a>
    <a href="#subscribe">订阅</a>
    <a class="nav-cta" href="feed.xml">RSS</a>
  </nav>
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
<style>
:root {{
  --bg: #0b0c10;
  --bg-soft: #15161d;
  --bg-card: #181a23;
  --border: #262833;
  --text: #f4f4f6;
  --text-soft: #b6b8c4;
  --text-dim: #7a7d8c;
  --accent: #ff7a59;
  --accent-glow: rgba(255,122,89,0.18);
  --link: #ffb59a;
  --radius: 14px;
  --max: 1100px;
  --font-display: ui-serif, "Newsreader", "Fraunces", "Source Serif Pro", "PingFang SC", serif;
  --font-body: ui-sans-serif, "Inter", "IBM Plex Sans", "PingFang SC", "Helvetica Neue", sans-serif;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--text); font-family: var(--font-body); -webkit-font-smoothing: antialiased; line-height: 1.55; }}
a {{ color: var(--link); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
img {{ max-width: 100%; display: block; }}

/* Skip link / a11y */
.skip {{ position: absolute; left: -9999px; top: 8px; background: var(--accent); color: #000; padding: 8px 16px; border-radius: 6px; }}
.skip:focus {{ left: 8px; z-index: 10; }}

/* Header */
.site-header {{ position: sticky; top: 0; z-index: 10; backdrop-filter: blur(12px); background: rgba(11,12,16,0.78); border-bottom: 1px solid var(--border); }}
.site-header > * {{ display: flex; max-width: var(--max); margin: 0 auto; padding: 14px 24px; align-items: center; justify-content: space-between; gap: 24px; }}
.brand {{ display: inline-flex; align-items: center; gap: 10px; font-family: var(--font-display); font-weight: 700; font-size: 20px; color: var(--text); }}
.brand-mark {{ font-size: 24px; filter: drop-shadow(0 0 10px var(--accent-glow)); }}
.site-nav {{ display: flex; gap: 18px; align-items: center; font-size: 14px; }}
.site-nav a {{ color: var(--text-soft); }}
.site-nav a:hover {{ color: var(--text); text-decoration: none; }}
.nav-cta {{ border: 1px solid var(--accent); color: var(--accent) !important; padding: 6px 12px; border-radius: 8px; }}

/* Hero */
.hero {{ max-width: var(--max); margin: 0 auto; padding: 56px 24px 80px; display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 56px; align-items: center; }}
.hero-media {{ position: relative; aspect-ratio: 1 / 1; border-radius: 24px; overflow: hidden; border: 1px solid var(--border); box-shadow: 0 20px 60px rgba(0,0,0,0.4); }}
.hero-img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
.hero-art {{ position: relative; aspect-ratio: 1 / 1; border-radius: 24px; overflow: hidden; background: var(--bg-soft); border: 1px solid var(--border); }}
.art-gradient {{ position: absolute; inset: 0; background: radial-gradient(circle at 30% 20%, rgba(255,122,89,0.45), transparent 55%), radial-gradient(circle at 80% 80%, rgba(124,92,255,0.40), transparent 60%), linear-gradient(160deg, #181a23, #0b0c10); }}
.art-glyph {{ position: absolute; inset: 0; display: grid; place-items: center; font-size: 96px; filter: drop-shadow(0 0 20px var(--accent-glow)); }}
.hero-eyebrow {{ color: var(--accent); text-transform: uppercase; letter-spacing: 1px; font-size: 12px; font-weight: 600; margin: 0 0 14px; }}
.hero-title {{ font-family: var(--font-display); font-size: clamp(34px, 5vw, 56px); line-height: 1.08; font-weight: 700; margin: 0 0 16px; letter-spacing: -0.02em; }}
.hero-desc {{ color: var(--text-soft); font-size: 18px; margin: 0 0 28px; max-width: 56ch; }}
.hero-cta {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 28px; }}
.btn {{ display: inline-flex; align-items: center; gap: 8px; padding: 12px 22px; border-radius: 10px; font-weight: 600; font-size: 15px; transition: transform .15s ease, background .15s ease; }}
.btn-primary {{ background: var(--accent); color: #0b0c10; }}
.btn-primary:hover {{ background: #ff8d6f; text-decoration: none; transform: translateY(-1px); }}
.btn-ghost {{ border: 1px solid var(--border); color: var(--text); }}
.btn-ghost:hover {{ border-color: var(--text-soft); text-decoration: none; }}
.hero-quote {{ color: var(--text-dim); font-style: italic; font-size: 15px; border-left: 2px solid var(--border); padding-left: 14px; margin: 0; }}

/* Sections base */
section {{ max-width: var(--max); margin: 0 auto; padding: 56px 24px; }}
section h2 {{ font-family: var(--font-display); font-size: clamp(26px, 3vw, 36px); margin: 0 0 8px; letter-spacing: -0.01em; }}
section > p.lead {{ color: var(--text-soft); margin: 0 0 32px; font-size: 16px; max-width: 60ch; }}

/* Series grid */
.series-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; margin-top: 32px; }}
.series-card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; transition: transform .2s ease, border-color .2s ease; }}
.series-card:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
.series-cover {{ aspect-ratio: 16/9; background: linear-gradient(135deg, #181a23, #0b0c10); position: relative; overflow: hidden; border-bottom: 1px solid var(--border); }}
.series-cover::before {{ content: ""; position: absolute; inset: 0; background: radial-gradient(circle at 70% 30%, var(--accent-glow), transparent 60%); }}
.cover-letter {{ position: absolute; inset: 0; display: grid; place-items: center; font-family: var(--font-display); font-size: 96px; color: var(--accent); opacity: 0.6; }}
.series-body {{ padding: 20px 22px 22px; }}
.series-body h3 {{ margin: 0 0 4px; font-family: var(--font-display); font-size: 22px; }}
.series-meta {{ color: var(--text-dim); font-size: 13px; margin: 0 0 12px; }}
.series-desc {{ color: var(--text-soft); font-size: 14px; margin: 0 0 16px; }}
.episode-list {{ list-style: none; padding: 0; margin: 0 0 14px; border-top: 1px solid var(--border); }}
.episode-list li {{ display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); font-size: 14px; }}
.li-title {{ color: var(--text); }}
.li-meta {{ color: var(--text-dim); white-space: nowrap; }}
.series-cta {{ font-size: 13px; color: var(--accent); margin: 0; }}

/* Latest episodes */
.ep-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-top: 24px; }}
.ep-card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }}
.ep-card.compact {{ padding: 18px; }}
.ep-meta {{ display: flex; gap: 10px; align-items: center; color: var(--text-dim); font-size: 12px; margin-bottom: 8px; }}
.ep-meta .badge {{ background: var(--accent-glow); color: var(--accent); padding: 2px 8px; border-radius: 6px; font-weight: 600; }}
.ep-title {{ margin: 0 0 8px; font-size: 17px; line-height: 1.35; }}
.ep-title a {{ color: var(--text-dim); font-size: 14px; font-weight: 500; margin-right: 4px; }}
.ep-title a:hover {{ color: var(--accent); text-decoration: none; }}
.ep-desc {{ color: var(--text-soft); font-size: 14px; margin: 0 0 14px; }}
.ep-card audio {{ width: 100%; margin-bottom: 10px; }}
.ep-links {{ display: flex; gap: 14px; font-size: 13px; }}

/* About */
.about {{ background: var(--bg-soft); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }}
.about-points {{ list-style: none; padding: 0; margin: 28px 0 0; display: flex; flex-wrap: wrap; gap: 32px; }}
.about-points li {{ color: var(--text-soft); font-size: 15px; }}
.about-points strong {{ color: var(--accent); font-size: 28px; font-weight: 700; font-family: var(--font-display); display: block; margin-bottom: 4px; }}

/* Subscribe */
.subscribe {{ text-align: center; padding-bottom: 80px; }}
.subscribe-lead {{ color: var(--text-soft); max-width: 60ch; margin: 0 auto 32px; }}
.subscribe-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; max-width: 880px; margin: 0 auto; }}
.sub-card {{ display: block; background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 22px 18px; text-align: left; color: var(--text); transition: transform .2s ease, border-color .2s ease; }}
.sub-card:hover {{ border-color: var(--accent); transform: translateY(-2px); text-decoration: none; }}
.sub-icon {{ display: block; font-size: 28px; margin-bottom: 8px; }}
.sub-title {{ display: block; font-weight: 600; margin-bottom: 4px; }}
.sub-desc {{ display: block; color: var(--text-dim); font-size: 13px; }}

/* Footer */
.site-footer {{ background: var(--bg-soft); border-top: 1px solid var(--border); margin-top: 80px; padding: 48px 24px 24px; }}
.footer-grid {{ max-width: var(--max); margin: 0 auto; display: grid; grid-template-columns: 1.5fr 1fr 1fr; gap: 40px; }}
.footer-brand h3 {{ font-family: var(--font-display); margin: 0 0 8px; font-size: 20px; }}
.footer-brand p {{ color: var(--text-soft); margin: 0; font-size: 14px; }}
.footer-col h4 {{ margin: 0 0 12px; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-dim); }}
.footer-col ul {{ list-style: none; padding: 0; margin: 0; }}
.footer-col li {{ padding: 4px 0; font-size: 14px; }}
.footer-col a {{ color: var(--text-soft); }}
.footer-bottom {{ max-width: var(--max); margin: 32px auto 0; color: var(--text-dim); font-size: 12px; text-align: center; border-top: 1px solid var(--border); padding-top: 20px; }}
.footer-bottom code {{ background: var(--bg-card); padding: 1px 6px; border-radius: 4px; font-size: 11px; }}

/* Responsive */
@media (max-width: 760px) {{
  .hero {{ grid-template-columns: 1fr; padding: 32px 20px 56px; gap: 32px; }}
  .hero-art {{ max-width: 280px; margin: 0 auto; }}
  section {{ padding: 40px 20px; }}
  .footer-grid {{ grid-template-columns: 1fr; gap: 24px; }}
  .site-header > * {{ padding: 12px 16px; }}
  .site-nav {{ display: none; }}
  .site-nav.nav-open {{ display: flex; flex-wrap: wrap; }}
}}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}
</style>
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
  <h2>最新单集</h2>
  <p class="lead">按发布日期排序的前几集。</p>
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
</script>
</body>
</html>
"""
    path = Path(out_dir) / "index.html"
    path.write_text(html, encoding="utf-8")
    return path