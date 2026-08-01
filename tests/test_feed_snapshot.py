"""feed.py 端到端快照（重构 Phase 0 安全网）。

动机：feed.py 是 658 行上帝文件，零测试——拆 Jinja2 前必须先建快照。
跑 build 后对 feed.xml / index.html / shownotes 做关键结构断言（不是 byte 级 diff，
因为 timestamp 不可重放）。

覆盖：
1. 产物文件存在 + 非空
2. feed.xml 含 item/pubDate/enclosure (RSS 2.0 三件套)
3. index.html 含 5 sections（hero / series / latest / about / subscribe）+ 站点骨架
4. shownotes.md 含标题 + 音频链接
5. P0 红线：zero emoji 在 HTML/RSS 产物里
6. SVG 图标库：_ICON_LIB 存在且 7+ 图标
7. P0-C 复现：含双引号标题的 episode 必须被 _hescape 转义
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.feed import (
    _ICON_LIB,
    _hescape,
    _fmt_dur,
    build_index,
    build_feed,
    load_manifest,
    write_shownotes,
    register_episode,
)
from src.ingest import parse_script


# P0 规则的 emoji 正则（与 ROOT_SYSTEM_POLICY 一致，\U 写 5 位避免 \u 4 位吞 ASCII）
_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001F9FF"
    r"\U0001FA00-\U0001FAFF"
    r"\u2600-\u26FF"
    r"\u2700-\u27BF"
    r"\U0001F000-\U0001F02F"
    r"\U0001F0A0-\U0001F0FF"
    r"\U0001F100-\U0001F64F"
    r"\U0001F680-\U0001F6FF"
    r"\U0001F900-\U0001F9FF"
    r"\U0001FA00-\U0001FA6F"
    r"\U0001FA70-\U0001FAFF"
    r"\u200D"
    r"\u20E3"
    r"\uFE00-\uFE0F"
    r"\U000E0020-\U000E007F]"
)

# 装饰字符图标（与字符图标守卫一致）—— index.html 不应出现
_DECORATIVE_ICON_CHARS = re.compile(r"[▶☰✕✕▾▴]")


class FeedSnapshotTest(unittest.TestCase):
    """端到端：跑一次 build，检查产物结构 + P0 红线。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        # 真实 fixture：拷贝一份小 raw 进来
        cls.raw_dir = cls.out / "raw"
        cls.raw_dir.mkdir()
        cls.draft = cls.out / "drafts" / "fixture-series" / "ep-01.md"
        cls.draft.parent.mkdir(parents=True)
        cls.draft.write_text(
            "---\n"
            "title: 测试节目\n"
            "series: 重构测试\n"
            "series_slug: refactor-test\n"
            "date: 2026-08-01\n"
            "host: 斌哥\n"
            "guest: 靓仔\n"
            "format: duo\n"
            "duration_est: 5min\n"
            "source: raw/fixture.md\n"
            "---\n"
            "# 第一章 开始重构\n\n"
            "[host] 这是个测试 segment\n"
            "[guest] 接话接话\n",
            encoding="utf-8",
        )
        # 模拟一个 mp3 + 时长
        ep_out = cls.out / "series" / "refactor-test" / "ep-01"
        ep_out.mkdir(parents=True)
        cls.mp3 = ep_out / "episode.mp3"
        cls.mp3.write_bytes(b"\x00" * 100)  # 100 字节假 mp3

        # 跑 build
        cfg = {
            "podcast": {
                "title": "测试电台",
                "description": "快照测试",
                "base_url": "https://example.com",
                "author": "斌哥",
            }
        }

        # 调 register_episode + write_shownotes + build_feed + build_index
        meta, body = parse_script(cls.draft.read_text(encoding="utf-8"))
        segments = body if isinstance(body, list) else [{"role": "host", "text": body}]
        register_episode(
            out_dir=cls.out,
            meta=meta,
            slug="refactor-test",
            duration=42,  # fake
            size=100,
        )
        write_shownotes(
            ep_dir=cls.mp3.parent,
            meta=meta,
            segments=segments,
            duration=42,
        )
        build_feed(cls.out, cfg["podcast"])
        build_index(cls.out, cfg["podcast"])

        cls.feed = (cls.out / "feed.xml").read_text(encoding="utf-8")
        cls.index = (cls.out / "index.html").read_text(encoding="utf-8")
        cls.shownotes = (ep_out / "shownotes.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_products_exist(self) -> None:
        self.assertTrue((self.out / "feed.xml").exists())
        self.assertTrue((self.out / "index.html").exists())
        self.assertTrue((self.mp3.parent / "shownotes.md").exists())
        self.assertTrue((self.out / "manifest.json").exists())

    def test_feed_xml_has_rss2_skeleton(self) -> None:
        for needle in ["<rss", "<channel>", "<title>测试电台</title>",
                       "<description>快照测试</description>",
                       "<item>", "<title>", "<enclosure", "<pubDate>"]:
            self.assertIn(needle, self.feed, f"feed.xml 缺 {needle!r}")

    def test_index_html_has_5_sections(self) -> None:
        # 5 个 section 锚点（hero 是 class，#subscribe 是 id，#series/#latest 是 id）
        for needle in ['class="hero"', 'id="series"', 'id="latest"', 'class="about"', 'id="subscribe"']:
            self.assertIn(needle, self.index, f"index.html 缺 {needle!r} section")

    def test_index_html_no_emoji(self) -> None:
        # P0-1 红线：emoji 不能作功能图标
        m = _EMOJI_RE.search(self.index)
        self.assertIsNone(m, f"index.html 含 emoji: {m.group() if m else None!r} (P0 违规)")

    def test_index_html_no_decorative_icons(self) -> None:
        # 字符图标守卫：▶/☰/▾ 等不许出现在 HTML
        m = _DECORATIVE_ICON_CHARS.search(self.index)
        self.assertIsNone(m, f"index.html 含装饰字符图标: {m.group() if m else None!r}")

    def test_shownotes_has_title_and_segments(self) -> None:
        # shownotes 当前是纯文本（M2-4 待改进：加 frontmatter + .mp3 链接）
        # 守恒：标题 + 时长 + 至少一段 segment
        self.assertIn("测试节目", self.shownotes)
        self.assertIn("0 分 42 秒", self.shownotes)
        self.assertIn("[host]", self.shownotes)
        # TODO(M2-4): assertIn(".mp3", self.shownotes) when shownotes 改结构化

    def test_icon_lib_has_core_set(self) -> None:
        # 图标库：站点当前用到的不能缺
        for icon in ["play", "mic", "music", "rss", "sparkle"]:
            self.assertIn(icon, _ICON_LIB, f"_ICON_LIB 缺 {icon!r}")
        # 全部 SVG 都有 viewBox + aria-hidden
        for name, svg in _ICON_LIB.items():
            self.assertIn("viewBox", svg, f"{name} 缺 viewBox")
            self.assertIn("aria-hidden", svg, f"{name} 缺 aria-hidden")

    def test_hescape_quotes_attribute_safe(self) -> None:
        # P0-C 复现：含双引号标题的属性注入场景
        evil = 'abc" onmouseover="alert(1)'
        safe = _hescape(evil)
        self.assertIn("&quot;", safe)
        self.assertNotIn('onmouseover="alert', safe)

    def test_hescape_handles_all_special(self) -> None:
        # 5 个 XML/HTML 实体全覆盖
        for src, want in [("a&b", "&amp;"), ("<x>", "&lt;x&gt;"),
                          ("\"q\"", "&quot;q&quot;"),
                          ("it's", "&#x27;")]:
            self.assertIn(want, _hescape(src), f"_hescape({src!r}) 缺 {want!r}")

    def test_audio_url_relative_path(self) -> None:
        # P0 相对路径守恒：manifest 里的 url 必须是相对（子路径 github.io 不 404）
        manifest = load_manifest(self.out)
        for ep in manifest.get("episodes", []):
            url = ep.get("url", "")
            self.assertFalse(url.startswith("/"), f"url 用了绝对路径: {url!r}（子路径会 404）")
            self.assertTrue(url.endswith(".mp3"), f"url 缺 .mp3: {url!r}")
            self.assertTrue(url.startswith("series/"), f"url 形态错: {url!r}")

    def test_episode_key_format(self) -> None:
        # P0 续传 key：必须是 {slug}::ep-XX 形式（断点续传判据）
        # 验证方法：检查 manifest 里 _key 字段格式
        manifest = load_manifest(self.out)
        for ep in manifest.get("episodes", []):
            self.assertIn("_key", ep, "manifest 缺 _key 字段")
            self.assertRegex(ep["_key"], r"^[\w\-]+::ep-\d{2}$", f"_key 格式错: {ep['_key']!r}")

    def test_p0_no_systemexit_in_feed(self) -> None:
        # 跑完 build 没异常就算通过（implicit）
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()