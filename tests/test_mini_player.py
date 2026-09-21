"""M3 mini player 守恒测试 — 已提交的 output/index.html 必须含吸底 player 结构。

关于"不自己触发 build"（2026-09-21 修正）
----------------------------------------
本文件原先在 ``setUpClass`` 里跑 ``python -m src.build drafts/ --skip-audio``，
理由是"确保 output/index.html 是最新的"。这是错的，有两个真实代价：

1. **污染生产目录**：``--skip-audio`` 只在 ``source_hash`` 命中时幂等跳过；只要
   drafts 里有一集的 hash 与 manifest 不符（改稿后未重渲的正常状态），这一步就会
   重渲它并**刷掉 shownotes 日期**、改写 manifest —— 跑一次测试就多两处 git 脏改动。
2. **CI 里纯冗余**：publish.yml 的顺序是「Unit tests」(L49) → 「Render index + feed」
   (L61) → deploy，测试跑完几秒后还会全量 build 一次。这里的 build 让全量渲染做两遍。

所以本测试改为**只读断言**：验证「已经提交进仓库、即将被部署的那份 index.html」
符合 player 契约 —— 这比验证临时构建的产物更贴近要守的东西。
产物缺失时 skip 并提示先跑构建，不再代劳。
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "output" / "index.html"


@unittest.skipUnless(
    INDEX.exists(),
    "缺 output/index.html；先跑 `python -m src.build drafts/ --skip-audio` 再测",
)
class MiniPlayerRenderTest(unittest.TestCase):

    def test_player_audio_in_dom(self) -> None:
        """player-audio 元素在 DOM 里恰好 1 个（排除 player.js 注释里的字符串）。"""
        import re
        text = INDEX.read_text(encoding="utf-8")
        # 只数 <script> 外的标签（DOM 里的 audio 元素）
        # 简单方法：去掉 <script>...</script> 块
        no_script = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL)
        n = len(re.findall(r'<audio\s+id="player-audio"', no_script))
        self.assertEqual(n, 1, f"应有 1 个 #player-audio DOM 元素，实际 {n}")
        self.assertIn('id="player-audio" preload="metadata"', text)
        self.assertNotIn('id="player-audio" controls', text, "player-audio 不该有 controls 属性")

    def test_no_native_audio_controls(self) -> None:
        """P0-1 守恒：不应有原生 <audio controls>（剥 script 后扫 DOM）。"""
        import re
        text = INDEX.read_text(encoding="utf-8")
        no_script = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL)
        audio_tags = re.findall(r"<audio\s[^>]*>", no_script)
        for tag in audio_tags:
            self.assertNotIn("controls", tag, f"原生 audio 不应带 controls: {tag}")

    def test_player_close_clears_src(self) -> None:
        """player.js 的 close() 必须 audio.removeAttribute('src') + audio.load()。"""
        player_js = (ROOT / "templates" / "player.js").read_text(encoding="utf-8")
        self.assertIn("removeAttribute('src')", player_js)
        self.assertIn("audio.load()", player_js)

    def test_player_progress_is_slider(self) -> None:
        """进度条 role='slider' + aria-valuenow/min/max。"""
        text = INDEX.read_text(encoding="utf-8")
        self.assertIn('class="player-progress"', text)
        self.assertIn('role="slider"', text)
        self.assertIn('aria-valuenow="0"', text)

    def test_ep_play_buttons_have_data_attrs(self) -> None:
        text = INDEX.read_text(encoding="utf-8")
        # data-action="play-now" 至少 3 个（latest 3 张）
        n = text.count('data-action="play-now"')
        self.assertGreaterEqual(n, 3, f"应至少 3 个 play-now 按钮，实际 {n}")

    def test_ep_card_has_data_attributes(self) -> None:
        """ep-card 必须含 data-audio / data-title / data-series 给 player 启动用。"""
        text = INDEX.read_text(encoding="utf-8")
        self.assertIn('data-audio="', text)
        self.assertIn('data-title="', text)
        self.assertIn('data-series="', text)
        self.assertIn('data-duration="', text)

    def test_a11y_aria_labels(self) -> None:
        """所有交互按钮必须有 aria-label。"""
        text = INDEX.read_text(encoding="utf-8")
        # player-btn 的 4 个按钮：toggle/mute/close + 1 个 player-toggle
        for label in ("播放或暂停", "静音", "关闭播放器", "立即播放"):
            self.assertIn(label, text, f"缺 aria-label: {label}")

    def test_player_js_injected(self) -> None:
        """templates/player.js 必须注入到 index.html（构建期替换占位符）。"""
        text = INDEX.read_text(encoding="utf-8")
        self.assertIn("MediaMetadata", text, "MediaSession 应注入")
        self.assertIn("playEpisode", text, "playEpisode 函数应注入")
        self.assertNotIn("__PLAYER_JS__", text, "占位符未替换（player.js 未注入）")


if __name__ == "__main__":
    unittest.main()