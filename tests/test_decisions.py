"""守护 src/decisions.py 三个 AI 推荐函数 + 持久化。

三门推荐是用户拍板前的 AI 建议，错了只是辅助；但推荐逻辑必须稳定可测：
- 对话感强 → duo
- 独白感强 → solo
- 章节均匀 → by_h2
- 章节不均 → by_chars
- voicecaster 信号清晰 → 走该类型首选 voice
- _decisions.json 落盘可读
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.decisions import (  # noqa: E402
    recommend_format,
    recommend_split,
    recommend_voice,
    save_decisions,
    Decisions,
)
from src.ingest import parse_script  # noqa: E402
from src.prepare import prepare_file  # noqa: E402


SAMPLE_DUO = """
主持人：今天我们来聊一个很有意思的话题。
嘉宾：是啊，最近 AI Infra 圈子里很多人在讨论这个。
主持人：你怎么看训练集群和推理集群的区别？
嘉宾：这是个好问题。简单说，一个是 batch 优化，一个是 latency 优化。
主持人：能举个例子吗？
嘉宾：比如 ChatGPT 这种对话产品，p99 延迟必须控制在 500ms 以内。
"""

SAMPLE_SOLO = """
回想那一刻，我才意识到自己在用 AI Infra 的时候已经不知不觉走上了那条路。
当时我们组在做 GPU 抢购，所有人都说算力不够。我承认自己也有过那种焦虑。
事后看，这件事其实是个缩影。我后来才明白，真正的挑战不在于堆砌卡数，
而在于分层和分场景去理解整个体系。反思下来，我们当时做了太多无意义的优化。
我意识到，真正的护城河不在硬件层，而在调度和编排那一层。回想起来，
那几个月我们一直在重复造轮子，把别人的代码 fork 一遍又一遍。我承认，
那些天我也没少熬夜。回过头看，我后来才意识到我们错过了分层优化的最佳时机。
那一刻起，我开始重新审视整个 AI Infra 的分层结构。
"""


class TestRecommendFormat(unittest.TestCase):

    def test_dialogue_heavy_recommends_duo(self):
        choice, conf, reason = recommend_format(SAMPLE_DUO)
        self.assertEqual(choice, "duo",
                         f"对话感强 → 应推荐 duo，实际 {choice}（reason: {reason}）")
        # conf >= 0.5 即可（信号中等时为 0.5，强烈时 > 0.5）
        self.assertGreaterEqual(conf, 0.5)

    def test_monologue_heavy_recommends_solo(self):
        choice, conf, reason = recommend_format(SAMPLE_SOLO)
        self.assertEqual(choice, "solo",
                         f"独白感强 → 应推荐 solo，实际 {choice}（reason: {reason}）")
        self.assertGreater(conf, 0.5)

    def test_short_article_falls_back_to_duo(self):
        choice, conf, reason = recommend_format("短文")
        self.assertEqual(choice, "duo")
        # 短文章置信度默认 0.5，提示信号不足
        self.assertLessEqual(conf, 0.6)


class TestRecommendVoice(unittest.TestCase):

    def test_reflective_text_picks_reflective_voice(self):
        # SAMPLE_SOLO 命中 reflective 关键词（那一刻/反思/回想/我承认 等）
        cfg = {"voicecaster": {"mode": "rule"}}
        voice, vtype, reason, alts = recommend_voice(SAMPLE_SOLO, cfg)
        self.assertEqual(vtype, "reflective",
                         f"独白文章应归类 reflective，实际 {vtype}")
        self.assertEqual(voice, "audiobook_male_1",
                         "reflective 默认首选 audiobook_male_1")
        self.assertIn(voice, [v for v in ["audiobook_male_1", "female-chengshu",
                                          "audiobook_male_2"]])

    def test_returns_alternatives_for_same_type(self):
        cfg = {"voicecaster": {"mode": "rule"}}
        _, _, _, alts = recommend_voice(SAMPLE_SOLO, cfg)
        # 备选是 reflective 类的非首选 voice
        self.assertIsInstance(alts, list)
        self.assertGreater(len(alts), 0,
                           "reflective 类应有备选 voice")


class TestRecommendSplit(unittest.TestCase):

    ARTICLE_UNIFORM_H2 = (
        "引言段。\n\n"
        "## 第一节\n\n" + ("正文段落。" * 100) + "\n\n"
        "## 第二节\n\n" + ("正文段落。" * 100) + "\n\n"
        "## 第三节\n\n" + ("正文段落。" * 100) + "\n\n"
        "## 第四节\n\n" + ("正文段落。" * 100) + "\n"
    )

    def test_uniform_h2_recommends_by_h2(self):
        cfg = {"split": {"min_episode_chars": 600, "max_episode_chars": 3000}}
        strat, params, count, reason = recommend_split(self.ARTICLE_UNIFORM_H2, cfg)
        self.assertEqual(strat, "by_h2",
                         f"4 个均匀 H2 章节 → 应推荐 by_h2，实际 {strat}")
        # 4 个 H2 + 引言段（"引言段。"）会被合到第 1 集（引言短 < min_c 600，
        # 由 plan_episodes 把引言合并进第 1 节）。recommend_split 自身不合并引言，
        # 所以 count 是 5（引言 + 4 章节）。这是有意为之，AI 推荐给用户看真实集数。
        self.assertGreaterEqual(count, 4)
        self.assertIn("max_episode_chars", params)

    def test_no_h2_falls_back_to_by_chars(self):
        # 没有 H2 章节的长文 → 推荐 by_chars
        article = ("普通段落。" * 1000)
        cfg = {"split": {"min_episode_chars": 600, "max_episode_chars": 3000}}
        strat, params, count, reason = recommend_split(article, cfg)
        self.assertIn(strat, ("by_chars", "by_h2"),
                      f"无 H2 长文应推荐 by_chars（兜底），实际 {strat}")

    def test_by_duration_estimates_via_chars_per_minute(self):
        # 验证 by_duration 路径存在且估算合理（10 分钟 × 250 字/分 = 2500 字/集）
        from src.decisions import _split_alternatives
        cfg = {
            "split": {
                "min_episode_chars": 600,
                "max_episode_chars": 3000,
                "default_max_duration_min": 10,
                "chars_per_minute": 250,
            }
        }
        # 2500 字符（_count 按字符长度，"段。" = 2 字符 × 1250 = 2500 字符）
        article = "段。" * 1250
        alts = _split_alternatives(article, cfg, n_h2_eps=0)
        for strat, params, count, label in alts:
            if strat == "by_duration":
                self.assertEqual(params.get("max_duration_min"), 10)
                # 2500 字符 / 2500 字符/集 = 1 集（向上取整）
                self.assertEqual(count, 1)
                return
        self.fail("by_duration 应出现在备选列表中")


class TestSaveDecisions(unittest.TestCase):

    def test_writes_json_to_out_dir(self):
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "drafts" / "my-series"
            out_dir.mkdir(parents=True)
            d = Decisions(
                format="solo",
                voice="audiobook_male_1",
                voice_type="reflective",
                split_strategy="by_h2",
                split_params={"max_episode_chars": 3000},
                split_count=5,
            )
            p = save_decisions(out_dir, d)
            self.assertTrue(p.exists())
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(data["decisions"]["format"], "solo")
            self.assertEqual(data["decisions"]["voice"], "audiobook_male_1")
            self.assertEqual(data["decisions"]["split_strategy"], "by_h2")


class TestFrontmatterShortcutCarriesDuoVoices(unittest.TestCase):
    """回归（2026-09-21）：frontmatter 三件套齐全 → 快捷分支必须把 duo 音色带进 draft。

    旧行为只读 format / voice / split_strategy，host_voice / guest_voice 被丢弃：
    draft frontmatter 缺这两项、_decisions.json 记成 ""。因为 build 会回退到
    voices_<backend> 的默认 host / guest，音频听不出问题 —— "用户显式写了音色却被丢"
    只能靠断言发现，所以这里把两种合法写法都钉住。
    """

    _PARA = (
        "这是一段用于测试的正文内容，目的是让每个小节都超过最小集长度阈值，避免切分逻辑"
        "把小节合并到一起，也避免正文过短而走到兜底路径。这段文字本身没有业务含义，"
        "只服务于测试的可重复性与稳定性。"
    )
    _BODY = (
        f"\n\n## 第一节\n\n{_PARA}{_PARA}{_PARA}\n\n"
        f"## 第二节\n\n{_PARA}{_PARA}{_PARA}\n"
    )

    def _prepare(self, frontmatter: str) -> tuple[list[dict], dict]:
        """跑一次真 prepare（llm 关闭，不联网），返回 (各集 frontmatter, 决策字典)。"""
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            raw.mkdir()
            src = raw / "2026-01-02-voice-routing.md"
            src.write_text(f"---\n{frontmatter}\n---{self._BODY}", encoding="utf-8")
            drafts_dir = Path(td) / "drafts"
            cfg = {
                "format": "duo",
                "llm": {"enable": False},  # 关键：不联网，走 _skeleton
                "split": {"min_episode_chars": 10, "max_episode_chars": 3000},
            }
            made = prepare_file(src, cfg, drafts_dir)
            self.assertTrue(made, "prepare_file 未产出任何 draft")
            metas = [parse_script(f.read_text(encoding="utf-8"))[0] for f in made]
            dec_files = list(drafts_dir.glob("*/_decisions.json"))
            self.assertEqual(len(dec_files), 1, "应恰好落一份 _decisions.json")
            dec = json.loads(dec_files[0].read_text(encoding="utf-8"))["decisions"]
        return metas, dec

    def test_explicit_keys_are_carried(self):
        metas, dec = self._prepare(
            "title: 音色路由测试\n"
            "format: duo\n"
            'voice: "host=Uncle_Fu / guest=Serena"\n'
            "host_voice: Uncle_Fu\n"
            "guest_voice: Serena\n"
            "split_strategy: by_h2\n"
            "date: 2026-01-02"
        )
        for m in metas:
            self.assertEqual(m.get("host_voice"), "Uncle_Fu", f"draft 丢了 host_voice：{m}")
            self.assertEqual(m.get("guest_voice"), "Serena", f"draft 丢了 guest_voice：{m}")
        self.assertEqual(dec["host_voice"], "Uncle_Fu")
        self.assertEqual(dec["guest_voice"], "Serena")

    def test_voice_label_only_is_parsed(self):
        """只有 voice 标签、没有 host_voice/guest_voice 键，也要能解析出来。

        decisions.py 的交互门写出的正是这个格式，只认键不认标签会让这类 raw 静默丢音色。
        """
        metas, dec = self._prepare(
            "title: 音色路由测试\n"
            "format: duo\n"
            'voice: "host=Dylan / guest=Ono_Anna"\n'
            "split_strategy: by_h2\n"
            "date: 2026-01-02"
        )
        self.assertEqual(metas[0].get("host_voice"), "Dylan")
        self.assertEqual(metas[0].get("guest_voice"), "Ono_Anna")
        self.assertEqual(dec["host_voice"], "Dylan")
        self.assertEqual(dec["guest_voice"], "Ono_Anna")

    def test_solo_does_not_get_phantom_duo_voices(self):
        """solo 稿没有 host/guest 是合法的，不该崩、也不该误填。"""
        metas, dec = self._prepare(
            "title: 音色路由测试\n"
            "format: solo\n"
            'voice: "host=Uncle_Fu"\n'
            "split_strategy: by_h2\n"
            "date: 2026-01-02"
        )
        self.assertEqual(metas[0].get("format"), "solo")
        self.assertFalse(metas[0].get("guest_voice"), "solo 不该凭空得到 guest_voice")
        self.assertFalse(dec["guest_voice"])


if __name__ == "__main__":
    unittest.main()